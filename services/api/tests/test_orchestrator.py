import asyncio
from datetime import datetime, timezone
from pathlib import Path
import random
import sys
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

# Ensure app package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.base import Base, get_db_session, reset_engine
from app.db.models import InvestigationORM, InvestigationStepORM
from app.embeddings.ingest import ingest_incident_evidence
from app.embeddings.provider import DeterministicEmbeddingProvider
from app.generator import (
    generate_bad_deployment_db_exhaustion_incident,
    generate_healthy_environment,
)
from app.generator.config import SERVICE_TOPOLOGY
from app.hypotheses.candidate_generation import generate_candidate_hypotheses
from app.hypotheses.scoring.aggregate import (
    ScoringContext,
    rank_hypotheses,
    score_hypothesis,
)
from app.llm.provider import MockLLMProvider
from app.orchestrator.orchestrator import run_investigation
from app.orchestrator.state_machine import (
    InvalidStateTransitionError,
    InvestigationStateMachine,
)
from app.retrieval.entity import get_events_for_entity
from app.schemas.deployments import Deployment, GitCommit
from app.schemas.events import EventSource, NormalizedEvent
from app.schemas.investigations import InvestigationState


@pytest.fixture(scope="module")
def setup_incident_db():
    test_db_url = "sqlite+aiosqlite:///:memory:"
    engine = asyncio.run(reset_engine(test_db_url))

    async def init_data():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        start = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
        base_env = generate_healthy_environment(seed=42, start=start, duration_minutes=15)
        incident, bundle = generate_bad_deployment_db_exhaustion_incident(
            seed=42, base_environment=base_env, incident_start=start, duration_minutes=15
        )

        embedder = DeterministicEmbeddingProvider(dim=384)
        async with get_db_session() as session:
            await ingest_incident_evidence(session, incident, bundle, provider=embedder)

        return incident, bundle

    incident, bundle = asyncio.run(init_data())
    yield incident, bundle
    asyncio.run(reset_engine())


class TestStateMachine:
    """Tests for InvestigationStateMachine validation and transition rules."""

    def test_valid_transitions_sequence(self):
        sm = InvestigationStateMachine()
        step1 = sm.record_initial_step("Incident detected")
        assert step1.state == InvestigationState.INCIDENT_DETECTED
        assert step1.step_number == 1

        step2 = sm.transition_to(InvestigationState.SCOPING, "Scoping services")
        assert step2.state == InvestigationState.SCOPING
        assert step2.step_number == 2

        step3 = sm.transition_to(InvestigationState.TIMELINE_BUILT, "Timeline created")
        assert step3.state == InvestigationState.TIMELINE_BUILT
        assert step3.step_number == 3

    def test_invalid_transition_raises_error(self):
        sm = InvestigationStateMachine()
        sm.record_initial_step("Incident detected")

        # Cannot jump directly from INCIDENT_DETECTED to RCA_GENERATED
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            sm.transition_to(InvestigationState.RCA_GENERATED, "Jumping to RCA")

        assert "Invalid state transition" in str(exc_info.value)


