from datetime import datetime, timezone
from pathlib import Path
import sys
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

# Ensure app package is importable regardless of working directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.schemas.alerts import Alert, AlertSeverity
from app.schemas.database_events import DatabaseEvent, DatabaseEventStatus
from app.schemas.deployments import Deployment, DeploymentStatus, GitCommit
from app.schemas.events import (
    EventSeverity,
    EventSource,
    LogEntry,
    MetricPoint,
    NormalizedEvent,
    TraceSpan,
)
from app.schemas.hypotheses import (
    EvidenceRef,
    Hypothesis,
    HypothesisScore,
    HypothesisStatus,
)
from app.schemas.incidents import (
    CausalChainLink,
    GroundTruth,
    Incident,
    IncidentDifficulty,
    IncidentSeverity,
)
from app.schemas.services import ServiceDefinition, ServiceDependency


# ==============================================================================
# 1. Events Schemas Tests (NormalizedEvent, LogEntry, MetricPoint, TraceSpan)
# ==============================================================================

class TestNormalizedEvent:
    def test_valid_instance(self):
        event_id = uuid4()
        now = datetime.now(timezone.utc)
        event = NormalizedEvent(
            id=event_id,
            timestamp=now,
            source=EventSource.LOG,
            entity="checkout-service",
            event_type="http_5xx",
            service="checkout-service",
            severity=EventSeverity.ERROR,
            attributes={"status_code": 500, "endpoint": "/checkout", "retried": True, "latency_sec": 1.25},
            relationships=["evt-123", "evt-456"],
        )
        assert event.id == event_id
        assert event.source == EventSource.LOG
        assert event.entity == "checkout-service"
        assert event.attributes["status_code"] == 500
        assert event.relationships == ["evt-123", "evt-456"]

    def test_missing_required_field(self):
        with pytest.raises(ValidationError) as exc_info:
            NormalizedEvent(
                # Missing 'id', 'timestamp', 'source', 'entity', 'event_type', 'attributes'
                service="checkout-service"
            )
        errors = exc_info.value.errors()
        missing_fields = {e["loc"][0] for e in errors if e["type"] == "missing"}
        assert {"id", "timestamp", "source", "entity", "event_type", "attributes"}.issubset(missing_fields)

    def test_invalid_type_field(self):
        with pytest.raises(ValidationError):
            NormalizedEvent(
                id="not-a-valid-uuid",
                timestamp="invalid-timestamp",
                source="invalid_source",
                entity="checkout-service",
                event_type="http_5xx",
                attributes={"key": [1, 2, 3]},  # list is not str | int | float | bool
            )


class TestLogEntry:
    def test_valid_instance(self):
        now = datetime.now(timezone.utc)
        log = LogEntry(
            timestamp=now,
            service="payment-service",
            severity=EventSeverity.ERROR,
            message="Failed to process transaction: payment gateway timeout",
            trace_id="trace-abc-123",
            request_id="req-987-xyz",
            metadata={"user_id": "usr-5541", "gateway": "stripe"},
        )
        assert log.service == "payment-service"
        assert log.severity == EventSeverity.ERROR
        assert log.metadata["gateway"] == "stripe"

    def test_missing_required_field(self):
        with pytest.raises(ValidationError) as exc_info:
            LogEntry(
                timestamp=datetime.now(timezone.utc),
                # missing 'service', 'severity', 'message'
            )
        missing_fields = {e["loc"][0] for e in exc_info.value.errors() if e["type"] == "missing"}
        assert {"service", "severity", "message"}.issubset(missing_fields)

    def test_invalid_type_field(self):
        with pytest.raises(ValidationError):
            LogEntry(
                timestamp="not-a-datetime",
                service=12345,  # wrong type if strictly non-string or severity is wrong
                severity="CRITICAL_BUT_INVALID_ENUM",
                message="Error occurred",
            )


