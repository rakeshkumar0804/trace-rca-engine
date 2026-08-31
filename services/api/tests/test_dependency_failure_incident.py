from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

# Ensure app package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.generator import (
    generate_dependency_failure_cascade_incident,
    generate_healthy_environment,
    strip_ground_truth_for_investigator,
)
from app.schemas.alerts import AlertSeverity
from app.schemas.events import EventSeverity


@pytest.fixture(scope="module")
def base_environment():
    """Generates a standard 15-minute healthy base environment."""
    start = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
    return generate_healthy_environment(seed=42, start=start, duration_minutes=15)


class TestDependencyFailureIncidentDeterminism:
    """Tests that identical seeds produce identical incident bundles."""

    def test_reproducibility(self, base_environment):
        start = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
        inc1, bundle1 = generate_dependency_failure_cascade_incident(
            seed=123, base_environment=base_environment, incident_start=start
        )
        inc2, bundle2 = generate_dependency_failure_cascade_incident(
            seed=123, base_environment=base_environment, incident_start=start
        )

        assert inc1.incident_id == inc2.incident_id
        assert inc1.ground_truth.root_cause == inc2.ground_truth.root_cause
        assert len(bundle1["logs"]) == len(bundle2["logs"])
        assert len(bundle1["metrics"]) == len(bundle2["metrics"])
        assert len(bundle1["traces"]) == len(bundle2["traces"])
        assert len(bundle1["deployments"]) == len(bundle2["deployments"])


class TestGroundTruthIsolation:
    """Ensures ground truth data never leaks into investigator-facing telemetry."""

    def test_ground_truth_text_never_appears_in_evidence_bundle(self, base_environment):
        start = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
        incident, bundle = generate_dependency_failure_cascade_incident(
            seed=42, base_environment=base_environment, incident_start=start
        )

        gt_text = incident.ground_truth.root_cause
        assert len(gt_text) > 20

        # Check logs
        for log in bundle["logs"]:
            assert gt_text not in log.message
            for k, v in log.metadata.items():
                assert gt_text not in str(v)

        # Check alerts
        for alert in bundle["alerts"]:
            assert gt_text not in alert.description

        # Check commits
        for commit in bundle["commits"]:
            assert gt_text not in commit.diff_summary

        # Check traces
        for trace in bundle["traces"]:
            assert gt_text not in trace.operation

    def test_strip_ground_truth_removes_field(self, base_environment):
        start = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
        incident, _ = generate_dependency_failure_cascade_incident(
            seed=42, base_environment=base_environment, incident_start=start
        )
        investigator_payload = strip_ground_truth_for_investigator(incident)
        assert "ground_truth" not in investigator_payload


class TestCausalObservability:
    """Verifies that key causal signals are present and observable in the telemetry."""

    def test_observable_symptoms_present_in_bundle(self, base_environment):
        start = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
        _, bundle = generate_dependency_failure_cascade_incident(
            seed=42, base_environment=base_environment, incident_start=start
        )

        # 1. payment-service internal degradation logs
        payment_logs = [l for l in bundle["logs"] if l.service == "payment-service" and l.severity in {EventSeverity.ERROR, EventSeverity.WARNING}]
        assert len(payment_logs) >= 2
        assert any("thread pool" in l.message.lower() or "timeout" in l.message.lower() for l in payment_logs)

        # 2. checkout-service timeout logs mentioning payment-service
        checkout_timeout_logs = [l for l in bundle["logs"] if l.service == "checkout-service" and "payment-service" in l.message]
        assert len(checkout_timeout_logs) >= 5

        # 3. payment-service metric spike
        payment_latencies = [m.value for m in bundle["metrics"] if m.service == "payment-service" and m.metric_name == "latency_p95_ms"]
        assert max(payment_latencies) > 3000.0

        # 4. Spans showing timeout duration ~5000ms
        slow_spans = [s for s in bundle["traces"] if s.service == "checkout-service" and s.duration_ms >= 5000.0]
        assert len(slow_spans) >= 5

        # 5. Alert fired on checkout-service
        checkout_alerts = [a for a in bundle["alerts"] if a.service == "checkout-service" and a.severity == AlertSeverity.CRITICAL]
        assert len(checkout_alerts) >= 1

        # 6. Database checkout_db is healthy (negative evidence)
        db_events = [d for d in bundle["database_events"] if d.database == "checkout_db" and d.timestamp >= start]
        assert len(db_events) >= 1
        assert all(d.status.value != "timeout" and d.status.value != "error" for d in db_events)
        assert all(d.connections_active <= 50 for d in db_events)


class TestDistractorCleanliness:
    """Verifies that distractors contain zero benchmark-revealing metadata."""

    def test_distractor_cleanliness_and_no_metadata_labels(self, base_environment):
        start = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
        _, bundle = generate_dependency_failure_cascade_incident(
            seed=42, base_environment=base_environment, incident_start=start
        )

        forbidden = ["distractor", "synthetic", "injected", "benchmark", "fake", "ground_truth"]

        for log in bundle["logs"]:
            for f in forbidden:
                assert f not in log.message.lower()
                for k, v in log.metadata.items():
                    assert f not in k.lower()
                    assert f not in str(v).lower()

        # Distractor deployment exists for inventory-service
        inventory_deps = [d for d in bundle["deployments"] if d.service == "inventory-service"]
        assert len(inventory_deps) >= 1


class TestTimingSanity:
    """Verifies temporal ordering of causal chain."""

    def test_temporal_chain_ordering(self, base_environment):
        start = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
        _, bundle = generate_dependency_failure_cascade_incident(
            seed=42, base_environment=base_environment, incident_start=start
        )

        first_payment_error = min(
            l.timestamp for l in bundle["logs"] if l.service == "payment-service" and l.severity in {EventSeverity.ERROR, EventSeverity.WARNING}
        )
        first_checkout_error = min(
            l.timestamp for l in bundle["logs"] if l.service == "checkout-service" and l.severity == EventSeverity.ERROR
        )
        first_alert = min(a.timestamp for a in bundle["alerts"])

        # payment-service degradation starts BEFORE checkout-service errors
        assert first_payment_error <= first_checkout_error
        # checkout-service errors precede the triggered alert
        assert first_checkout_error <= first_alert


class TestDifferentiatorFromPhase3:
    """Verifies that this incident does NOT contain a checkout-service deployment or commit in the incident window."""

    def test_no_checkout_service_deployment_in_window(self, base_environment):
        from datetime import timedelta
        start = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
        _, bundle = generate_dependency_failure_cascade_incident(
            seed=42, base_environment=base_environment, incident_start=start
        )

        recent_checkout_deps = [
            d for d in bundle["deployments"]
            if d.service == "checkout-service"
            and d.started_at >= start - timedelta(minutes=30)
            and d.started_at <= start + timedelta(minutes=15)
        ]
        recent_checkout_commits = [
            c for c in bundle["commits"]
            if "checkout" in c.repository
            and c.timestamp >= start - timedelta(minutes=30)
            and c.timestamp <= start + timedelta(minutes=15)
        ]

        # Critical differentiator: NO checkout deployment or commit in the incident lookback window
        assert len(recent_checkout_deps) == 0, f"Expected 0 checkout deployments in window, found {len(recent_checkout_deps)}"
        assert len(recent_checkout_commits) == 0, f"Expected 0 checkout commits in window, found {len(recent_checkout_commits)}"
