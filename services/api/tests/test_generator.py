from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pytest
from pydantic import BaseModel

# Ensure app package is importable regardless of working directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.generator import (
    SERVICE_CONFIGS,
    SERVICE_TOPOLOGY,
    build_service_definitions,
    generate_healthy_environment,
)
from app.schemas.database_events import DatabaseEvent
from app.schemas.deployments import Deployment, GitCommit
from app.schemas.events import EventSeverity, LogEntry, MetricPoint, TraceSpan


class CustomJSONEncoder(json.JSONEncoder):
    """Encodes Pydantic models, datetimes, and UUIDs for strict serialization comparison."""
    def default(self, obj):
        if isinstance(obj, BaseModel):
            return obj.model_dump(mode="json")
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


class TestGeneratorDeterminism:
    """1. Determinism test: calling generate_healthy_environment(seed=42, ...) twice produces byte-identical output."""

    def test_reproducibility_across_identical_seeds(self):
        start = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)
        env_run_1 = generate_healthy_environment(seed=42, start=start, duration_minutes=15)
        env_run_2 = generate_healthy_environment(seed=42, start=start, duration_minutes=15)

        json_1 = json.dumps(env_run_1, cls=CustomJSONEncoder, sort_keys=True)
        json_2 = json.dumps(env_run_2, cls=CustomJSONEncoder, sort_keys=True)

        assert json_1 == json_2, "Outputs with identical seeds must be strictly byte-identical"

    def test_variance_across_different_seeds(self):
        start = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)
        env_run_1 = generate_healthy_environment(seed=42, start=start, duration_minutes=15)
        env_run_2 = generate_healthy_environment(seed=999, start=start, duration_minutes=15)

        json_1 = json.dumps(env_run_1, cls=CustomJSONEncoder, sort_keys=True)
        json_2 = json.dumps(env_run_2, cls=CustomJSONEncoder, sort_keys=True)

        assert json_1 != json_2, "Outputs with different seeds should vary"


class TestGeneratorSchemaValidity:
    """2. Schema validity test: every generated object validates cleanly against Phase 1 Pydantic models."""

    def test_all_generated_objects_conform_to_schemas(self):
        start = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)
        env = generate_healthy_environment(seed=42, start=start, duration_minutes=10)

        # Validate logs
        for log in env["logs"]:
            assert isinstance(log, LogEntry)
            re_validated = LogEntry.model_validate(log.model_dump())
            assert re_validated == log

        # Validate metrics
        for metric in env["metrics"]:
            assert isinstance(metric, MetricPoint)
            re_validated = MetricPoint.model_validate(metric.model_dump())
            assert re_validated == metric

        # Validate traces
        for trace in env["traces"]:
            assert isinstance(trace, TraceSpan)
            re_validated = TraceSpan.model_validate(trace.model_dump())
            assert re_validated == trace

        # Validate deployments
        for dep in env["deployments"]:
            assert isinstance(dep, Deployment)
            re_validated = Deployment.model_validate(dep.model_dump())
            assert re_validated == dep

        # Validate commits
        for commit in env["commits"]:
            assert isinstance(commit, GitCommit)
            re_validated = GitCommit.model_validate(commit.model_dump())
            assert re_validated == commit

        # Validate database events
        for db_evt in env["database_events"]:
            assert isinstance(db_evt, DatabaseEvent)
            re_validated = DatabaseEvent.model_validate(db_evt.model_dump())
            assert re_validated == db_evt

    def test_service_topology_and_definitions_conform(self):
        definitions = build_service_definitions()
        assert len(definitions) == 7
        for name, defn in definitions.items():
            assert defn.name == name
            for dep in defn.dependencies:
                assert dep.from_service == name
                assert dep.to_service in SERVICE_CONFIGS