class TestMetricPoint:
    def test_valid_instance(self):
        now = datetime.now(timezone.utc)
        metric = MetricPoint(
            timestamp=now,
            service="checkout-service",
            metric_name="http_requests_latency_p99",
            value=845.2,
            unit="ms",
            labels={"route": "/checkout/complete", "status_class": "5xx"},
        )
        assert metric.metric_name == "http_requests_latency_p99"
        assert metric.value == 845.2
        assert metric.unit == "ms"

    def test_missing_required_field(self):
        with pytest.raises(ValidationError) as exc_info:
            MetricPoint(
                timestamp=datetime.now(timezone.utc),
                # missing 'service', 'metric_name', 'value', 'unit'
            )
        missing_fields = {e["loc"][0] for e in exc_info.value.errors() if e["type"] == "missing"}
        assert {"service", "metric_name", "value", "unit"}.issubset(missing_fields)

    def test_invalid_type_field(self):
        with pytest.raises(ValidationError):
            MetricPoint(
                timestamp="invalid-date",
                service="checkout-service",
                metric_name="cpu_usage",
                value="not-a-number",
                unit="percentage",
            )


class TestTraceSpan:
    def test_valid_instance(self):
        now = datetime.now(timezone.utc)
        span = TraceSpan(
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            span_id="00f067aa0ba902b7",
            parent_span_id="5fb397be34d23b0f",
            service="order-service",
            operation="process_order",
            start_time=now,
            duration_ms=235.4,
            status="ok",
            attributes={"http.method": "POST", "http.status_code": "200"},
        )
        assert span.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
        assert span.status == "ok"
        assert span.duration_ms == 235.4

    def test_missing_required_field(self):
        with pytest.raises(ValidationError) as exc_info:
            TraceSpan(
                trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
                # missing span_id, service, operation, start_time, duration_ms, status
            )
        missing_fields = {e["loc"][0] for e in exc_info.value.errors() if e["type"] == "missing"}
        assert {"span_id", "service", "operation", "start_time", "duration_ms", "status"}.issubset(missing_fields)

    def test_invalid_type_field(self):
        with pytest.raises(ValidationError):
            TraceSpan(
                trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
                span_id="00f067aa0ba902b7",
                service="order-service",
                operation="process_order",
                start_time="not-a-datetime",
                duration_ms="invalid-duration",
                status="unknown_status",  # Literal["ok", "error"]
            )


# ==============================================================================
# 2. Deployments Schemas Tests (Deployment, GitCommit)
# ==============================================================================

class TestDeployment:
    def test_valid_instance(self):
        dep_id = uuid4()
        now = datetime.now(timezone.utc)
        deployment = Deployment(
            deployment_id=dep_id,
            service="checkout-service",
            version="v2.14.0",
            commit_sha="a1b2c3d4e5f67890123456789abcdef012345678",
            started_at=now,
            completed_at=now,
            environment="production",
            status=DeploymentStatus.SUCCESS,
        )
        assert deployment.deployment_id == dep_id
        assert deployment.status == DeploymentStatus.SUCCESS
        assert deployment.version == "v2.14.0"

    def test_missing_required_field(self):
        with pytest.raises(ValidationError) as exc_info:
            Deployment(
                service="checkout-service",
                # missing deployment_id, version, commit_sha, started_at, environment, status
            )
        missing_fields = {e["loc"][0] for e in exc_info.value.errors() if e["type"] == "missing"}
        assert {"deployment_id", "version", "commit_sha", "started_at", "environment", "status"}.issubset(missing_fields)

    def test_invalid_type_field(self):
        with pytest.raises(ValidationError):
            Deployment(
                deployment_id="invalid-uuid",
                service="checkout-service",
                version="v2.14.0",
                commit_sha="a1b2c3",
                started_at="invalid-date",
                environment="production",
                status="not_a_valid_status",
            )


class TestGitCommit:
    def test_valid_instance(self):
        now = datetime.now(timezone.utc)
        commit = GitCommit(
            commit_sha="e8f49b1a0d2c",
            author="engineer@company.internal",
            timestamp=now,
            repository="org/checkout-service",
            files_changed=["src/api/checkout.py", "src/db/pool.py"],
            diff_summary="Optimize DB connection pooling and query timeouts",
            symbols_changed=["checkout.process_payment", "pool.get_connection"],
        )
        assert commit.commit_sha == "e8f49b1a0d2c"
        assert len(commit.files_changed) == 2
        assert len(commit.symbols_changed) == 2

    def test_missing_required_field(self):
        with pytest.raises(ValidationError) as exc_info:
            GitCommit(
                author="engineer@company.internal",
                # missing commit_sha, timestamp, repository, files_changed, diff_summary
            )
        missing_fields = {e["loc"][0] for e in exc_info.value.errors() if e["type"] == "missing"}
        assert {"commit_sha", "timestamp", "repository", "files_changed", "diff_summary"}.issubset(missing_fields)

    def test_invalid_type_field(self):
        with pytest.raises(ValidationError):
            GitCommit(
                commit_sha="e8f49b1a0d2c",
                author="engineer@company.internal",
                timestamp="invalid-datetime",
                repository="org/checkout-service",
                files_changed="should-be-a-list",
                diff_summary="summary",
            )