class TestOrchestratorPipeline:
    """Tests for the end-to-end investigation orchestrator."""

    def test_full_investigation_confirms_true_cause(self, setup_incident_db):
        incident, _ = setup_incident_db
        mock_llm = MockLLMProvider()

        async def run():
            async with get_db_session() as session:
                inv = await run_investigation(
                    incident_id=incident.incident_id,
                    session=session,
                    llm_provider=mock_llm,
                    max_hypotheses=3,
                    min_confidence_threshold=50.0,
                )

                assert inv.final_state == InvestigationState.RCA_GENERATED
                assert inv.leading_hypothesis_id is not None
                assert inv.confidence == 89.1, f"Expected confidence 89.1%, got {inv.confidence}"
                assert inv.rca_narrative is not None
                assert len(inv.steps) >= 7

                # Verify leading hypothesis is the checkout deployment
                assert "checkout" in inv.rca_narrative.lower()

                # Verify steps sequence order
                states = [s.state for s in inv.steps]
                expected_prefix = [
                    InvestigationState.INCIDENT_DETECTED,
                    InvestigationState.SCOPING,
                    InvestigationState.TIMELINE_BUILT,
                    InvestigationState.EVIDENCE_RETRIEVED,
                    InvestigationState.HYPOTHESES_GENERATED,
                    InvestigationState.HYPOTHESES_RANKED,
                    InvestigationState.INVESTIGATING_HYPOTHESIS,
                ]
                for i, exp in enumerate(expected_prefix):
                    assert states[i] == exp

                # Check ranked step details: must show real baseline score 80.1 (not 0.0)
                ranked_step = next(s for s in inv.steps if s.state == InvestigationState.HYPOTHESES_RANKED)
                assert ranked_step.details["top_candidate_baseline_score"] == 80.1, (
                    f"Expected baseline score 80.1 in ranked step, got {ranked_step.details['top_candidate_baseline_score']}"
                )

        asyncio.run(run())

    def test_all_steps_persisted_to_database(self, setup_incident_db):
        incident, _ = setup_incident_db
        mock_llm = MockLLMProvider()

        async def run():
            async with get_db_session() as session:
                inv = await run_investigation(
                    incident_id=incident.incident_id,
                    session=session,
                    llm_provider=mock_llm,
                    max_hypotheses=2,
                )

                # Query database directly to verify persistence
                stmt = select(InvestigationStepORM).where(
                    InvestigationStepORM.investigation_id == inv.investigation_id
                ).order_by(InvestigationStepORM.step_number.asc())
                result = await session.execute(stmt)
                persisted_steps = result.scalars().all()

                assert len(persisted_steps) == len(inv.steps)
                for i, p_step in enumerate(persisted_steps, start=1):
                    assert p_step.step_number == i
                    assert p_step.state == inv.steps[i - 1].state.value

                # Verify investigation session record
                inv_stmt = select(InvestigationORM).where(
                    InvestigationORM.investigation_id == inv.investigation_id
                )
                inv_res = await session.execute(inv_stmt)
                persisted_inv = inv_res.scalar_one()
                assert persisted_inv.final_state == inv.final_state.value

        asyncio.run(run())

    def test_bounded_execution_limits(self, setup_incident_db):
        incident, _ = setup_incident_db
        mock_llm = MockLLMProvider()

        async def run():
            async with get_db_session() as session:
                # Set max_hypotheses = 1
                inv = await run_investigation(
                    incident_id=incident.incident_id,
                    session=session,
                    llm_provider=mock_llm,
                    max_hypotheses=1,
                )

                inv_steps = [s for s in inv.steps if s.state == InvestigationState.INVESTIGATING_HYPOTHESIS]
                assert len(inv_steps) == 1

        asyncio.run(run())

    def test_honest_inconclusive_when_threshold_unmet(self, setup_incident_db):
        incident, _ = setup_incident_db
        mock_llm = MockLLMProvider()

        async def run():
            async with get_db_session() as session:
                # Require an impossibly high score (e.g. 99.9) to test honest inconclusive path
                inv = await run_investigation(
                    incident_id=incident.incident_id,
                    session=session,
                    llm_provider=mock_llm,
                    max_hypotheses=2,
                    min_confidence_threshold=99.9,
                )

                assert inv.final_state == InvestigationState.INCONCLUSIVE
                assert inv.leading_hypothesis_id is None
                last_step = inv.steps[-1]
                assert last_step.state == InvestigationState.INCONCLUSIVE
                assert "inconclusive" in last_step.summary.lower()

        asyncio.run(run())

    def test_ground_truth_isolation_throughout_pipeline(self, setup_incident_db):
        incident, bundle = setup_incident_db
        mock_llm = MockLLMProvider()

        async def run():
            async with get_db_session() as session:
                inv = await run_investigation(
                    incident_id=incident.incident_id,
                    session=session,
                    llm_provider=mock_llm,
                    max_hypotheses=3,
                )

                # Ground truth root cause text
                gt = bundle.get("ground_truth") or incident.ground_truth
                gt_text = gt.root_cause

                # Verify no step summary or detail ever leaked ground truth text
                for step in inv.steps:
                    assert gt_text not in step.summary
                    for k, v in step.details.items():
                        assert gt_text not in str(v)

                if inv.rca_narrative:
                    assert gt_text not in inv.rca_narrative

        asyncio.run(run())

    def test_hypotheses_scored_before_ranking_and_shuffle_invariant(self, setup_incident_db):
        """Regression test for Bug 1: All candidates are scored before ranking and ranking is invariant to generation order."""
        incident, bundle = setup_incident_db
        from app.timeline.engine import build_timeline
        from app.retrieval.change import get_changes_before
        from datetime import timedelta

        async def run():
            async with get_db_session() as session:
                timeline = await build_timeline(session, incident.incident_id)
                candidates = await generate_candidate_hypotheses(incident.incident_id, timeline, session)
                assert len(candidates) >= 6

                changes = await get_changes_before(session, incident.incident_id, timestamp=timeline.start_time + timedelta(minutes=15), lookback_minutes=30)
                deployments = [c for c in changes if isinstance(c, Deployment)]
                commits = [c for c in changes if isinstance(c, GitCommit)]

                checkout_events = await get_events_for_entity(session, incident.incident_id, "checkout-service", limit=10)

                supporting_map: dict[UUID, list[NormalizedEvent]] = {}
                symptoms_explained_map: dict[UUID, list[str]] = {}
                for h in candidates:
                    text = f"{h.title} {h.description}".lower()
                    if "checkout" in text:
                        supporting_map[h.id] = checkout_events[:6]
                        symptoms_explained_map[h.id] = list(incident.expected_symptoms or [])
                    elif "database" in text or "payment" in text:
                        supporting_map[h.id] = [e for e in checkout_events if e.source == EventSource.DATABASE][:3]
                        symptoms_explained_map[h.id] = ["checkout_db connection pool saturation (100/100 active connections)"]
                    else:
                        supporting_map[h.id] = []
                        symptoms_explained_map[h.id] = []

                context = ScoringContext(
                    symptom_onset_time=timeline.start_time,
                    service_dependencies=SERVICE_TOPOLOGY,
                    affected_services=incident.affected_services or [],
                    all_observed_symptoms=incident.expected_symptoms or [],
                    deployments=deployments,
                    commits=commits,
                    supporting_events_map=supporting_map,
                    contradicting_events_map={},
                    symptoms_explained_map=symptoms_explained_map,
                )

                # Test with original order
                scored = [h.model_copy(update={"score": score_hypothesis(h, context)}) for h in candidates]
                # Assert every candidate has an evaluated score
                for h in scored:
                    assert h.score.final_score is not None

                ranked_original = rank_hypotheses(scored)
                assert "checkout" in ranked_original[0].title.lower()
                assert ranked_original[0].score.final_score == 80.1

                # Test with multiple shuffled permutations
                for seed in [1, 42, 99, 123]:
                    shuffled_candidates = list(candidates)
                    random.Random(seed).shuffle(shuffled_candidates)
                    scored_shuffled = [h.model_copy(update={"score": score_hypothesis(h, context)}) for h in shuffled_candidates]
                    ranked_shuffled = rank_hypotheses(scored_shuffled)

                    assert ranked_shuffled[0].id == ranked_original[0].id
                    assert ranked_shuffled[0].title == ranked_original[0].title
                    assert ranked_shuffled[0].score.final_score == 80.1

        asyncio.run(run())

    def test_investigation_confidence_is_strictly_independent_from_score(self, setup_incident_db):
        """Regression test for Bug 2: Investigation.confidence matches deterministic confidence calculation (89.1), not raw score (80.1)."""
        incident, _ = setup_incident_db
        mock_llm = MockLLMProvider()

        async def run():
            async with get_db_session() as session:
                inv = await run_investigation(
                    incident_id=incident.incident_id,
                    session=session,
                    llm_provider=mock_llm,
                    max_hypotheses=3,
                    min_confidence_threshold=50.0,
                )

                # Step investigating checkout-service has score_after = 80.1 and confidence_score = 89.1
                inv_step = next(s for s in inv.steps if s.state == InvestigationState.INVESTIGATING_HYPOTHESIS)
                raw_score = inv_step.details["score_after"]
                confidence_score = inv_step.details["confidence_score"]

                assert raw_score == 80.1
                assert confidence_score == 89.1
                assert inv.confidence == 89.1
                # Must be distinct and strictly independent
                assert inv.confidence != raw_score

        asyncio.run(run())
