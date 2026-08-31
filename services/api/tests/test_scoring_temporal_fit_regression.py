import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
from uuid import uuid4

import pytest

# Ensure app package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.base import Base, get_db_session, reset_engine
from app.embeddings.ingest import ingest_incident_evidence
from app.embeddings.provider import DeterministicEmbeddingProvider
from app.generator import (
    generate_bad_deployment_db_exhaustion_incident,
    generate_healthy_environment,
)
from app.hypotheses.candidate_generation import generate_candidate_hypotheses
from app.hypotheses.scoring.temporal_fit import calculate_temporal_fit
from app.llm.provider import MockLLMProvider
from app.llm.self_critique.falsification_engine import run_self_critique
from app.timeline.engine import build_timeline


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

        return incident

    incident = asyncio.run(init_data())
    yield incident
    asyncio.run(reset_engine())


class TestTemporalFitScoringRegression:
    """Regression tests for temporal fit scoring calculation."""

    def test_payment_db_temporal_fit_does_not_jump_to_max_on_contradiction(self, setup_incident_db):
        """Regression test: Ensures payment_db hypothesis does not receive a max 20.0 temporal_fit score
        when its retrieved telemetry is contradicting rather than verified supporting cause events."""
        incident = setup_incident_db
        mock_llm = MockLLMProvider()

        async def run():
            async with get_db_session() as session:
                timeline = await build_timeline(session, incident.incident_id)
                candidates = await generate_candidate_hypotheses(incident.incident_id, timeline, session)
                payment_hyp = next(h for h in candidates if "database" in h.title.lower() or "payment_db" in h.title.lower())

                # Run self-critique on payment_db
                res = await run_self_critique(
                    incident_id=incident.incident_id,
                    hypotheses=candidates,
                    session=session,
                    llm_provider=mock_llm,
                    target_hypothesis_id=payment_hyp.id,
                    max_iterations=1,
                )

                step = res.steps[0]
                assert step.score_before.temporal_fit == 5.0, "Baseline temporal fit for unverified cause must be 5.0"
                # Temporal fit must NOT jump to 20.0 (maximum) because the retrieved evidence contradicted payment_db
                assert step.score_after.temporal_fit <= 5.0, (
                    f"Expected temporal_fit to remain <= 5.0 for contradicted hypothesis, got {step.score_after.temporal_fit}"
                )
                assert step.score_after.contradictory_evidence_penalty > 0.0, "Contradiction penalty must be applied"

        asyncio.run(run())

    def test_pure_temporal_fit_calculation_empty_candidate_events(self):
        """Unit test: When no candidate cause events are verified, temporal fit returns baseline 5.0."""
        from app.schemas.hypotheses import Hypothesis, HypothesisScore, HypothesisStatus

        hyp = Hypothesis(
            id=uuid4(),
            incident_id=uuid4(),
            title="Test Hypothesis",
            description="Test description",
            status=HypothesisStatus.CANDIDATE,
            score=HypothesisScore(
                temporal_fit=5.0,
                causal_fit=0.0,
                evidence_support=0.0,
                system_dependency_fit=0.0,
                change_proximity=0.0,
                contradictory_evidence_penalty=0.0,
                unexplained_symptoms_penalty=0.0,
                final_score=5.0,
            ),
        )

        score = calculate_temporal_fit(
            hypothesis=hyp,
            candidate_cause_events=[],
            symptom_onset_time=datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc),
        )
        assert score == 5.0