class TestGeneratorRealismSanityChecks:
    """3. Realism sanity checks: plausible operational bounds, ratios, and relationship invariants."""

    def test_log_error_rate_stays_within_reasonable_band(self):
        start = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)
        env = generate_healthy_environment(seed=123, start=start, duration_minutes=30)
        logs = env["logs"]
        assert len(logs) > 0

        # Overall error logs in healthy environment should be < 3%
        error_logs = [log for log in logs if log.severity == EventSeverity.ERROR]
        error_ratio = len(error_logs) / len(logs)
        assert error_ratio < 0.03, f"Healthy error log ratio was too high: {error_ratio:.4f}"

        # Majority should be INFO logs (> 90%)
        info_logs = [log for log in logs if log.severity == EventSeverity.INFO]
        info_ratio = len(info_logs) / len(logs)
        assert info_ratio > 0.90, f"Healthy info log ratio was too low: {info_ratio:.4f}"

    def test_database_connections_never_exceed_max(self):
        start = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)
        env = generate_healthy_environment(seed=456, start=start, duration_minutes=20)
        db_events = env["database_events"]
        assert len(db_events) > 0

        for event in db_events:
            assert event.connections_active < event.connections_max, (
                f"Active connections ({event.connections_active}) exceeded max ({event.connections_max})"
            )
            assert event.connections_active > 0

    def test_metrics_p95_greater_than_or_equal_to_p50(self):
        start = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)
        env = generate_healthy_environment(seed=789, start=start, duration_minutes=15)
        metrics = env["metrics"]

        p50_by_ts_service: dict[tuple[datetime, str], float] = {}
        p95_by_ts_service: dict[tuple[datetime, str], float] = {}

        for m in metrics:
            if m.metric_name == "latency_p50_ms":
                p50_by_ts_service[(m.timestamp, m.service)] = m.value
            elif m.metric_name == "latency_p95_ms":
                p95_by_ts_service[(m.timestamp, m.service)] = m.value

        for key, p50_val in p50_by_ts_service.items():
            if key in p95_by_ts_service:
                p95_val = p95_by_ts_service[key]
                assert p95_val >= p50_val, f"p95 ({p95_val}) is less than p50 ({p50_val}) for {key}"

    def test_trace_spans_have_valid_parent_child_references(self):
        start = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)
        env = generate_healthy_environment(seed=101, start=start, duration_minutes=15)
        traces = env["traces"]
        assert len(traces) > 0

        # Group spans by trace_id
        traces_by_id: dict[str, list[TraceSpan]] = {}
        for span in traces:
            traces_by_id.setdefault(span.trace_id, []).append(span)

        for trace_id, span_list in traces_by_id.items():
            span_ids = {s.span_id for s in span_list}
            root_spans = [s for s in span_list if s.parent_span_id is None]
            
            # Exactly one root span per trace tree
            assert len(root_spans) == 1, f"Trace {trace_id} must have exactly one root span"
            assert root_spans[0].service == "api-gateway"

            # All non-root spans must point to a parent span within the same trace
            for span in span_list:
                if span.parent_span_id is not None:
                    assert span.parent_span_id in span_ids, (
                        f"Orphaned parent_span_id {span.parent_span_id} in trace {trace_id}"
                    )

    def test_commit_and_deployment_linkage(self):
        start = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)
        env = generate_healthy_environment(seed=202, start=start, duration_minutes=15)
        commits = env["commits"]
        deployments = env["deployments"]

        commit_shas = {c.commit_sha for c in commits}
        for dep in deployments:
            assert dep.commit_sha in commit_shas, f"Deployment commit_sha {dep.commit_sha} not found in commits"
            assert dep.status.value == "success"
            if dep.completed_at and dep.started_at:
                assert dep.completed_at > dep.started_at


class TestGeneratorVolume:
    """4. Volume test: 15-minute window produces a plausible, non-trivial volume of events."""

    def test_fifteen_minute_window_volume(self):
        start = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)
        env = generate_healthy_environment(seed=303, start=start, duration_minutes=15)

        # 15 minutes with ~10s ticks = ~90 ticks
        # 7 services * ~90 ticks * ~2 logs/tick = ~1,000 - 1,500 logs
        assert 500 <= len(env["logs"]) <= 3000, f"Expected 500-3000 logs, got {len(env['logs'])}"

        # 7 services * ~90 ticks * ~6-8 metrics/tick = ~3,500 - 6,000 metrics
        assert 2000 <= len(env["metrics"]) <= 8000, f"Expected 2000-8000 metrics, got {len(env['metrics'])}"

        # Sampled traces (~30 traces with 3-7 spans each = ~100-250 spans)
        assert 50 <= len(env["traces"]) <= 500, f"Expected 50-500 trace spans, got {len(env['traces'])}"

        # 3 deployments and 3 commits
        assert len(env["deployments"]) == 3
        assert len(env["commits"]) == 3

        # DB events for 3 DB-owning services * ~90 ticks * 1-2 events = ~200-600 events
        assert 100 <= len(env["database_events"]) <= 1000, (
            f"Expected 100-1000 DB events, got {len(env['database_events'])}"
        )