# ==============================================================================
# 3. Database Events Schemas Tests (DatabaseEvent)
# ==============================================================================

class TestDatabaseEvent:
    def test_valid_instance(self):
        now = datetime.now(timezone.utc)
        db_evt = DatabaseEvent(
            timestamp=now,
            database="checkout_db_primary",
            query_fingerprint="SELECT * FROM orders WHERE user_id = ? FOR UPDATE",
            duration_ms=4520.5,
            connections_active=98,
            connections_max=100,
            locks_held=14,
            rows_affected=1,
            status=DatabaseEventStatus.SLOW,
        )
        assert db_evt.database == "checkout_db_primary"
        assert db_evt.status == DatabaseEventStatus.SLOW
        assert db_evt.connections_active == 98

    def test_missing_required_field(self):
        with pytest.raises(ValidationError) as exc_info:
            DatabaseEvent(
                database="checkout_db_primary",
                # missing timestamp, query_fingerprint, duration_ms, connections_active, connections_max, locks_held, rows_affected, status
            )
        missing_fields = {e["loc"][0] for e in exc_info.value.errors() if e["type"] == "missing"}
        assert {"timestamp", "query_fingerprint", "duration_ms", "connections_active", "connections_max", "locks_held", "rows_affected", "status"}.issubset(missing_fields)

    def test_invalid_type_field(self):
        with pytest.raises(ValidationError):
            DatabaseEvent(
                timestamp="invalid-time",
                database="checkout_db_primary",
                query_fingerprint="SELECT 1",
                duration_ms="not-a-float",
                connections_active="many",
                connections_max=100,
                locks_held=0,
                rows_affected=0,
                status="database_down",  # invalid enum
            )


# ==============================================================================
# 4. Alerts Schemas Tests (Alert)
# ==============================================================================

class TestAlert:
    def test_valid_instance(self):
        now = datetime.now(timezone.utc)
        alert = Alert(
            timestamp=now,
            alert_type="High5xxErrorRate",
            service="checkout-service",
            severity=AlertSeverity.CRITICAL,
            description="5xx error rate exceeded 5% threshold over 5m window",
        )
        assert alert.service == "checkout-service"
        assert alert.severity == AlertSeverity.CRITICAL

    def test_missing_required_field(self):
        with pytest.raises(ValidationError) as exc_info:
            Alert(
                service="checkout-service",
                # missing timestamp, alert_type, severity, description
            )
        missing_fields = {e["loc"][0] for e in exc_info.value.errors() if e["type"] == "missing"}
        assert {"timestamp", "alert_type", "severity", "description"}.issubset(missing_fields)

    def test_invalid_type_field(self):
        with pytest.raises(ValidationError):
            Alert(
                timestamp="not-a-date",
                alert_type="HighLatency",
                service="checkout-service",
                severity="SUPER_CRITICAL",  # invalid severity enum
                description="Latency high",
            )


# ==============================================================================
# 5. Services Schemas Tests (ServiceDependency, ServiceDefinition)
# ==============================================================================

class TestServiceDependency:
    def test_valid_instance(self):
        dep = ServiceDependency(
            from_service="checkout-service",
            to_service="payment-service",
            protocol="grpc",
            request_type="sync_rpc",
            expected_latency_ms=45.0,
            dependency_strength="hard",
        )
        assert dep.from_service == "checkout-service"
        assert dep.to_service == "payment-service"
        assert dep.dependency_strength == "hard"

    def test_missing_required_field(self):
        with pytest.raises(ValidationError) as exc_info:
            ServiceDependency(
                from_service="checkout-service"
                # missing to_service, protocol, request_type, expected_latency_ms, dependency_strength
            )
        missing_fields = {e["loc"][0] for e in exc_info.value.errors() if e["type"] == "missing"}
        assert {"to_service", "protocol", "request_type", "expected_latency_ms", "dependency_strength"}.issubset(missing_fields)

    def test_invalid_type_field(self):
        with pytest.raises(ValidationError):
            ServiceDependency(
                from_service="checkout-service",
                to_service="payment-service",
                protocol="grpc",
                request_type="sync_rpc",
                expected_latency_ms="fast",  # not a float
                dependency_strength="optional",  # not Literal["hard", "soft"]
            )


