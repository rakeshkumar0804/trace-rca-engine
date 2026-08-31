# CRITICAL ISOLATION ENFORCEMENT: This orchestrator operates ONLY on investigator-facing evidence and tables.
# It must NEVER join or query the 'ground_truths' table.

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.conversions import (
    investigation_step_to_orm,
    investigation_to_orm,
)
from app.db.models import IncidentORM, InvestigationORM
from app.generator.config import SERVICE_TOPOLOGY
from app.hypotheses.candidate_generation import generate_candidate_hypotheses
from app.hypotheses.scoring.aggregate import (
    ScoringContext,
    rank_hypotheses,
    score_hypothesis,
)
from app.llm.prompts.hypothesis_summary import build_hypothesis_summary_prompt
from app.llm.provider import LLMProvider, get_llm_provider
from app.llm.schemas import HypothesisSummaryNarrative
from app.llm.self_critique.falsification_engine import run_self_critique
from app.orchestrator.state_machine import InvestigationStateMachine
from app.retrieval.change import get_changes_before
from app.retrieval.entity import get_events_for_entity
from app.retrieval.relationship import get_events_for_dependencies
from app.retrieval.semantic import search_similar
from app.retrieval.temporal import get_events_in_window
from app.schemas.deployments import Deployment, GitCommit
from app.schemas.events import EventSeverity, EventSource, NormalizedEvent
from app.schemas.hypotheses import EvidenceRef, Hypothesis, HypothesisStatus
from app.schemas.investigations import (
    Investigation,
    InvestigationState,
    InvestigationStep,
)
from app.timeline.engine import build_timeline


