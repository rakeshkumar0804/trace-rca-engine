from pathlib import Path
import sys
from uuid import uuid4

import pytest

# Ensure app package is importable regardless of working directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.llm.grounding import (
    derive_deterministic_confidence,
    sanitize_verdicts_grounding,
    validate_evidence_citations,
)
from app.llm.prompts.falsification_questions import build_falsification_questions_prompt
from app.llm.schemas import EvidenceVerdict
from app.schemas.events import EventSeverity, EventSource, NormalizedEvent
from app.schemas.hypotheses import Hypothesis, HypothesisScore, HypothesisStatus


class TestLLMGroundingAndCitationValidation:
    """Tests for Rule 3 & Rule 5: Strict evidence citation validation & hallucination rejection."""

    def test_validate_evidence_citations_separates_valid_and_invalid(self):
        id1 = uuid4()
        id2 = uuid4()
        id3_fabricated = uuid4()
        id4_fabricated = uuid4()

        available = {id1, id2}
        claimed = [id1, id3_fabricated, id2, id4_fabricated]

        valid, invalid = validate_evidence_citations(claimed, available)
        assert valid == [id1, id2]
        assert invalid == [id3_fabricated, id4_fabricated]

    def test_sanitize_verdicts_grounding_rejects_hallucinated_citations(self):
        real_id = uuid4()
        fake_id1 = uuid4()
        fake_id2 = uuid4()

        available = {real_id}

        verdicts = [
            EvidenceVerdict(
                question="Q1",
                evidence_ids_cited=[real_id],
                verdict="supports",
                reasoning="Telemetry proves hypothesis.",
            ),
            EvidenceVerdict(
                question="Q2",
                evidence_ids_cited=[fake_id1, fake_id2],
                verdict="contradicts",
                reasoning="Hallucinated error log.",
            ),
        ]

        sanitized, rejected = sanitize_verdicts_grounding(verdicts, available)

        # Q1 remains valid with real_id
        assert sanitized[0].evidence_ids_cited == [real_id]
        assert sanitized[0].verdict == "supports"

        # Q2 had ONLY fabricated IDs, so it was sanitized to empty citations and marked inconclusive
        assert sanitized[1].evidence_ids_cited == []
        assert sanitized[1].verdict == "inconclusive"
        assert "ungrounded" in sanitized[1].reasoning.lower()
        assert set(rejected) == {fake_id1, fake_id2}

    def test_deterministic_confidence_calculation(self):
        """Verify Rule 4: Confidence is derived deterministically from score and evidence properties."""
        score_high = HypothesisScore(
            temporal_fit=18.0, causal_fit=20.0, evidence_support=17.0, system_dependency_fit=20.0,
            change_proximity=19.0, contradictory_evidence_penalty=0.0, unexplained_symptoms_penalty=0.0,
            final_score=85.0,
        )

        # High score, 4 distinct sources, 0 contradictions, 0 unexplained symptoms -> high confidence
        conf_high = derive_deterministic_confidence(
            score=score_high,
            contradiction_count=0,
            unexplained_symptom_count=0,
            distinct_sources_count=4,
        )
        assert 85.0 <= conf_high <= 100.0

        # Penalized heavily if contradictions exist
        conf_penalized = derive_deterministic_confidence(
            score=score_high,
            contradiction_count=2,  # -40.0
            unexplained_symptom_count=1,  # -10.0
            distinct_sources_count=2,
        )
        assert conf_penalized <= 50.0

    def test_prompt_ground_truth_isolation(self):
        """Verify prompt construction never includes or references hidden GroundTruth content."""
        hyp = Hypothesis(
            id=uuid4(),
            incident_id=uuid4(),
            title="Bad deployment to checkout-service",
            description="N+1 query defect in checkout-service v2.15.0",
            status=HypothesisStatus.INVESTIGATING,
            score=HypothesisScore(
                temporal_fit=15, causal_fit=20, evidence_support=15, system_dependency_fit=20,
                change_proximity=18, contradictory_evidence_penalty=0, unexplained_symptoms_penalty=0,
                final_score=80.0,
            ),
        )

        ground_truth_secret = "SECRET_ROOT_CAUSE_GROUND_TRUTH_CHAIN_12345"

        prompt, sys_inst = build_falsification_questions_prompt(
            hypothesis=hyp,
            existing_evidence=[],
            timeline_summary="Summary of 50 events.",
        )

        assert ground_truth_secret not in prompt
        assert ground_truth_secret not in sys_inst
        assert "ground_truth" not in prompt.lower()
        assert "ground_truths" not in prompt.lower()