class TestServiceDefinition:
    def test_valid_instance(self):
        dep = ServiceDependency(
            from_service="checkout-service",
            to_service="inventory-service",
            protocol="http",
            request_type="rest",
            expected_latency_ms=30.0,
            dependency_strength="soft",
        )
        service = ServiceDefinition(
            name="checkout-service",
            description="Core e-commerce checkout flow handler",
            owns_database=True,
            dependencies=[dep],
        )
        assert service.name == "checkout-service"
        assert service.owns_database is True
        assert len(service.dependencies) == 1

    def test_missing_required_field(self):
        with pytest.raises(ValidationError) as exc_info:
            ServiceDefinition(
                # missing name, description, owns_database
                dependencies=[]
            )
        missing_fields = {e["loc"][0] for e in exc_info.value.errors() if e["type"] == "missing"}
        assert {"name", "description", "owns_database"}.issubset(missing_fields)

    def test_invalid_type_field(self):
        with pytest.raises(ValidationError):
            ServiceDefinition(
                name="checkout-service",
                description="Core service",
                owns_database="yes",  # boolean required
                dependencies="not-a-list",
            )


# ==============================================================================
# 6. Incidents Schemas Tests (CausalChainLink, GroundTruth, Incident)
# ==============================================================================

class TestCausalChainLink:
    def test_valid_instance(self):
        link = CausalChainLink(
            from_node="commit_e8f49b",
            to_node="connection_pool_exhaustion",
            relationship="introduced",
            explanation="Unbounded connection timeout led to connection pool leak under load",
        )
        assert link.from_node == "commit_e8f49b"
        assert link.relationship == "introduced"

    def test_missing_required_field(self):
        with pytest.raises(ValidationError) as exc_info:
            CausalChainLink(
                from_node="commit_e8f49b"
                # missing to_node, relationship, explanation
            )
        missing_fields = {e["loc"][0] for e in exc_info.value.errors() if e["type"] == "missing"}
        assert {"to_node", "relationship", "explanation"}.issubset(missing_fields)

    def test_invalid_type_field(self):
        with pytest.raises(ValidationError):
            CausalChainLink(
                from_node=["node-1"],  # invalid type, string expected
                to_node="node-2",
                relationship="caused",
                explanation="explanation text",
            )


class TestGroundTruth:
    def test_valid_instance(self):
        dep_id = uuid4()
        link = CausalChainLink(
            from_node="deployment_v2",
            to_node="db_deadlock",
            relationship="caused",
            explanation="Migration missing index caused full table lock",
        )
        gt = GroundTruth(
            root_cause="Missing database index on order_items table in deployment v2.14.0",
            causal_chain=[link],
            responsible_commit_sha="a1b2c3d4e5f6",
            responsible_deployment_id=dep_id,
        )
        assert gt.root_cause.startswith("Missing database index")
        assert gt.responsible_deployment_id == dep_id
        assert len(gt.causal_chain) == 1

    def test_missing_required_field(self):
        with pytest.raises(ValidationError) as exc_info:
            GroundTruth(
                responsible_commit_sha="a1b2c3"
                # missing root_cause, causal_chain
            )
        missing_fields = {e["loc"][0] for e in exc_info.value.errors() if e["type"] == "missing"}
        assert {"root_cause", "causal_chain"}.issubset(missing_fields)

    def test_invalid_type_field(self):
        with pytest.raises(ValidationError):
            GroundTruth(
                root_cause="Database deadlock",
                causal_chain="not-a-list-of-links",
                responsible_deployment_id="invalid-uuid",
            )


