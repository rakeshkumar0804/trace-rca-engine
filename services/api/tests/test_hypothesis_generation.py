import asyncio
from datetime import datetime, timezone
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
from app.schemas.hypotheses import Hypothesis, HypothesisStatus
from app.timeline.engine import build_timeline


@pytest.fixture(scope="module", autouse=True)
def setup_incident_for_hypotheses():
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


class TestHypothesisCandidateGeneration:
    """Tests for rule-based candidate hypothesis generation against ingested evidence."""

    def test_generate_candidates_produces_diverse_options(self, setup_incident_for_hypotheses):
        incident = setup_incident_for_hypotheses

        async def run():
            async with get_db_session() as session:
                timeline = await build_timeline(session, incident.incident_id)
                candidates = await generate_candidate_hypotheses(incident.incident_id, timeline, session)

                # Must produce at least 3 distinct candidates
                assert len(candidates) >= 3, f"Expected at least 3 candidates, got {len(candidates)}"

                # Verify all are valid Hypothesis instances starting in CANDIDATE status
                for c in candidates:
                    assert isinstance(c, Hypothesis)
                    assert c.incident_id == incident.incident_id
                    assert c.status == HypothesisStatus.CANDIDATE
                    assert c.score.final_score == 0.0  # Unscored initially

                titles_lower = [c.title.lower() for c in candidates]
                descriptions_lower = [c.description.lower() for c in candidates]
                combined_texts = [f"{t} {d}" for t, d in zip(titles_lower, descriptions_lower, strict=False)]

                # Must include a plausible hypothesis naming deployment or checkout-service (the true cause)
                found_deployment_cause = any(
                    "deployment" in text and "checkout" in text for text in combined_texts
                )
                assert found_deployment_cause, (
                    f"Candidate list lacked a deployment/checkout hypothesis: {titles_lower}"
                )

                # Must ALSO include at least one plausible-but-wrong candidate (testing non-cheating heuristic diversity)
                found_alternative_candidate = any(
                    "traffic" in text or "memory" in text or "saturation" in text for text in combined_texts
                )
                assert found_alternative_candidate, (
                    f"Candidate list lacked plausible alternative hypotheses: {titles_lower}"
                )

        asyncio.run(run())

    def test_candidate_generator_strict_ground_truth_isolation(self):
        """Verify candidate_generation.py strictly avoids querying the 'ground_truths' table."""
        src_path = Path(__file__).resolve().parent.parent / "app" / "hypotheses" / "candidate_generation.py"
        lines = src_path.read_text(encoding="utf-8").splitlines()

        # Must have the explicit isolation header comment
        assert any("CRITICAL ISOLATION ENFORCEMENT" in l for l in lines)

        # Code body must NOT reference GroundTruthORM or the ground_truths table
        code_lines = [l for l in lines if not l.strip().startswith("#")]
        code_body = "\n".join(code_lines)
        assert "GroundTruthORM" not in code_body
        assert "ground_truths" not in code_body.lower()
        assert "ground_truth" not in code_body.lower()
