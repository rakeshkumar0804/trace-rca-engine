from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from uuid import UUID

import pytest
from pydantic import BaseModel

# Ensure app package is importable regardless of working directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.generator import (
    generate_bad_deployment_db_exhaustion_incident,
    generate_healthy_environment,
    strip_ground_truth_for_investigator,
)
from app.schemas.alerts import Alert
from app.schemas.database_events import DatabaseEvent, DatabaseEventStatus
from app.schemas.deployments import Deployment, GitCommit
from app.schemas.events import EventSeverity, LogEntry, MetricPoint, TraceSpan
from app.schemas.incidents import GroundTruth, Incident


class CustomJSONEncoder(json.JSONEncoder):
    """Encodes Pydantic models, datetimes, and UUIDs for strict serialization comparison."""
    def default(self, obj):
        if isinstance(obj, BaseModel):
            return obj.model_dump(mode="json")
        if isinstance(obj, (datetime, UUID)):
            return str(obj)
        return super().default(obj)


@pytest.fixture
def base_healthy_env():
    start = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
    return generate_healthy_environment(seed=42, start=start, duration_minutes=15)


class TestIncidentGeneratorDeterminism:
    """1. Determinism: same seed produces identical incident record and mutated evidence bundle."""

    def test_reproducibility(self, base_healthy_env):
        start = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
        incident_1, bundle_1 = generate_bad_deployment_db_exhaustion_incident(
            seed=100, base_environment=base_healthy_env, incident_start=start, duration_minutes=15
        )
        incident_2, bundle_2 = generate_bad_deployment_db_exhaustion_incident(
            seed=100, base_environment=base_healthy_env, incident_start=start, duration_minutes=15
        )

        json_inc_1 = json.dumps(incident_1.model_dump(mode="json"), sort_keys=True)
        json_inc_2 = json.dumps(incident_2.model_dump(mode="json"), sort_keys=True)
        assert json_inc_1 == json_inc_2

        json_b_1 = json.dumps(bundle_1, cls=CustomJSONEncoder, sort_keys=True)
        json_b_2 = json.dumps(bundle_2, cls=CustomJSONEncoder, sort_keys=True)
        assert json_b_1 == json_b_2


class TestGroundTruthIsolation:
    """2. Ground truth isolation: GroundTruth explanation/labels must NEVER appear in investigator-facing evidence."""

    def test_ground_truth_text_never_appears_in_evidence_bundle(self, base_healthy_env):
        start = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
        incident, bundle = generate_bad_deployment_db_exhaustion_incident(
            seed=42, base_environment=base_healthy_env, incident_start=start, duration_minutes=15
        )

        assert isinstance(incident.ground_truth, GroundTruth)
        root_cause_text = incident.ground_truth.root_cause

        # Key leak phrases that must NEVER appear in logs/commits/alerts/telemetry
        leak_phrases = [
            "N+1",
            "n+1",
            "n_plus_one",
            "root cause",
            "root_cause",
            "ground truth",
            "ground_truth",
            "causal chain",
            "causal_chain",
            "query-in-loop",
            "responsible_commit",
            "distractor",
            "distractor_ref",
        ]

        # Gather all text fields across the entire investigator-facing bundle
        bundle_text_corpus: list[str] = []

        for log in bundle["logs"]:
            bundle_text_corpus.append(log.message)
            for k, v in log.metadata.items():
                bundle_text_corpus.append(f"{k}:{v}")

        for metric in bundle["metrics"]:
            bundle_text_corpus.append(metric.metric_name)
            for k, v in metric.labels.items():
                bundle_text_corpus.append(f"{k}:{v}")

        for trace in bundle["traces"]:
            bundle_text_corpus.append(trace.operation)
            for k, v in trace.attributes.items():
                bundle_text_corpus.append(f"{k}:{v}")

        for commit in bundle["commits"]:
            bundle_text_corpus.append(commit.diff_summary)
            for f in commit.files_changed:
                bundle_text_corpus.append(f)
            for s in commit.symbols_changed:
                bundle_text_corpus.append(s)

        for db_evt in bundle["database_events"]:
            bundle_text_corpus.append(db_evt.query_fingerprint)

        for alert in bundle["alerts"]:
            bundle_text_corpus.append(alert.description)
            bundle_text_corpus.append(alert.alert_type)

        combined_text = " ".join(bundle_text_corpus).lower()

        # 1. Assert exact full root cause string is not present
        assert root_cause_text.lower() not in combined_text, "Full root_cause string was leaked in evidence bundle!"

        # 2. Assert specific leakage phrases are not present
        for phrase in leak_phrases:
            assert phrase.lower() not in combined_text, (
                f"Leaked ground-truth / diagnostic keyword '{phrase}' found in investigator-facing evidence!"
            )