class TestIncident:
    def test_valid_instance(self):
        inc_id = uuid4()
        now = datetime.now(timezone.utc)
        link = CausalChainLink(
            from_node="commit_xyz",
            to_node="pool_starvation",
            relationship="caused",
            explanation="Connection pool size reduced from 50 to 5",
        )
        gt = GroundTruth(
            root_cause="Connection pool exhaustion in checkout service due to bad config commit",
            causal_chain=[link],
            responsible_commit_sha="c0ffee1234",
            responsible_deployment_id=uuid4(),
        )
        distractor_id = uuid4()
        incident = Incident(
            incident_id=inc_id,
            incident_type="Database Connection Saturation",
            start_time=now,
            end_time=None,
            affected_services=["checkout-service", "order-service"],
            expected_symptoms=["HTTP 504 Gateway Timeout", "Database connection pool exhausted"],
            distractor_event_ids=[distractor_id],
            difficulty=IncidentDifficulty.MEDIUM,
            severity=IncidentSeverity.SEV1,
            ground_truth=gt,
        )
        assert incident.incident_id == inc_id
        assert incident.difficulty == IncidentDifficulty.MEDIUM
        assert incident.severity == IncidentSeverity.SEV1
        assert len(incident.affected_services) == 2
        assert incident.distractor_event_ids == [distractor_id]

    def test_missing_required_field(self):
        with pytest.raises(ValidationError) as exc_info:
            Incident(
                incident_type="Outage"
                # missing incident_id, start_time, affected_services, expected_symptoms, difficulty, severity, ground_truth
            )
        missing_fields = {e["loc"][0] for e in exc_info.value.errors() if e["type"] == "missing"}
        assert {"incident_id", "start_time", "affected_services", "expected_symptoms", "difficulty", "severity", "ground_truth"}.issubset(missing_fields)

    def test_invalid_type_field(self):
        with pytest.raises(ValidationError):
            Incident(
                incident_id="not-a-uuid",
                incident_type="Outage",
                start_time="not-a-date",
                affected_services="checkout-service",  # expected list
                expected_symptoms="500 errors",        # expected list
                difficulty="impossible",               # invalid enum
                severity="SEV0",                       # invalid enum
                ground_truth={"root_cause": 123},      # invalid ground truth object
            )


# ==============================================================================
# Special Enforcement Test: Incident.ground_truth existence
# ==============================================================================

# This field must NEVER be exposed via the investigator-facing API in later phases — see Phase 4+ for enforcement.
def test_incident_ground_truth_presence_and_isolation():
    """Verify that Incident.ground_truth exists, is strongly typed, and holds the benchmark ground truth.

    NOTE: This field must NEVER be exposed via the investigator-facing API in later phases — see Phase 4+ for enforcement.
    """
    inc_id = uuid4()
    dep_id = uuid4()
    now = datetime.now(timezone.utc)
    gt = GroundTruth(
        root_cause="Redis eviction policy misconfigured to noeviction under high key pressure",
        causal_chain=[
            CausalChainLink(
                from_node="config_deployment",
                to_node="redis_oom_error",
                relationship="caused",
                explanation="Redis memory limit hit without key eviction enabled",
            )
        ],
        responsible_commit_sha="9f8e7d6c5b",
        responsible_deployment_id=dep_id,
    )
    incident = Incident(
        incident_id=inc_id,
        incident_type="Cache Memory Exhaustion",
        start_time=now,
        affected_services=["session-service"],
        expected_symptoms=["Session lookup failures", "HTTP 500 on login"],
        difficulty=IncidentDifficulty.EASY,
        severity=IncidentSeverity.SEV2,
        ground_truth=gt,
    )

    # Confirm ground_truth is present on the model instance and contains expected benchmark data
    assert hasattr(incident, "ground_truth")
    assert incident.ground_truth.root_cause == "Redis eviction policy misconfigured to noeviction under high key pressure"
    assert incident.ground_truth.responsible_deployment_id == dep_id
    assert len(incident.ground_truth.causal_chain) == 1
    assert incident.ground_truth.causal_chain[0].relationship == "caused"


# ==============================================================================
# 7. Hypotheses Schemas Tests (EvidenceRef, HypothesisScore, Hypothesis)
# ==============================================================================

class TestEvidenceRef:
    def test_valid_instance(self):
        ev_id = uuid4()
        ref = EvidenceRef(
            evidence_type=EventSource.METRIC,
            evidence_id=ev_id,
            relevance_note="Shows 10x spike in database connection latency at 14:02 UTC",
        )
        assert ref.evidence_type == EventSource.METRIC
        assert ref.evidence_id == ev_id
        assert ref.relevance_note.startswith("Shows 10x spike")

    def test_missing_required_field(self):
        with pytest.raises(ValidationError) as exc_info:
            EvidenceRef(
                relevance_note="Relevant evidence"
                # missing evidence_type, evidence_id
            )
        missing_fields = {e["loc"][0] for e in exc_info.value.errors() if e["type"] == "missing"}
        assert {"evidence_type", "evidence_id"}.issubset(missing_fields)

    def test_invalid_type_field(self):
        with pytest.raises(ValidationError):
            EvidenceRef(
                evidence_type="unknown_evidence_type",  # invalid EventSource
                evidence_id="not-a-uuid",
                relevance_note="Note",
            )


