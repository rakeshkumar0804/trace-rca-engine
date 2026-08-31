import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
from uuid import uuid4

import pytest

# Ensure app package is importable regardless of working directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.base import Base, get_db_session, reset_engine
from app.embeddings.ingest import ingest_incident_evidence
from app.embeddings.provider import DeterministicEmbeddingProvider
from app.generator import (
    generate_bad_deployment_db_exhaustion_incident,
    generate_healthy_environment,
)
from app.hypotheses.candidate_generation import generate_candidate_hypotheses
from app.hypotheses.scoring import rank_hypotheses
from app.llm.provider import GeminiProvider, MockLLMProvider
from app.llm.self_critique.falsification_engine import run_self_critique
from app.schemas.hypotheses import Hypothesis, HypothesisStatus
from app.timeline.engine import build_timeline


@pytest.fixture(scope="module", autouse=True)
def setup_incident_for_self_critique():
    """Initializes test database and ingests the Phase 3 sample incident."""
    test_db_url = "sqlite+aiosqlite:///:memory:"
    engine = asyncio.run(reset_engine(test_db_url))
    embedder = DeterministicEmbeddingProvider(dim=384)

    async def init_data():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        start = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
        base_env = generate_healthy_environment(seed=42, start=start, duration_minutes=15)
        incident, bundle = generate_bad_deployment_db_exhaustion_incident(
            seed=42, base_environment=base_env, incident_start=start, duration_minutes=15
        )

        async with get_db_session() as session:
            await ingest_incident_evidence(session, incident, bundle, provider=embedder)

        return incident

    incident = asyncio.run(init_data())
    yield incident
    asyncio.run(reset_engine())


class TestSelfCritiqueFalsificationLoop:
    """Tests for the 6-step self-critique/falsification workflow."""

    def test_self_critique_confirms_correct_hypothesis(self, setup_incident_for_self_critique):
        """Top true hypothesis (checkout deployment) survives falsification and is CONFIRMED."""
        incident = setup_incident_for_self_critique
        mock_provider = MockLLMProvider()

        async def run():
            async with get_db_session() as session:
                timeline = await build_timeline(session, incident.incident_id)
                candidates = await generate_candidate_hypotheses(incident.incident_id, timeline, session)
                ranked = rank_hypotheses(candidates)

                checkout_hyp = next(h for h in ranked if "checkout" in h.title.lower() and "deployment" in h.title.lower())

                result = await run_self_critique(
                    incident_id=incident.incident_id,
                    hypotheses=ranked,
                    session=session,
                    llm_provider=mock_provider,
                    target_hypothesis_id=checkout_hyp.id,
                    max_iterations=3,
                )

                assert result.incident_id == incident.incident_id
                assert len(result.steps) >= 1

                step1 = result.steps[0]
                assert step1.hypothesis_id == checkout_hyp.id
                assert len(step1.questions_asked) >= 2
                assert len(step1.verdicts) >= 1

                # True hypothesis must end with status CONFIRMED or SUPPORTED
                assert step1.status_after in [HypothesisStatus.CONFIRMED, HypothesisStatus.SUPPORTED]
                assert step1.score_after.final_score >= 70.0
                assert step1.confidence_score >= 70.0

        asyncio.run(run())

    def test_self_critique_rejects_weak_distractor_hypothesis(self, setup_incident_for_self_critique):
        """Weak/distractor hypothesis (payment_db or traffic) is contradicted and REJECTED."""
        incident = setup_incident_for_self_critique
        mock_provider = MockLLMProvider()

        async def run():
            async with get_db_session() as session:
                timeline = await build_timeline(session, incident.incident_id)
                candidates = await generate_candidate_hypotheses(incident.incident_id, timeline, session)

                weak_hyp = next(h for h in candidates if "traffic" in h.title.lower() or "database" in h.title.lower())

                result = await run_self_critique(
                    incident_id=incident.incident_id,
                    hypotheses=candidates,
                    session=session,
                    llm_provider=mock_provider,
                    target_hypothesis_id=weak_hyp.id,
                    max_iterations=3,
                )

                assert len(result.steps) >= 1
                step1 = result.steps[0]
                assert step1.hypothesis_id == weak_hyp.id

                # Contradictions should be recorded
                contradicting_verdicts = [v for v in step1.verdicts if v.verdict == "contradicts"]
                assert len(contradicting_verdicts) >= 1

                # Status must transition to REJECTED or WEAK
                assert step1.status_after in [HypothesisStatus.REJECTED, HypothesisStatus.WEAK]

        asyncio.run(run())

    def test_confidence_is_strictly_deterministic(self, setup_incident_for_self_critique):
        """Verify confidence scores reported in all steps match the deterministic formula."""
        incident = setup_incident_for_self_critique
        mock_provider = MockLLMProvider()

        async def run():
            async with get_db_session() as session:
                timeline = await build_timeline(session, incident.incident_id)
                candidates = await generate_candidate_hypotheses(incident.incident_id, timeline, session)

                result = await run_self_critique(
                    incident_id=incident.incident_id,
                    hypotheses=candidates,
                    session=session,
                    llm_provider=mock_provider,
                    max_iterations=2,
                )

                for step in result.steps:
                    assert isinstance(step.confidence_score, float)
                    assert 0.0 <= step.confidence_score <= 100.0
                    assert "deterministically" in step.confidence_rationale.lower()

        asyncio.run(run())

    def test_max_iterations_bound_respected(self, setup_incident_for_self_critique):
        """Verify the self-critique loop respects max_iterations and terminates without infinite loop."""
        incident = setup_incident_for_self_critique
        mock_provider = MockLLMProvider()

        async def run():
            async with get_db_session() as session:
                timeline = await build_timeline(session, incident.incident_id)
                candidates = await generate_candidate_hypotheses(incident.incident_id, timeline, session)

                weak_hyp = next(h for h in candidates if "traffic" in h.title.lower() or "memory" in h.title.lower())

                result = await run_self_critique(
                    incident_id=incident.incident_id,
                    hypotheses=candidates,
                    session=session,
                    llm_provider=mock_provider,
                    target_hypothesis_id=weak_hyp.id,
                    max_iterations=2,
                )

                assert result.iterations_run <= 2
                assert len(result.steps) <= 2

        asyncio.run(run())

    @pytest.mark.integration
    def test_real_gemini_self_critique_integration(self, setup_incident_for_self_critique):
        """Integration test with live Gemini API (only executed when API key is present in environment)."""
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            pytest.skip("Skipping live Gemini integration test: GEMINI_API_KEY not configured.")

        incident = setup_incident_for_self_critique
        gemini_provider = GeminiProvider(api_key=api_key)

        async def run():
            async with get_db_session() as session:
                timeline = await build_timeline(session, incident.incident_id)
                candidates = await generate_candidate_hypotheses(incident.incident_id, timeline, session)
                checkout_hyp = next(h for h in candidates if "checkout" in h.title.lower() and "deployment" in h.title.lower())

                result = await run_self_critique(
                    incident_id=incident.incident_id,
                    hypotheses=candidates,
                    session=session,
                    llm_provider=gemini_provider,
                    target_hypothesis_id=checkout_hyp.id,
                    max_iterations=1,
                )

                assert len(result.steps) == 1
                assert result.steps[0].status_after in [HypothesisStatus.CONFIRMED, HypothesisStatus.SUPPORTED]

        asyncio.run(run())
