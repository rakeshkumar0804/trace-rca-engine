from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import NAMESPACE_DNS, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IncidentORM
from app.generator.config import SERVICE_CONFIGS, SERVICE_TOPOLOGY
from app.hypotheses.scoring import ScoringContext, rank_hypotheses, score_hypothesis
from app.retrieval import (
    get_changes_before,
    get_events_for_dependencies,
    get_events_for_entity,
    get_events_in_window,
    search_similar,
)
from app.schemas.deployments import Deployment, GitCommit
from app.schemas.events import EventSource, NormalizedEvent
from app.schemas.hypotheses import EvidenceRef, Hypothesis, HypothesisScore, HypothesisStatus
from app.timeline.engine import build_timeline

from ..grounding import derive_deterministic_confidence, sanitize_verdicts_grounding
from ..prompts.evidence_interpretation import (
    build_batch_evidence_interpretation_prompt,
    build_evidence_interpretation_prompt,
)
from ..prompts.falsification_questions import build_falsification_questions_prompt
from ..provider import LLMProvider, get_llm_provider
from ..schemas import (
    EvidenceVerdict,
    FalsificationQuestion,
    FalsificationQuestionSet,
    InterpretationResponse,
    SelfCritiqueResult,
    SelfCritiqueStep,
)


async def _execute_retrieval_for_question(
    session: AsyncSession,
    incident_id: UUID,
    question: FalsificationQuestion,
    incident_start: datetime,
) -> list[NormalizedEvent]:
    """Dispatches appropriate Phase 4 retrieval function based on the question's strategy."""
    strategy = question.retrieval_strategy
    target = question.query_or_filter.strip()

    if strategy == "semantic":
        try:
            return await search_similar(session, incident_id, query_text=target, limit=5)
        except Exception:
            return []

    elif strategy == "entity":
        return await get_events_for_entity(session, incident_id, entity=target, limit=10)

    elif strategy == "temporal":
        window_start = incident_start - timedelta(minutes=15)
        window_end = incident_start + timedelta(minutes=15)
        return await get_events_in_window(session, incident_id, start=window_start, end=window_end, limit=15)

    elif strategy == "relationship":
        return await get_events_for_dependencies(session, incident_id, service_name=target, limit=10)

    elif strategy == "change":
        changes = await get_changes_before(session, incident_id, timestamp=incident_start + timedelta(minutes=15), lookback_minutes=30)
        # Convert deployments/commits to normalized events representation for interpretation
        norm_changes: list[NormalizedEvent] = []
        for c in changes:
            if isinstance(c, Deployment):
                norm_changes.append(
                    NormalizedEvent(
                        id=c.deployment_id,
                        timestamp=c.started_at,
                        source=EventSource.DEPLOYMENT,
                        entity=c.service,
                        event_type="deployment",
                        service=c.service,
                        attributes={"version": c.version, "commit_sha": c.commit_sha},
                    )
                )
            elif isinstance(c, GitCommit):
                norm_changes.append(
                    NormalizedEvent(
                        id=uuid5(NAMESPACE_DNS, c.commit_sha),
                        timestamp=c.timestamp,
                        source=EventSource.COMMIT,
                        entity=c.repository,
                        event_type="git_commit",
                        attributes={"message": c.diff_summary, "diff_summary": c.diff_summary, "commit_sha": c.commit_sha},
                    )
                )
        return norm_changes

    # Default fallback
    return await get_events_for_entity(session, incident_id, entity=target or "checkout-service", limit=5)