class TestDistractorCleanlinessRegression:
    """3. Regression test: assert that NO evidence object contains any distractor-identifying field, tag, or metadata."""

    def test_no_distractor_identifying_metadata_or_labels(self, base_healthy_env):
        start = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
        _, bundle = generate_bad_deployment_db_exhaustion_incident(
            seed=42, base_environment=base_healthy_env, incident_start=start, duration_minutes=15
        )

        for stream_name, events in bundle.items():
            for obj in events:
                data = obj.model_dump(mode="json") if hasattr(obj, "model_dump") else obj
                serialized = json.dumps(data).lower()
                assert "distractor" not in serialized, (
                    f"Evidence object in stream '{stream_name}' contains distractor-identifying tag: {data}"
                )


class TestCausalObservability:
    """4. Causal observability: all stages of the incident chain are observable in raw telemetry."""

    def test_observable_symptoms_present_in_bundle(self, base_healthy_env):
        start = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
        incident, bundle = generate_bad_deployment_db_exhaustion_incident(
            seed=42, base_environment=base_healthy_env, incident_start=start, duration_minutes=15
        )

        # A. Causal commit and deployment exist for checkout-service
        checkout_deps = [d for d in bundle["deployments"] if d.service == "checkout-service" and d.version == "v2.15.0"]
        assert len(checkout_deps) == 1
        causal_dep = checkout_deps[0]
        assert causal_dep.commit_sha == incident.ground_truth.responsible_commit_sha
        assert causal_dep.deployment_id == incident.ground_truth.responsible_deployment_id

        # B. Timeout DatabaseEvents occur on checkout_db after deployment
        timeout_db_events = [
            d for d in bundle["database_events"]
            if d.database == "checkout_db" and d.status == DatabaseEventStatus.TIMEOUT
        ]
        assert len(timeout_db_events) > 0
        for evt in timeout_db_events:
            assert evt.timestamp >= causal_dep.completed_at
            assert evt.duration_ms >= 5000.0
            assert evt.connections_active >= 90

        # C. Spiking MetricPoints for checkout-service
        spiking_latency = [
            m for m in bundle["metrics"]
            if m.service == "checkout-service" and m.metric_name == "latency_p95_ms" and m.value >= 3000.0
        ]
        assert len(spiking_latency) > 0

        spiking_error_rate = [
            m for m in bundle["metrics"]
            if m.service == "checkout-service" and m.metric_name == "error_rate" and m.value >= 5.0
        ]
        assert len(spiking_error_rate) > 0

        # D. Error logs for checkout-service
        checkout_error_logs = [
            l for l in bundle["logs"]
            if l.service == "checkout-service" and l.severity == EventSeverity.ERROR
        ]
        assert len(checkout_error_logs) > 0

        # E. Critical Alert fired for checkout-service
        alerts = [a for a in bundle["alerts"] if a.service == "checkout-service" and a.alert_type == "High5xxErrorRate"]
        assert len(alerts) == 1
        assert alerts[0].severity.value == "critical"

        # F. Error TraceSpans with HTTP 504 / 500
        error_traces = [t for t in bundle["traces"] if t.status == "error"]
        assert len(error_traces) > 0


