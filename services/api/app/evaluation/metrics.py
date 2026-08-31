"""Pure, deterministic evaluation metric functions for TRACE benchmark."""

from collections import defaultdict
from typing import Any
from uuid import UUID

from app.schemas.hypotheses import Hypothesis
from app.schemas.incidents import GroundTruth, Incident


def root_cause_accuracy(
    predicted_text: str,
    ground_truth: GroundTruth,
    incident_type: str,
) -> bool:
    """Evaluates whether a predicted root cause statement/title matches Ground Truth.
    
    Matching Logic (Strict and Documented):
    1. For `bad_deployment_db_exhaustion`:
       - Must identify `checkout-service` (or `checkout_db` / checkout deployment) as the root cause service/component.
       - Must identify the deployment/commit trigger OR database pool / N+1 query leak as the causal mechanism.
       - Must NOT attribute the root cause solely to unrelated services (e.g. notification-service, inventory-service).
    2. For `dependency_failure_cascade`:
       - Must identify `payment-service` as the root cause service / upstream dependency.
       - Must identify downstream dependency failure, thread pool exhaustion, or payment service latency.
       - Must NOT attribute the incident to a checkout-service deployment (which was absent) or inventory distractor deployment.
    """
    text = predicted_text.lower()

    if incident_type == "bad_deployment_db_exhaustion":
        # Positive criteria: service + failure mechanism
        service_match = "checkout-service" in text or "checkout_db" in text or "checkout" in text
        mechanism_match = any(m in text for m in [
            "deployment", "deploy", "release", "commit", "v2.15", "n+1", "n + 1",
            "connection pool", "pool saturation", "query leak", "exhaustion", "database",
        ])
        # Negative criteria: distractors wrongly blamed as primary cause
        distractor_blame = ("notification-service" in text and "checkout" not in text) or ("inventory-service" in text and "checkout" not in text)
        return service_match and mechanism_match and not distractor_blame

    elif incident_type == "dependency_failure_cascade":
        # Positive criteria: payment-service + dependency degradation mechanism
        service_match = "payment-service" in text or "payment" in text
        mechanism_match = any(m in text for m in [
            "dependency", "degradation", "thread pool", "timeout", "latency",
            "downstream", "saturation", "cascade", "cascading", "failure in payment",
        ])
        # Negative criteria: incorrectly claiming checkout deployment was root cause
        distractor_blame = "deployment to checkout-service" in text or "deployment to inventory-service" in text
        return service_match and mechanism_match and not distractor_blame

    elif incident_type == "memory_leak_masked_deployment":
        # Positive criteria: service + memory leak / heap / GC mechanism
        service_match = "checkout-service" in text or "checkout" in text or "host" in text or "process" in text
        mechanism_match = any(m in text for m in [
            "memory leak", "heap", "garbage collection", "gc pause", "gc",
            "memory exhaustion", "memory growth", "progressive memory",
            "heap saturation", "stop-the-world", "unbounded object",
        ])
        # Negative criteria: anchoring on the red-herring deployment as root cause
        deployment_blame = (
            "bad deployment to checkout-service" in text
            or "deployment v2.16" in text
            or "deployment introduced" in text
            or "caused by deployment" in text
            or "deployment of version v2.16" in text
            or "deployment of checkout-service" in text
        )
        return service_match and mechanism_match and not deployment_blame

    # Fallback generic string match on root_cause keywords
    return ground_truth.root_cause.lower()[:30] in text


def top_k_accuracy(
    ranked_hypotheses: list[Hypothesis],
    ground_truth: GroundTruth,
    incident_type: str,
    k: int = 3,
) -> bool:
    """Checks whether the true root cause is present within TRACE's top-k ranked hypotheses."""
    top_candidates = ranked_hypotheses[:k]
    for hyp in top_candidates:
        full_text = f"{hyp.title} {hyp.description}"
        if root_cause_accuracy(full_text, ground_truth, incident_type):
            return True
    return False


def evidence_precision(
    cited_evidence_ids: list[UUID | str],
    relevant_evidence_ids: list[UUID | str] | set[UUID | str],
    distractor_ids: list[UUID | str] | set[UUID | str] | None = None,
) -> float:
    """Calculates precision of cited evidence against the set of true causal evidence IDs.
    
    Formula: |cited_ids ∩ relevant_ids| / |cited_ids|
    Any cited ID present in distractor_ids explicitly counts as false positive.
    """
    if not cited_evidence_ids:
        return 0.0

    cited_set = {str(eid) for eid in cited_evidence_ids}
    relevant_set = {str(eid) for eid in relevant_evidence_ids}
    distractor_set = {str(eid) for eid in (distractor_ids or [])}

    # Remove distractors from relevant if erroneously overlapping
    clean_relevant_set = relevant_set - distractor_set

    true_positives = len(cited_set & clean_relevant_set)
    return round(true_positives / len(cited_set), 4)


def confidence_calibration(
    predictions: list[tuple[float, bool]],
) -> dict[str, dict[str, Any]]:
    """Calculates confidence calibration statistics bucketed across confidence intervals.
    
    Args:
        predictions: List of tuples (confidence_score [0..100], is_correct [bool])
    
    Returns:
        dict of interval buckets with count, correct, actual_accuracy, and mean_confidence.
    """
    buckets = {
        "0-50%": {"min": 0.0, "max": 50.0, "count": 0, "correct": 0, "conf_sum": 0.0},
        "50-70%": {"min": 50.0, "max": 70.0, "count": 0, "correct": 0, "conf_sum": 0.0},
        "70-90%": {"min": 70.0, "max": 90.0, "count": 0, "correct": 0, "conf_sum": 0.0},
        "90-100%": {"min": 90.0, "max": 100.0, "count": 0, "correct": 0, "conf_sum": 0.0},
    }

    for conf, is_correct in predictions:
        for b_name, b_data in buckets.items():
            # Upper bound inclusive for 90-100%
            if b_name == "90-100%":
                in_bucket = b_data["min"] <= conf <= b_data["max"]
            else:
                in_bucket = b_data["min"] <= conf < b_data["max"]

            if in_bucket:
                b_data["count"] += 1
                if is_correct:
                    b_data["correct"] += 1
                b_data["conf_sum"] += conf
                break

    report: dict[str, dict[str, Any]] = {}
    for b_name, b_data in buckets.items():
        cnt = b_data["count"]
        acc = round(b_data["correct"] / cnt, 4) if cnt > 0 else None
        avg_conf = round(b_data["conf_sum"] / cnt, 2) if cnt > 0 else None
        report[b_name] = {
            "total_predictions": cnt,
            "correct_predictions": b_data["correct"],
            "accuracy": acc,
            "average_confidence": avg_conf,
        }

    return report


def hallucination_rate(
    total_attempted_citations: int,
    invalid_citations: int,
) -> float:
    """Calculates the hallucination rate: fraction of evidence citations that were ungrounded."""
    if total_attempted_citations == 0:
        return 0.0
    return round(invalid_citations / total_attempted_citations, 4)