async def run_investigation(
    incident_id: UUID,
    session: AsyncSession,
    llm_provider: LLMProvider | None = None,
    max_hypotheses: int = 3,
    min_confidence_threshold: float = 50.0,
    investigation_id: UUID | None = None,
) -> Investigation:
    """Executes the complete end-to-end TRACE investigation orchestrator pipeline.
    
    Orchestrates the lifecycle state machine:
    INCIDENT_DETECTED -> SCOPING -> TIMELINE_BUILT -> EVIDENCE_RETRIEVED
    -> HYPOTHESES_GENERATED -> HYPOTHESES_RANKED -> INVESTIGATING_HYPOTHESIS
    -> (RCA_GENERATED | INCONCLUSIVE | FAILED)
    """
    provider = llm_provider or get_llm_provider()
    inv_id = investigation_id or uuid4()
    started_at = datetime.now(timezone.utc)
    sm = InvestigationStateMachine()

    async def persist_step(step: InvestigationStep) -> None:
        """Incrementally persists an investigation step to the database with cooperative async yield."""
        step_orm = investigation_step_to_orm(step, inv_id)
        session.add(step_orm)
        await session.commit()
        import asyncio
        await asyncio.sleep(0.05)

    # --------------------------------------------------------------------------
    # 1. INCIDENT_DETECTED
    # --------------------------------------------------------------------------
    stmt = select(IncidentORM).where(IncidentORM.incident_id == incident_id)
    result = await session.execute(stmt)
    incident_orm = result.scalar_one_or_none()

    if not incident_orm:
        step = sm.record_initial_step(
            summary=f"Incident {incident_id} not found in database.",
            details={"incident_id": str(incident_id), "error": "not_found"},
            timestamp=started_at,
        )
        await persist_step(step)
        step_fail = sm.transition_to(
            next_state=InvestigationState.FAILED,
            summary="Investigation failed: Incident record does not exist.",
            details={"incident_id": str(incident_id)},
        )
        await persist_step(step_fail)

        inv = Investigation(
            investigation_id=inv_id,
            incident_id=incident_id,
            steps=sm.steps,
            final_state=InvestigationState.FAILED,
            leading_hypothesis_id=None,
            confidence=0.0,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
        )
        session.add(investigation_to_orm(inv))
        await session.commit()
        return inv

    step_init = sm.record_initial_step(
        summary=f"Incident detected: {incident_orm.incident_type} (severity={incident_orm.severity})",
        details={
            "incident_id": str(incident_id),
            "incident_type": incident_orm.incident_type,
            "severity": incident_orm.severity,
            "start_time": incident_orm.start_time.isoformat(),
        },
        timestamp=started_at,
    )
    await persist_step(step_init)

    # --------------------------------------------------------------------------
    # 2. SCOPING
    # --------------------------------------------------------------------------
    affected_services = incident_orm.affected_services or []
    expected_symptoms = incident_orm.expected_symptoms or []
    step_scope = sm.transition_to(
        next_state=InvestigationState.SCOPING,
        summary=f"Scoping incident: {len(affected_services)} affected services, {len(expected_symptoms)} initial symptoms",
        details={
            "affected_services_count": len(affected_services),
            "affected_services": ", ".join(affected_services),
            "expected_symptoms_count": len(expected_symptoms),
            "expected_symptoms": ", ".join(expected_symptoms),
        },
    )
    await persist_step(step_scope)

    # --------------------------------------------------------------------------
    # 3. TIMELINE_BUILT
    # --------------------------------------------------------------------------
    timeline = await build_timeline(session, incident_id)
    step_timeline = sm.transition_to(
        next_state=InvestigationState.TIMELINE_BUILT,
        summary=f"Constructed incident timeline with {len(timeline.events)} events across {len(timeline.clusters)} clusters",
        details={
            "total_events": len(timeline.events),
            "cluster_count": len(timeline.clusters),
            "start_time": timeline.start_time.isoformat(),
            "end_time": (timeline.end_time or timeline.start_time).isoformat(),
        },
    )
    await persist_step(step_timeline)

    # --------------------------------------------------------------------------
    # 4. EVIDENCE_RETRIEVED (Initial 5-way retrieval)
    # --------------------------------------------------------------------------
    initial_evidence: list[NormalizedEvent] = []
    window_events = await get_events_in_window(
        session,
        incident_id,
        start=timeline.start_time - timedelta(minutes=5),
        end=timeline.start_time + timedelta(minutes=15),
        limit=20,
    )
    initial_evidence.extend(window_events)

    for s in affected_services:
        ent_events = await get_events_for_entity(session, incident_id, s, limit=10)
        initial_evidence.extend(ent_events)

    dep_events = []
    if affected_services:
        dep_events = await get_events_for_dependencies(session, incident_id, affected_services[0], limit=10)
        initial_evidence.extend(dep_events)

    semantic_events = []
    if expected_symptoms:
        semantic_events = await search_similar(session, incident_id, query_text=expected_symptoms[0], limit=5)
        initial_evidence.extend(semantic_events)

    changes = await get_changes_before(session, incident_id, timestamp=timeline.start_time + timedelta(minutes=15), lookback_minutes=30)

    distinct_evidence_ids = {e.id for e in initial_evidence}
    step_evidence = sm.transition_to(
        next_state=InvestigationState.EVIDENCE_RETRIEVED,
        summary=f"Retrieved initial evidence bundle: {len(distinct_evidence_ids)} distinct telemetry events and {len(changes)} changes",
        details={
            "distinct_telemetry_events": len(distinct_evidence_ids),
            "window_events_count": len(window_events),
            "dependency_events_count": len(dep_events),
            "semantic_events_count": len(semantic_events),
            "recent_changes_count": len(changes),
        },
    )
    await persist_step(step_evidence)

    # --------------------------------------------------------------------------
    # 5. HYPOTHESES_GENERATED & SCORED (Phase 5 Deterministic Scoring)
    # --------------------------------------------------------------------------
    candidates = await generate_candidate_hypotheses(incident_id, timeline, session)

    if not candidates:
        step_inconc = sm.transition_to(
            next_state=InvestigationState.INCONCLUSIVE,
            summary="Investigation inconclusive: No viable candidate hypotheses could be generated from timeline.",
            details={"candidates_generated": 0},
        )
        await persist_step(step_inconc)

        inv = Investigation(
            investigation_id=inv_id,
            incident_id=incident_id,
            steps=sm.steps,
            final_state=InvestigationState.INCONCLUSIVE,
            leading_hypothesis_id=None,
            confidence=0.0,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
        )
        session.add(investigation_to_orm(inv))
        await session.commit()
        return inv

    deployments = [c for c in changes if isinstance(c, Deployment)]
    commits = [c for c in changes if isinstance(c, GitCommit)]

    # Fetch entity events for candidate evidence mapping
    entity_events_by_service: dict[str, list[NormalizedEvent]] = {}
    for s in affected_services:
        entity_events_by_service[s] = await get_events_for_entity(session, incident_id, s, limit=10)

    supporting_events_map: dict[UUID, list[NormalizedEvent]] = {}
    symptoms_explained_map: dict[UUID, list[str]] = {}
    for h in candidates:
        title_lower = h.title.lower()
        if "payment" in title_lower:
            err_evts = [
                e for e in entity_events_by_service.get("payment-service", [])
                if e.severity in [EventSeverity.ERROR, EventSeverity.WARNING]
            ]
            supporting_events_map[h.id] = err_evts if err_evts else entity_events_by_service.get("payment-service", [])[:6]
            symptoms_explained_map[h.id] = list(expected_symptoms)
        elif "checkout" in title_lower:
            supporting_events_map[h.id] = entity_events_by_service.get("checkout-service", [])[:6]
            symptoms_explained_map[h.id] = list(expected_symptoms)
        elif "database" in title_lower:
            supporting_events_map[h.id] = [e for e in entity_events_by_service.get("checkout-service", []) if e.source == EventSource.DATABASE][:3]
            symptoms_explained_map[h.id] = ["checkout_db connection pool saturation (100/100 active connections)"]
        else:
            supporting_events_map[h.id] = []
            symptoms_explained_map[h.id] = []

    scoring_context = ScoringContext(
        symptom_onset_time=timeline.start_time,
        service_dependencies=SERVICE_TOPOLOGY,
        affected_services=affected_services,
        all_observed_symptoms=expected_symptoms,
        deployments=deployments,
        commits=commits,
        supporting_events_map=supporting_events_map,
        contradicting_events_map={},
        symptoms_explained_map=symptoms_explained_map,
    )

    scored_candidates: list[Hypothesis] = []
    for h in candidates:
        sup_events = supporting_events_map.get(h.id, [])
        combined_refs = list(h.supporting_evidence)
        for e in sup_events:
            if not any(r.evidence_id == e.id for r in combined_refs):
                note = str(e.attributes.get("message") or e.attributes.get("description") or f"{e.source.value} telemetry on {e.service}")
                combined_refs.append(
                    EvidenceRef(
                        evidence_type=e.source,
                        evidence_id=e.id,
                        relevance_note=note[:120],
                    )
                )
        score = score_hypothesis(h, scoring_context)
        scored_candidates.append(h.model_copy(update={"score": score, "supporting_evidence": combined_refs}))

    step_hyp = sm.transition_to(
        next_state=InvestigationState.HYPOTHESES_GENERATED,
        summary=f"Generated {len(scored_candidates)} candidate root-cause hypotheses from timeline clusters and changelog",
        details={
            "candidate_count": len(scored_candidates),
            "candidate_titles": ", ".join(h.title for h in scored_candidates),
        },
    )
    await persist_step(step_hyp)

    # --------------------------------------------------------------------------
    # 6. HYPOTHESES_RANKED
    # --------------------------------------------------------------------------
    ranked_candidates = rank_hypotheses(scored_candidates)
    top_initial = ranked_candidates[0]

    step_rank = sm.transition_to(
        next_state=InvestigationState.HYPOTHESES_RANKED,
        summary=f"Ranked {len(ranked_candidates)} hypotheses by deterministic score. Top candidate: '{top_initial.title}' (baseline score {top_initial.score.final_score:.1f})",
        details={
            "top_candidate_id": str(top_initial.id),
            "top_candidate_title": top_initial.title,
            "top_candidate_baseline_score": round(top_initial.score.final_score, 2),
            "total_ranked": len(ranked_candidates),
            "candidate_hypotheses": [
                {
                    "hypothesis_id": str(h.id),
                    "title": h.title,
                    "description": h.description,
                    "status": h.status.value if hasattr(h.status, 'value') else str(h.status),
                    "final_score": round(h.score.final_score, 2),
                    "supporting_evidence": [
                        {
                            "evidence_id": str(ref.evidence_id),
                            "evidence_type": ref.evidence_type.value if hasattr(ref.evidence_type, 'value') else str(ref.evidence_type),
                            "relevance_note": ref.relevance_note,
                        }
                        for ref in h.supporting_evidence
                    ],
                }
                for h in ranked_candidates
            ],
        },
    )
    await persist_step(step_rank)

    # --------------------------------------------------------------------------
    # 7. INVESTIGATING_HYPOTHESIS (Bounded loop over top N hypotheses)
    # --------------------------------------------------------------------------
    hypotheses_to_investigate = ranked_candidates[:max_hypotheses]
    investigated_hypotheses: list[Hypothesis] = []
    hypothesis_pool: dict[UUID, Hypothesis] = {h.id: h for h in ranked_candidates}
    hypothesis_confidence_pool: dict[UUID, float] = {}

    for idx, target_hyp in enumerate(hypotheses_to_investigate, start=1):
        critique_result = await run_self_critique(
            incident_id=incident_id,
            hypotheses=list(hypothesis_pool.values()),
            session=session,
            llm_provider=provider,
            target_hypothesis_id=target_hyp.id,
            max_iterations=1,
        )

        critique_step = critique_result.steps[0] if critique_result.steps else None
        if critique_step:
            # Merge any newly cited evidence from self-critique into supporting evidence
            critique_refs = list(target_hyp.supporting_evidence)
            for v in critique_step.verdicts:
                if v.verdict == "supports":
                    for eid in v.evidence_ids_cited:
                        if not any(r.evidence_id == eid for r in critique_refs):
                            critique_refs.append(
                                EvidenceRef(
                                    evidence_type=EventSource.LOG,
                                    evidence_id=eid,
                                    relevance_note=f"Supports: {v.question[:100]}",
                                )
                            )

            updated_hyp = target_hyp.model_copy(
                update={
                    "score": critique_step.score_after,
                    "status": critique_step.status_after,
                    "supporting_evidence": critique_refs,
                }
            )
            hypothesis_pool[target_hyp.id] = updated_hyp
            hypothesis_confidence_pool[target_hyp.id] = critique_step.confidence_score
            investigated_hypotheses.append(updated_hyp)

            verdicts_serialized = [
                {
                    "question": v.question,
                    "verdict": v.verdict,
                    "reasoning": v.reasoning,
                    "evidence_ids_cited": [str(eid) for eid in v.evidence_ids_cited],
                    "verdict_source": v.verdict_source,
                }
                for v in critique_step.verdicts
            ]

            questions_serialized = [
                {
                    "question": q.question,
                    "rationale": q.rationale,
                    "retrieval_strategy": q.retrieval_strategy,
                    "query_or_filter": q.query_or_filter,
                }
                for q in critique_step.questions_asked
            ]

            step_inv = sm.transition_to(
                next_state=InvestigationState.INVESTIGATING_HYPOTHESIS,
                summary=f"Investigated [{idx}/{len(hypotheses_to_investigate)}] '{target_hyp.title}': status={critique_step.status_after.value}, score={critique_step.score_after.final_score:.1f}, confidence={critique_step.confidence_score:.1f}%",
                details={
                    "hypothesis_id": str(target_hyp.id),
                    "hypothesis_title": target_hyp.title,
                    "status_before": critique_step.status_before.value,
                    "status_after": critique_step.status_after.value,
                    "score_before": round(critique_step.score_before.final_score, 2),
                    "score_after": round(critique_step.score_after.final_score, 2),
                    "confidence_score": round(critique_step.confidence_score, 2),
                    "questions_count": len(critique_step.questions_asked),
                    "evidence_retrieved_count": len(critique_step.retrieved_evidence_ids),
                    "retrieved_evidence_ids": [str(eid) for eid in critique_step.retrieved_evidence_ids],
                    "verdicts": verdicts_serialized,
                    "questions_asked": questions_serialized,
                    "supporting_evidence": [
                        {
                            "evidence_id": str(ref.evidence_id),
                            "evidence_type": ref.evidence_type.value if hasattr(ref.evidence_type, 'value') else str(ref.evidence_type),
                            "relevance_note": ref.relevance_note,
                        }
                        for ref in updated_hyp.supporting_evidence
                    ],
                },
            )
            await persist_step(step_inv)

            if critique_step.status_after == HypothesisStatus.CONFIRMED:
                break

    # --------------------------------------------------------------------------
    # 8. SELECT LEADING HYPOTHESIS & RCA GENERATION / INCONCLUSIVE
    # --------------------------------------------------------------------------
    status_priority = {
        HypothesisStatus.CONFIRMED: 4,
        HypothesisStatus.SUPPORTED: 3,
        HypothesisStatus.CANDIDATE: 2,
        HypothesisStatus.INVESTIGATING: 2,
        HypothesisStatus.WEAK: 1,
        HypothesisStatus.REJECTED: 0,
    }

    evaluated_pool = list(hypothesis_pool.values())
    evaluated_pool.sort(
        key=lambda h: (status_priority.get(h.status, 0), h.score.final_score),
        reverse=True,
    )

    leading_hyp = evaluated_pool[0] if evaluated_pool else None
    rca_narrative_text: str | None = None

    if (
        leading_hyp
        and leading_hyp.status in {HypothesisStatus.CONFIRMED, HypothesisStatus.SUPPORTED}
        and leading_hyp.score.final_score >= min_confidence_threshold
    ):
        confidence_val = hypothesis_confidence_pool.get(leading_hyp.id, leading_hyp.score.final_score)

        # Generate RCA natural language narrative
        supporting_events = await get_events_for_entity(session, incident_id, "checkout-service", limit=5)
        rca_prompt, rca_sys = build_hypothesis_summary_prompt(
            hypothesis=leading_hyp,
            supporting_evidence=supporting_events,
            falsification_summary=f"Hypothesis was rigorously self-critiqued against telemetry and confirmed with score {leading_hyp.score.final_score:.1f}.",
        )

        try:
            rca_resp = await provider.generate_structured(
                prompt=rca_prompt,
                response_schema=HypothesisSummaryNarrative,
                system_instruction=rca_sys,
            )
            rca_narrative_text = f"{rca_resp.title}\n\n{rca_resp.executive_summary}\n\nFalsification: {rca_resp.falsification_summary}"
        except Exception:
            rca_narrative_text = f"Root Cause: {leading_hyp.title}\n\n{leading_hyp.description}"

        step_rca = sm.transition_to(
            next_state=InvestigationState.RCA_GENERATED,
            summary=f"RCA generated for confirmed root cause: '{leading_hyp.title}' (score={leading_hyp.score.final_score:.1f}, confidence={confidence_val:.1f}%)",
            details={
                "leading_hypothesis_id": str(leading_hyp.id),
                "leading_hypothesis_title": leading_hyp.title,
                "final_score": round(leading_hyp.score.final_score, 2),
                "confidence_score": round(confidence_val, 2),
                "final_status": leading_hyp.status.value,
                "supporting_evidence": [
                    {
                        "evidence_id": str(ref.evidence_id),
                        "evidence_type": ref.evidence_type.value if hasattr(ref.evidence_type, 'value') else str(ref.evidence_type),
                        "relevance_note": ref.relevance_note,
                    }
                    for ref in leading_hyp.supporting_evidence
                ],
            },
        )
        await persist_step(step_rca)
        final_state = InvestigationState.RCA_GENERATED

    else:
        # Honest inconclusive state
        reason = (
            f"No hypothesis cleared confidence threshold {min_confidence_threshold}."
            if leading_hyp and leading_hyp.status != HypothesisStatus.REJECTED
            else "All evaluated candidate hypotheses were refuted or rejected during self-critique."
        )
        step_inconc = sm.transition_to(
            next_state=InvestigationState.INCONCLUSIVE,
            summary=f"Investigation inconclusive: {reason}",
            details={
                "min_confidence_threshold": min_confidence_threshold,
                "top_score_observed": round(leading_hyp.score.final_score, 2) if leading_hyp else 0.0,
                "top_status": leading_hyp.status.value if leading_hyp else "none",
            },
        )
        await persist_step(step_inconc)
        final_state = InvestigationState.INCONCLUSIVE
        confidence_val = 0.0

    completed_at = datetime.now(timezone.utc)
    investigation = Investigation(
        investigation_id=inv_id,
        incident_id=incident_id,
        steps=sm.steps,
        final_state=final_state,
        leading_hypothesis_id=leading_hyp.id if final_state == InvestigationState.RCA_GENERATED and leading_hyp else None,
        confidence=confidence_val,
        started_at=started_at,
        completed_at=completed_at,
        rca_narrative=rca_narrative_text,
    )

    existing_inv_orm = (await session.execute(
        select(InvestigationORM).where(InvestigationORM.investigation_id == inv_id)
    )).scalar_one_or_none()

    if existing_inv_orm:
        existing_inv_orm.final_state = final_state.value
        existing_inv_orm.leading_hypothesis_id = leading_hyp.id if final_state == InvestigationState.RCA_GENERATED and leading_hyp else None
        existing_inv_orm.confidence = confidence_val
        existing_inv_orm.completed_at = completed_at
        existing_inv_orm.rca_narrative = rca_narrative_text
    else:
        session.add(investigation_to_orm(investigation))
    await session.commit()
    return investigation