class TestDistractors:
    """5. Distractor presence: 3 distractor events exist in bundle and are mapped to distractor_event_ids."""

    def test_distractors_injected_and_referenced(self, base_healthy_env):
        start = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
        incident, bundle = generate_bad_deployment_db_exhaustion_incident(
            seed=42, base_environment=base_healthy_env, incident_start=start, duration_minutes=15
        )

        assert len(incident.distractor_event_ids) == 3

        # 1. Distractor deployment to notification-service
        notif_deps = [d for d in bundle["deployments"] if d.service == "notification-service" and d.version == "v1.19.4"]
        assert len(notif_deps) == 1
        assert notif_deps[0].deployment_id == incident.distractor_event_ids[0]

        # 2. Distractor latency metric on inventory-service exists and is clean
        inv_metrics = [
            m for m in bundle["metrics"]
            if m.service == "inventory-service" and m.metric_name == "latency_p95_ms" and m.value >= 140.0
        ]
        assert len(inv_metrics) == 1
        assert "distractor_ref" not in inv_metrics[0].labels
        assert "distractor" not in json.dumps(inv_metrics[0].labels)

        # 3. Distractor warning log on auth-service exists and is clean
        auth_warning_logs = [
            l for l in bundle["logs"]
            if l.service == "auth-service" and l.severity == EventSeverity.WARNING and "Slow session cache" in l.message
        ]
        assert len(auth_warning_logs) == 1
        assert "distractor_ref" not in auth_warning_logs[0].metadata
        assert "distractor" not in json.dumps(auth_warning_logs[0].metadata)


class TestTimingSanity:
    """6. Timing sanity: strict causal temporal ordering is maintained."""

    def test_temporal_chain_ordering(self, base_healthy_env):
        start = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
        incident, bundle = generate_bad_deployment_db_exhaustion_incident(
            seed=42, base_environment=base_healthy_env, incident_start=start, duration_minutes=15
        )

        # 1. Deployment completion time
        checkout_dep = [d for d in bundle["deployments"] if d.service == "checkout-service" and d.version == "v2.15.0"][0]
        assert checkout_dep.completed_at is not None

        # 2. First Database timeout
        timeout_db_events = [
            d for d in bundle["database_events"]
            if d.database == "checkout_db" and d.status == DatabaseEventStatus.TIMEOUT
        ]
        first_timeout = min(timeout_db_events, key=lambda x: x.timestamp)

        # 3. First latency spike (> 3000ms)
        latency_spikes = [
            m for m in bundle["metrics"]
            if m.service == "checkout-service" and m.metric_name == "latency_p95_ms" and m.value >= 3000.0
        ]
        first_latency_spike = min(latency_spikes, key=lambda x: x.timestamp)

        # 4. Alert fired time
        alert = bundle["alerts"][0]

        # Verify strict causal sequence:
        # deployment completed <= first timeout <= latency spike <= alert fired
        assert checkout_dep.completed_at <= first_timeout.timestamp, "Timeouts started before deployment completed!"
        assert checkout_dep.completed_at <= first_latency_spike.timestamp, "Latency spiked before deployment completed!"
        assert first_timeout.timestamp <= alert.timestamp, "Alert fired before database timeouts occurred!"


class TestStripGroundTruthUtility:
    """7. strip_ground_truth_for_investigator utility verification."""

    def test_strip_ground_truth_removes_field(self, base_healthy_env):
        start = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
        incident, _ = generate_bad_deployment_db_exhaustion_incident(
            seed=42, base_environment=base_healthy_env, incident_start=start, duration_minutes=15
        )

        investigator_view = strip_ground_truth_for_investigator(incident)
        assert isinstance(investigator_view, dict)
        assert "ground_truth" not in investigator_view
        assert "incident_id" in investigator_view
        assert "affected_services" in investigator_view
        assert "expected_symptoms" in investigator_view
        assert "distractor_event_ids" in investigator_view