class TestHypothesisScore:
    def test_valid_instance(self):
        score = HypothesisScore(
            temporal_fit=0.92,
            causal_fit=0.88,
            evidence_support=0.95,
            system_dependency_fit=0.85,
            change_proximity=0.90,
            contradictory_evidence_penalty=0.0,
            unexplained_symptoms_penalty=0.05,
            final_score=0.89,
        )
        assert score.temporal_fit == 0.92
        assert score.final_score == 0.89

    def test_missing_required_field(self):
        with pytest.raises(ValidationError) as exc_info:
            HypothesisScore(
                temporal_fit=0.92
                # missing causal_fit, evidence_support, system_dependency_fit, change_proximity, contradictory_evidence_penalty, unexplained_symptoms_penalty, final_score
            )
        missing_fields = {e["loc"][0] for e in exc_info.value.errors() if e["type"] == "missing"}
        assert {"causal_fit", "evidence_support", "system_dependency_fit", "change_proximity", "contradictory_evidence_penalty", "unexplained_symptoms_penalty", "final_score"}.issubset(missing_fields)

    def test_invalid_type_field(self):
        with pytest.raises(ValidationError):
            HypothesisScore(
                temporal_fit="high",  # float expected
                causal_fit=0.8,
                evidence_support=0.9,
                system_dependency_fit=0.8,
                change_proximity=0.9,
                contradictory_evidence_penalty=0.0,
                unexplained_symptoms_penalty=0.0,
                final_score=0.85,
            )


class TestHypothesis:
    def test_valid_instance(self):
        hyp_id = uuid4()
        inc_id = uuid4()
        ev_id1 = uuid4()
        ev_id2 = uuid4()

        score = HypothesisScore(
            temporal_fit=0.95,
            causal_fit=0.90,
            evidence_support=0.85,
            system_dependency_fit=0.95,
            change_proximity=0.98,
            contradictory_evidence_penalty=0.0,
            unexplained_symptoms_penalty=0.0,
            final_score=0.93,
        )
        supporting = EvidenceRef(
            evidence_type=EventSource.DEPLOYMENT,
            evidence_id=ev_id1,
            relevance_note="Deployment v2.14.0 completed 2 minutes prior to first 504 error",
        )
        contradicting = EvidenceRef(
            evidence_type=EventSource.ALERT,
            evidence_id=ev_id2,
            relevance_note="Auth service CPU normal during initial alert window",
        )

        hypothesis = Hypothesis(
            id=hyp_id,
            incident_id=inc_id,
            title="Database Connection Pool Exhaustion from Deployment v2.14.0",
            description="Commit e8f49b changed connection timeout default causing pool saturation under peak traffic",
            status=HypothesisStatus.SUPPORTED,
            score=score,
            supporting_evidence=[supporting],
            contradicting_evidence=[contradicting],
        )

        assert hypothesis.id == hyp_id
        assert hypothesis.incident_id == inc_id
        assert hypothesis.status == HypothesisStatus.SUPPORTED
        assert hypothesis.score.final_score == 0.93
        assert len(hypothesis.supporting_evidence) == 1
        assert len(hypothesis.contradicting_evidence) == 1

    def test_missing_required_field(self):
        with pytest.raises(ValidationError) as exc_info:
            Hypothesis(
                title="Hypothesis Title"
                # missing id, incident_id, description, status, score
            )
        missing_fields = {e["loc"][0] for e in exc_info.value.errors() if e["type"] == "missing"}
        assert {"id", "incident_id", "description", "status", "score"}.issubset(missing_fields)

    def test_invalid_type_field(self):
        with pytest.raises(ValidationError):
            Hypothesis(
                id="not-a-uuid",
                incident_id="not-a-uuid",
                title="Title",
                description="Desc",
                status="invalid_status",
                score="not-a-score-object",
            )