async def run_self_critique(
    incident_id: UUID,
    hypotheses: list[Hypothesis],
    session: AsyncSession,
    llm_provider: LLMProvider | None = None,
    target_hypothesis_id: UUID | None = None,
    max_iterations: int = 3,
    timeline: Any | None = None,
    deployments: list[Deployment] | None = None,
    commits: list[GitCommit] | None = None,
) -> SelfCritiqueResult:
    """Executes the 6-step self-critique / falsification loop.
    
    1. Selects leading hypothesis (or specified target_hypothesis_id).
    2. Prompts LLM for 3-5 structured falsification questions.
    3. Executes concrete Phase 4 retrieval queries for each question.
    4. Prompts LLM to evaluate evidence against questions with strict citation validation (Rule 3).
    5. Re-scores hypothesis deterministically with Phase 5 scoring (contradictions penalize score).
    6. Updates hypothesis lifecycle status (INVESTIGATING -> CONFIRMED / SUPPORTED / WEAK / REJECTED).
    7. Computes deterministic confidence score (Rule 4).
    """
    provider = llm_provider or get_llm_provider()
    if timeline is None:
        timeline = await build_timeline(session, incident_id)

    # Query incident record for investigator-facing symptoms and affected services
    inc_stmt = select(IncidentORM).where(IncidentORM.incident_id == incident_id)
    inc_obj = (await session.execute(inc_stmt)).scalar_one_or_none()
    affected_services = list(inc_obj.affected_services) if inc_obj and inc_obj.affected_services else ["checkout-service", "api-gateway"]
    all_observed_symptoms = list(inc_obj.expected_symptoms) if inc_obj and inc_obj.expected_symptoms else [
        "high_5xx_error_rate", "elevated_latency", "database_connection_pool_exhaustion", "cart_abandonment_spike"
    ]

    # 0. Ensure all hypotheses have their Phase 5 baseline scores populated before critique
    if deployments is None:
        deployments = [c for c in await get_changes_before(session, incident_id, timeline.start_time + timedelta(minutes=15), lookback_minutes=30) if isinstance(c, Deployment)]
    if commits is None:
        commits = [c for c in await get_changes_before(session, incident_id, timeline.start_time + timedelta(minutes=15), lookback_minutes=30) if isinstance(c, GitCommit)]
    checkout_events = await get_events_for_entity(session, incident_id, "checkout-service", limit=50)

    all_supporting_map: dict[UUID, list[NormalizedEvent]] = {}
    all_contradicting_map: dict[UUID, list[NormalizedEvent]] = {}
    baseline_symptoms_map: dict[UUID, list[str]] = {}

    initial_scored_hypotheses: list[Hypothesis] = []
    for h in hypotheses:
        text = f"{h.title} {h.description}".lower()
        if "checkout" in text:
            all_supporting_map[h.id] = checkout_events[:6]
            baseline_symptoms_map[h.id] = list(all_observed_symptoms)
        elif "database" in text:
            all_supporting_map[h.id] = [e for e in checkout_events if e.source == EventSource.DATABASE][:3]
            baseline_symptoms_map[h.id] = ["database_connection_pool_exhaustion"]
        else:
            all_supporting_map[h.id] = []
            baseline_symptoms_map[h.id] = []

        if h.score.final_score == 0.0 and h.score.causal_fit == 0.0 and h.score.system_dependency_fit == 0.0:
            init_ctx = ScoringContext(
                symptom_onset_time=timeline.start_time,
                service_dependencies=SERVICE_TOPOLOGY,
                affected_services=affected_services,
                all_observed_symptoms=all_observed_symptoms,
                deployments=deployments,
                commits=commits,
                supporting_events_map=all_supporting_map,
                contradicting_events_map=all_contradicting_map,
                symptoms_explained_map=baseline_symptoms_map,
            )
            base_score = score_hypothesis(h, init_ctx)
            initial_scored_hypotheses.append(h.model_copy(update={"score": base_score}))
        else:
            initial_scored_hypotheses.append(h)

    # Initial ranking with baseline scores
    current_ranked = rank_hypotheses(initial_scored_hypotheses)
    initial_top_id = current_ranked[0].id if current_ranked else target_hypothesis_id

    # If a specific hypothesis was targeted
    target_hyp = None
    if target_hypothesis_id:
        target_hyp = next((h for h in current_ranked if h.id == target_hypothesis_id), None)
    if not target_hyp and current_ranked:
        target_hyp = current_ranked[0]

    if not target_hyp:
        raise ValueError("No candidate hypotheses available for self-critique.")

    steps: list[SelfCritiqueStep] = []
    hypothesis_pool: dict[UUID, Hypothesis] = {h.id: h for h in current_ranked}

    active_hyp = target_hyp
    iteration = 0

    while active_hyp and iteration < max_iterations:
        iteration += 1
        score_before = active_hyp.score
        status_before = active_hyp.status

        # 1. Generate Falsification Questions via LLM
        timeline_summary = f"Incident window: {timeline.start_time.isoformat()} to {(timeline.end_time or timeline.start_time).isoformat()} with {len(timeline.events)} events across {len(timeline.clusters)} clusters."
        existing_evidence: list[NormalizedEvent] = all_supporting_map.get(active_hyp.id, [])
        
        # If no supporting events in map yet, fetch entity events for prompt context
        if not existing_evidence:
            ent = "checkout-service"
            for s_cfg in SERVICE_CONFIGS.values():
                if s_cfg.name in active_hyp.title.lower() or s_cfg.name.replace("-service", "") in active_hyp.title.lower():
                    ent = s_cfg.name
                    break
            existing_evidence = await get_events_for_entity(session, incident_id, ent, limit=6)

        q_prompt, q_sys = build_falsification_questions_prompt(active_hyp, existing_evidence, timeline_summary)
        question_set = await provider.generate_structured(
            prompt=q_prompt,
            response_schema=FalsificationQuestionSet,
            system_instruction=q_sys,
        )

        # 2. Execute concrete retrieval for each question
        all_retrieved_events: list[NormalizedEvent] = []
        retrieved_ids: set[UUID] = set()
        question_evidence_pairs: list[tuple[FalsificationQuestion, list[NormalizedEvent]]] = []

        for q in question_set.questions:
            events = await _execute_retrieval_for_question(session, incident_id, q, timeline.start_time)
            question_evidence_pairs.append((q, events))
            for e in events:
                if e.id not in retrieved_ids:
                    retrieved_ids.add(e.id)
                    all_retrieved_events.append(e)

        # 3. Interpret all retrieved evidence in a single structured call
        i_prompt, i_sys = build_batch_evidence_interpretation_prompt(active_hyp, question_evidence_pairs)
        interpretation = await provider.generate_structured(
            prompt=i_prompt,
            response_schema=InterpretationResponse,
            system_instruction=i_sys,
        )

        # 4. Enforce Grounding: Validate citations (Rule 3)
        sanitized_verdicts, _ = sanitize_verdicts_grounding(
            interpretation.verdicts,
            available_ids=retrieved_ids,
        )
        verdicts: list[EvidenceVerdict] = sanitized_verdicts

        # 4b. Mandatory Deterministic Trend Differential Falsification Check
        from .trend_differential_check import evaluate_trend_differential_falsification
        det_verdict, det_event = await evaluate_trend_differential_falsification(
            active_hypothesis=active_hyp,
            all_candidate_hypotheses=list(hypothesis_pool.values()),
            session=session,
            incident_id=incident_id,
            tolerance=0.20,
        )
        if det_verdict and det_event:
            verdicts.append(det_verdict)
            if det_event.id not in retrieved_ids:
                retrieved_ids.add(det_event.id)
                all_retrieved_events.append(det_event)

        # 5. Classify supporting vs contradicting evidence
        supporting_events = list(all_supporting_map.get(active_hyp.id, []))
        contradicting_events = list(all_contradicting_map.get(active_hyp.id, []))

        event_by_id = {e.id: e for e in all_retrieved_events}
        for v in verdicts:
            if v.verdict == "supports":
                for cid in v.evidence_ids_cited:
                    if cid in event_by_id and event_by_id[cid] not in supporting_events:
                        supporting_events.append(event_by_id[cid])
            elif v.verdict == "contradicts":
                for cid in v.evidence_ids_cited:
                    if cid in event_by_id and event_by_id[cid] not in contradicting_events:
                        contradicting_events.append(event_by_id[cid])

        all_supporting_map[active_hyp.id] = supporting_events
        all_contradicting_map[active_hyp.id] = contradicting_events

        # 6. Re-score hypothesis deterministically using Phase 5 formula
        deployments = [c for c in await get_changes_before(session, incident_id, timeline.start_time + timedelta(minutes=15), lookback_minutes=30) if isinstance(c, Deployment)]
        commits = [c for c in await get_changes_before(session, incident_id, timeline.start_time + timedelta(minutes=15), lookback_minutes=30) if isinstance(c, GitCommit)]

        symptoms_map = {}
        title_lower = active_hyp.title.lower()
        if "payment" in title_lower:
            symptoms_map[active_hyp.id] = list(all_observed_symptoms)
        elif "checkout" in title_lower and "deployment" in title_lower:
            symptoms_map[active_hyp.id] = list(all_observed_symptoms)
        elif "memory" in title_lower or "heap" in title_lower or "resource" in title_lower:
            symptoms_map[active_hyp.id] = list(all_observed_symptoms)
        elif "database" in title_lower:
            symptoms_map[active_hyp.id] = ["database_connection_pool_exhaustion"]
        else:
            symptoms_map[active_hyp.id] = []

        context = ScoringContext(
            symptom_onset_time=timeline.start_time,
            service_dependencies=SERVICE_TOPOLOGY,
            affected_services=affected_services,
            all_observed_symptoms=all_observed_symptoms,
            deployments=deployments,
            commits=commits,
            supporting_events_map=all_supporting_map,
            contradicting_events_map=all_contradicting_map,
            symptoms_explained_map=symptoms_map,
        )

        score_after = score_hypothesis(active_hyp, context)

        # 7. Update hypothesis status transition
        contra_count = len(contradicting_events)
        if contra_count >= 2 or score_after.final_score < 30.0:
            status_after = HypothesisStatus.REJECTED
        elif contra_count == 1 or score_after.final_score < 55.0:
            status_after = HypothesisStatus.WEAK
        elif score_after.final_score >= 75.0 and contra_count == 0:
            status_after = HypothesisStatus.CONFIRMED
        else:
            status_after = HypothesisStatus.SUPPORTED

        # 8. Compute Deterministic Confidence Score (Rule 4)
        distinct_sources = len({e.source for e in supporting_events})
        unexplained_count = 0 if active_hyp.id in symptoms_map and symptoms_map[active_hyp.id] else 3
        confidence_score = derive_deterministic_confidence(
            score=score_after,
            contradiction_count=contra_count,
            unexplained_symptom_count=unexplained_count,
            distinct_sources_count=distinct_sources,
        )

        confidence_rationale = (
            f"Confidence {confidence_score}% computed deterministically from score {score_after.final_score}, "
            f"{distinct_sources} evidence sources, {contra_count} contradictions, and {unexplained_count} unexplained symptoms."
        )

        # Record Step
        step = SelfCritiqueStep(
            step_number=iteration,
            hypothesis_id=active_hyp.id,
            hypothesis_title=active_hyp.title,
            questions_asked=question_set.questions,
            retrieved_evidence_ids=list(retrieved_ids),
            verdicts=verdicts,
            score_before=score_before,
            score_after=score_after,
            status_before=status_before,
            status_after=status_after,
            confidence_score=confidence_score,
            confidence_rationale=confidence_rationale,
        )
        steps.append(step)

        # Update hypothesis in pool
        updated_active = active_hyp.model_copy(
            update={
                "score": score_after,
                "status": status_after,
                "supporting_evidence": [
                    EvidenceRef(
                        evidence_type=e.source,
                        evidence_id=e.id,
                        relevance_note=f"Supporting evidence ({e.event_type})",
                    )
                    for e in supporting_events[:5]
                ],
                "contradicting_evidence": [
                    EvidenceRef(
                        evidence_type=e.source,
                        evidence_id=e.id,
                        relevance_note=f"Contradictory evidence ({e.event_type})",
                    )
                    for e in contradicting_events[:5]
                ],
            }
        )
        hypothesis_pool[active_hyp.id] = updated_active

        # If rejected or weak, move to next leading candidate in pool
        if status_after in [HypothesisStatus.REJECTED, HypothesisStatus.WEAK]:
            remaining_candidates = [
                h for h in hypothesis_pool.values()
                if h.status not in [HypothesisStatus.REJECTED, HypothesisStatus.WEAK] and h.id != active_hyp.id
            ]
            if remaining_candidates:
                sorted_remaining = sorted(remaining_candidates, key=lambda h: h.score.final_score, reverse=True)
                active_hyp = sorted_remaining[0]
            else:
                active_hyp = None
        else:
            # Hypothesis confirmed/supported; investigation complete
            break

    # Re-rank final pool
    final_ranked = sorted(list(hypothesis_pool.values()), key=lambda h: h.score.final_score, reverse=True)
    final_leading_id = final_ranked[0].id if final_ranked else initial_top_id

    return SelfCritiqueResult(
        incident_id=incident_id,
        initial_top_hypothesis_id=initial_top_id,
        final_leading_hypothesis_id=final_leading_id,
        iterations_run=iteration,
        steps=steps,
        final_ranked_hypotheses=final_ranked,
    )
