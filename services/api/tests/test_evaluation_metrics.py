from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.evaluation.metrics import (
    confidence_calibration,
    evidence_precision,
    hallucination_rate,
    root_cause_accuracy,
    top_k_accuracy,
)
from app.schemas.hypotheses import Hypothesis, HypothesisScore, HypothesisStatus
from app.schemas.incidents import CausalChainLink, GroundTruth


class TestEvaluationMetricsPureFunctions:
    """Tests the pure metric functions without any database or LLM dependencies."""

    def test_root_cause_accuracy_bad_deployment_match(self):
        gt = GroundTruth(
            root_cause="Deployment of checkout-service version v2.15.0 caused N+1 database queries",
            causal_chain=[],
        )
        assert root_cause_accuracy(
            "Bad deployment to checkout-service (v2.15.0)",
            gt,
            "bad_deployment_db_exhaustion",
        )
        assert root_cause_accuracy(
            "Database connection pool saturation on checkout_db caused by loop query leak",
            gt,
            "bad_deployment_db_exhaustion",
        )
        # Distractor should not match
        assert not root_cause_accuracy(
            "Bad deployment to notification-service (v1.19.4)",
            gt,
            "bad_deployment_db_exhaustion",
        )

    def test_root_cause_accuracy_dependency_failure_match(self):
        gt = GroundTruth(
            root_cause="Internal thread pool exhaustion in payment-service cascading to checkout-service",
            causal_chain=[],
        )
        assert root_cause_accuracy(
            "Downstream dependency failure in payment-service",
            gt,
            "dependency_failure_cascade",
        )
        assert root_cause_accuracy(
            "Service degradation and thread pool timeouts in payment-service",
            gt,
            "dependency_failure_cascade",
        )
        # Distractor deployment or other service should not match
        assert not root_cause_accuracy(
            "Bad deployment to checkout-service (v2.15.0)",
            gt,
            "dependency_failure_cascade",
        )
        assert not root_cause_accuracy(
            "Bad deployment to inventory-service (v1.8.2)",
            gt,
            "dependency_failure_cascade",
        )

    def test_root_cause_accuracy_memory_leak_match(self):
        gt = GroundTruth(
            root_cause="Progressive heap memory leak and unbounded object accumulation in checkout-service",
            causal_chain=[],
        )
        # Real memory leak statements should match
        assert root_cause_accuracy(
            "Memory leak and garbage collection pause in checkout-service",
            gt,
            "memory_leak_masked_deployment",
        )
        assert root_cause_accuracy(
            "Progressive heap exhaustion and major GC pause stalls on checkout-service host",
            gt,
            "memory_leak_masked_deployment",
        )
        # Blaming the red-herring deployment must NOT match
        assert not root_cause_accuracy(
            "Bad deployment to checkout-service (v2.16.0)",
            gt,
            "memory_leak_masked_deployment",
        )
        assert not root_cause_accuracy(
            "Deployment of checkout-service version v2.16.0 introduced caching error",
            gt,
            "memory_leak_masked_deployment",
        )

    def test_top_k_accuracy_membership(self):
        gt = GroundTruth(
            root_cause="Deployment of checkout-service version v2.15.0 caused N+1 database queries",
            causal_chain=[],
        )
        score = HypothesisScore(
            temporal_fit=1.0,
            causal_fit=1.0,
            evidence_support=1.0,
            system_dependency_fit=1.0,
            change_proximity=1.0,
            contradictory_evidence_penalty=0.0,
            unexplained_symptoms_penalty=0.0,
            final_score=80.0,
        )
        inc_id = uuid4()
        now = datetime.now(timezone.utc)
        h1 = Hypothesis(
            id=uuid4(),
            incident_id=inc_id,
            title="Bad deployment to notification-service",
            description="notification failure",
            status=HypothesisStatus.CANDIDATE,
            score=score,
            created_at=now,
        )
        h2 = Hypothesis(
            id=uuid4(),
            incident_id=inc_id,
            title="Bad deployment to checkout-service (v2.15.0)",
            description="checkout deployment leak",
            status=HypothesisStatus.CANDIDATE,
            score=score,
            created_at=now,
        )
        h3 = Hypothesis(
            id=uuid4(),
            incident_id=inc_id,
            title="Host memory exhaustion",
            description="memory leak",
            status=HypothesisStatus.CANDIDATE,
            score=score,
            created_at=now,
        )

        assert top_k_accuracy([h1, h2, h3], gt, "bad_deployment_db_exhaustion", k=2)
        assert top_k_accuracy([h1, h2, h3], gt, "bad_deployment_db_exhaustion", k=3)
        assert not top_k_accuracy([h1, h3], gt, "bad_deployment_db_exhaustion", k=2)

    def test_evidence_precision_calculation(self):
        e1, e2, e3, e4 = uuid4(), uuid4(), uuid4(), uuid4()
        relevant = {e1, e2}
        distractors = {e4}

        # 2 cited, 2 relevant -> 100%
        assert evidence_precision([e1, e2], relevant, distractors) == 1.0

        # 4 cited: 2 relevant, 1 clean irrelevant, 1 distractor -> 50%
        assert evidence_precision([e1, e2, e3, e4], relevant, distractors) == 0.5

        # Empty cited -> 0.0
        assert evidence_precision([], relevant, distractors) == 0.0

    def test_confidence_calibration_binning(self):
        predictions = [
            (95.0, True),
            (92.0, True),
            (85.0, True),
            (75.0, False),
            (60.0, True),
            (40.0, False),
        ]
        calib = confidence_calibration(predictions)

        assert calib["90-100%"]["total_predictions"] == 2
        assert calib["90-100%"]["correct_predictions"] == 2
        assert calib["90-100%"]["accuracy"] == 1.0

        assert calib["70-90%"]["total_predictions"] == 2
        assert calib["70-90%"]["correct_predictions"] == 1
        assert calib["70-90%"]["accuracy"] == 0.5

        assert calib["50-70%"]["total_predictions"] == 1
        assert calib["50-70%"]["correct_predictions"] == 1
        assert calib["50-70%"]["accuracy"] == 1.0

        assert calib["0-50%"]["total_predictions"] == 1
        assert calib["0-50%"]["correct_predictions"] == 0
        assert calib["0-50%"]["accuracy"] == 0.0

    def test_hallucination_rate_calculation(self):
        assert hallucination_rate(100, 5) == 0.05
        assert hallucination_rate(50, 0) == 0.0
        assert hallucination_rate(0, 0) == 0.0
