import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select

# Ensure app package is importable regardless of working directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.base import Base, get_db_session, reset_engine
from app.db.conversions import (
    alert_to_orm,
    database_event_to_orm,
    deployment_to_orm,
    git_commit_to_orm,
    ground_truth_to_orm,
    incident_to_orm,
    investigation_step_to_orm,
    investigation_to_orm,
    log_entry_to_orm,
    metric_point_to_orm,
    normalized_event_to_orm,
    orm_to_alert,
    orm_to_database_event,
    orm_to_deployment,
    orm_to_git_commit,
    orm_to_ground_truth,
    orm_to_incident,
    orm_to_investigation,
    orm_to_investigation_step,
    orm_to_log_entry,
    orm_to_metric_point,
    orm_to_normalized_event,
    orm_to_trace_span,
    raw_to_normalized_event,
    trace_span_to_orm,
)
from app.db.models import (
    AlertORM,
    DatabaseEventORM,
    DeploymentORM,
    GitCommitORM,
    GroundTruthORM,
    IncidentORM,
    InvestigationORM,
    InvestigationStepORM,
    LogORM,
    MetricORM,
    NormalizedEventORM,
    TraceSpanORM,
)
from app.embeddings.ingest import ingest_incident_evidence
from app.embeddings.provider import DeterministicEmbeddingProvider
from app.generator import (
    generate_bad_deployment_db_exhaustion_incident,
    generate_dependency_failure_cascade_incident,
    generate_healthy_environment,
)
from app.retrieval import (
    get_changes_before,
    get_events_for_dependencies,
    get_events_for_entity,
    get_events_in_window,
    search_similar,
)
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
from app.schemas.incidents import (
    CausalChainLink,
    GroundTruth,
    Incident,
    IncidentDifficulty,
    IncidentSeverity,
)
from app.schemas.investigations import (
    Investigation,
    InvestigationState,
    InvestigationStep,
)


@pytest.fixture(scope="module", autouse=True)
def setup_test_db():
    """Initializes in-memory/file async SQLite database for testing."""
    test_db_url = "sqlite+aiosqlite:///:memory:"
    engine = asyncio.run(reset_engine(test_db_url))

    async def init_tables():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(init_tables())
    yield
    asyncio.run(reset_engine())


class TestModelConversionsRoundTrip:
    """1. Round-trip test: every Pydantic model -> ORM -> Pydantic produces an equal object."""

    def test_log_entry_round_trip(self):
        inc_id = uuid4()
        log = LogEntry(
            timestamp=datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc),
            service="checkout-service",
            severity=EventSeverity.ERROR,
            message="Database query timed out after 5000ms",
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            request_id="req-123456",
            metadata={"env": "production", "host": "pod-1"},
        )
        orm = log_entry_to_orm(log, inc_id, embedding=[0.1] * 128)
        reconstructed = orm_to_log_entry(orm)
        assert reconstructed == log

    def test_metric_point_round_trip(self):
        inc_id = uuid4()
        metric = MetricPoint(
            timestamp=datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc),
            service="checkout-service",
            metric_name="latency_p95_ms",
            value=3420.5,
            unit="ms",
            labels={"service": "checkout-service", "env": "production"},
        )
        orm = metric_point_to_orm(metric, inc_id)
        reconstructed = orm_to_metric_point(orm)
        assert reconstructed == metric

    def test_trace_span_round_trip(self):
        inc_id = uuid4()
        span = TraceSpan(
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            span_id="00f067aa0ba902b7",
            parent_span_id="5fb397be34d23b0f",
            service="checkout-service",
            operation="POST /checkout/process",
            start_time=datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc),
            duration_ms=5012.3,
            status="error",
            attributes={"http.status_code": "500", "error": "true"},
        )
        orm = trace_span_to_orm(span, inc_id)
        reconstructed = orm_to_trace_span(orm)
        assert reconstructed == span

    def test_deployment_round_trip(self):
        inc_id = uuid4()
        dep = Deployment(
            deployment_id=uuid4(),
            service="checkout-service",
            version="v2.15.0",
            commit_sha="a1b2c3d4e5f67890123456789abcdef012345678",
            started_at=datetime(2026, 8, 30, 13, 55, 0, tzinfo=timezone.utc),
            completed_at=datetime(2026, 8, 30, 13, 58, 0, tzinfo=timezone.utc),
            environment="production",
            status=DeploymentStatus.SUCCESS,
        )
        orm = deployment_to_orm(dep, inc_id)
        reconstructed = orm_to_deployment(orm)
        assert reconstructed == dep

    def test_git_commit_round_trip(self):
        inc_id = uuid4()
        commit = GitCommit(
            commit_sha="a1b2c3d4e5f67890123456789abcdef012345678",
            author="engineer@corp.internal",
            timestamp=datetime(2026, 8, 30, 13, 50, 0, tzinfo=timezone.utc),
            repository="corp/checkout-service",
            files_changed=["src/checkout/summary.py"],
            diff_summary="Add itemized discount calculation",
            symbols_changed=["summary.calculate_discounts"],
        )
        orm = git_commit_to_orm(commit, inc_id, embedding=[0.2] * 128)
        reconstructed = orm_to_git_commit(orm)
        assert reconstructed == commit

    def test_database_event_round_trip(self):
        inc_id = uuid4()
        db_evt = DatabaseEvent(
            timestamp=datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc),
            database="checkout_db",
            query_fingerprint="SELECT * FROM discount_rules WHERE item_id = ?",
            duration_ms=5021.0,
            connections_active=98,
            connections_max=100,
            locks_held=6,
            rows_affected=0,
            status=DatabaseEventStatus.TIMEOUT,
        )
        orm = database_event_to_orm(db_evt, inc_id)
        reconstructed = orm_to_database_event(orm)
        assert reconstructed == db_evt

    def test_alert_round_trip(self):
        inc_id = uuid4()
        alert = Alert(
            timestamp=datetime(2026, 8, 30, 14, 3, 0, tzinfo=timezone.utc),
            alert_type="High5xxErrorRate",
            service="checkout-service",
            severity=AlertSeverity.CRITICAL,
            description="5xx error rate exceeded 5% threshold",
        )
        orm = alert_to_orm(alert, inc_id, embedding=[0.3] * 128)
        reconstructed = orm_to_alert(orm)
        assert reconstructed == alert

    def test_ground_truth_round_trip(self):
        inc_id = uuid4()
        dep_id = uuid4()
        gt = GroundTruth(
            root_cause="Deployment v2.15.0 caused N+1 database query leak",
            causal_chain=[
                CausalChainLink(
                    from_node="deployment",
                    to_node="query_surge",
                    relationship="caused",
                    explanation="Loop queries saturated connection pool",
                )
            ],
            responsible_commit_sha="c0ffee1234",
            responsible_deployment_id=dep_id,
        )
        orm = ground_truth_to_orm(gt, inc_id)
        reconstructed = orm_to_ground_truth(orm)
        assert reconstructed == gt

    def test_normalized_event_round_trip(self):
        inc_id = uuid4()
        evt = NormalizedEvent(
            id=uuid4(),
            timestamp=datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc),
            source=EventSource.LOG,
            entity="checkout-service",
            event_type="http_5xx",
            service="checkout-service",
            severity=EventSeverity.ERROR,
            attributes={"status_code": 500, "duration_ms": 5012.3},
            relationships=["req-98765"],
        )
        orm = normalized_event_to_orm(evt, inc_id)
        reconstructed = orm_to_normalized_event(orm)
        assert reconstructed == evt

    def test_incident_round_trip(self):
        gt = GroundTruth(root_cause="Test root cause", causal_chain=[])
        inc = Incident(
            incident_id=uuid4(),
            incident_type="dependency_failure_cascade",
            start_time=datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 8, 30, 14, 15, 0, tzinfo=timezone.utc),
            severity=IncidentSeverity.SEV1,
            difficulty=IncidentDifficulty.MEDIUM,
            affected_services=["checkout-service", "payment-service"],
            expected_symptoms=["high_latency", "504_timeouts"],
            ground_truth=gt,
        )
        orm = incident_to_orm(inc)
        reconstructed = orm_to_incident(orm, ground_truth=inc.ground_truth)
        assert reconstructed == inc

    def test_investigation_and_steps_round_trip(self):
        inv_id = uuid4()
        inc_id = uuid4()
        hyp_id = uuid4()
        now = datetime(2026, 8, 30, 14, 10, 0, tzinfo=timezone.utc)
        step = InvestigationStep(
            step_number=1,
            state=InvestigationState.INVESTIGATING_HYPOTHESIS,
            timestamp=now,
            summary="Investigating leading hypothesis",
            details={"score": 85.0},
        )
        step_orm = investigation_step_to_orm(step, inv_id)
        reconstructed_step = orm_to_investigation_step(step_orm)
        assert reconstructed_step.step_number == step.step_number
        assert reconstructed_step.state == step.state
        assert reconstructed_step.summary == step.summary
        assert reconstructed_step.details == step.details

        inv = Investigation(
            investigation_id=inv_id,
            incident_id=inc_id,
            steps=[step],
            final_state=InvestigationState.RCA_GENERATED,
            leading_hypothesis_id=hyp_id,
            confidence=92.5,
            started_at=now,
            completed_at=now,
            rca_narrative="Confirmed root cause.",
        )
        inv_orm = investigation_to_orm(inv)
        reconstructed_inv = orm_to_investigation(inv_orm, steps=[reconstructed_step])
        assert reconstructed_inv.investigation_id == inv.investigation_id
        assert reconstructed_inv.final_state == inv.final_state
        assert reconstructed_inv.confidence == inv.confidence
        assert reconstructed_inv.rca_narrative == inv.rca_narrative
        assert len(reconstructed_inv.steps) == 1


class TestGroundTruthTableIsolation:
    """2. Ground truths table isolation: assert no investigator retrieval query joins or references 'ground_truths'."""

    def test_retrieval_functions_never_reference_ground_truth_table(self):
        # Inspect source code of all retrieval modules to confirm zero references to ground_truth table
        retrieval_dir = Path(__file__).resolve().parent.parent / "app" / "retrieval"
        for py_file in retrieval_dir.glob("*.py"):
            lines = py_file.read_text(encoding="utf-8").splitlines()
            # Must contain the explicit isolation header comment
            assert any("CRITICAL ISOLATION ENFORCEMENT" in l for l in lines), f"Missing isolation header in {py_file.name}"
            
            code_lines = [l for l in lines if not l.strip().startswith("#")]
            code_body = "\n".join(code_lines)
            # Must NOT import or query GroundTruthORM or ground_truths table in code
            assert "GroundTruthORM" not in code_body, f"GroundTruthORM illegally referenced in {py_file.name}"
            assert "ground_truths" not in code_body.lower(), f"'ground_truths' table queried in {py_file.name}"
            assert "ground_truth" not in code_body.lower(), f"'ground_truth' field queried in {py_file.name}"

    def test_executed_sql_queries_never_mention_ground_truth_both_incidents(self):
        """DB-query-level enforcement: intercepts actual generated SQL queries across retrieval functions for BOTH incident types."""
        async def run():
            test_db_url = "sqlite+aiosqlite:///:memory:"
            engine = await reset_engine(test_db_url)
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            executed_sqls: list[str] = []

            def record_sql(conn, cursor, statement, parameters, context, executemany):
                executed_sqls.append(statement)

            event.listen(engine.sync_engine, "before_cursor_execute", record_sql)

            embedder = DeterministicEmbeddingProvider(dim=384)
            start = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)

            # Test Incident Type 1: bad_deployment_db_exhaustion
            env1 = generate_healthy_environment(seed=101, start=start, duration_minutes=15)
            inc1, bundle1 = generate_bad_deployment_db_exhaustion_incident(
                seed=101, base_environment=env1, incident_start=start, duration_minutes=15
            )

            # Test Incident Type 2: dependency_failure_cascade
            env2 = generate_healthy_environment(seed=202, start=start, duration_minutes=15)
            inc2, bundle2 = generate_dependency_failure_cascade_incident(
                seed=202, base_environment=env2, incident_start=start, duration_minutes=15
            )

            async with get_db_session() as session:
                await ingest_incident_evidence(session, inc1, bundle1, provider=embedder)
                await ingest_incident_evidence(session, inc2, bundle2, provider=embedder)

                # Clear ingestion SQLs to specifically inspect investigator retrieval queries
                executed_sqls.clear()

                # Run all 5 retrieval functions against Incident 1
                await get_events_in_window(session, inc1.incident_id, start, start)
                await get_events_for_entity(session, inc1.incident_id, "checkout-service")
                await get_events_for_dependencies(session, inc1.incident_id, "checkout-service")
                await get_changes_before(session, inc1.incident_id, start)
                await search_similar(session, inc1.incident_id, "connection timeout error", provider=embedder)

                # Run all 5 retrieval functions against Incident 2
                await get_events_in_window(session, inc2.incident_id, start, start)
                await get_events_for_entity(session, inc2.incident_id, "payment-service")
                await get_events_for_dependencies(session, inc2.incident_id, "payment-service")
                await get_changes_before(session, inc2.incident_id, start)
                await search_similar(session, inc2.incident_id, "thread pool exhaustion", provider=embedder)

                # Assert that queries were executed and NONE referenced ground_truths table
                assert len(executed_sqls) >= 10, "Expected at least 10 executed retrieval queries"
                for query in executed_sqls:
                    q_lower = query.lower()
                    assert "ground_truths" not in q_lower, f"CRITICAL LEAK: 'ground_truths' referenced in executed query: {query}"
                    assert "ground_truth" not in q_lower, f"CRITICAL LEAK: 'ground_truth' referenced in executed query: {query}"

            event.remove(engine.sync_engine, "before_cursor_execute", record_sql)

        asyncio.run(run())


class TestIdempotentIngestion:
    """3. Idempotent ingest: running ingest twice on the same incident produces no duplicate rows."""

    def test_ingest_is_idempotent_bad_deployment_incident(self):
        async def run_test():
            start = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
            base_env = generate_healthy_environment(seed=42, start=start, duration_minutes=5)
            incident, bundle = generate_bad_deployment_db_exhaustion_incident(
                seed=42, base_environment=base_env, incident_start=start, duration_minutes=5
            )

            embedder = DeterministicEmbeddingProvider(dim=384)

            async with get_db_session() as session:
                # First ingest
                await ingest_incident_evidence(session, incident, bundle, provider=embedder)

                # Record counts
                count_norm_1 = (await session.execute(
                    select(func.count(NormalizedEventORM.id)).where(NormalizedEventORM.incident_id == incident.incident_id)
                )).scalar_one()
                count_logs_1 = (await session.execute(
                    select(func.count(LogORM.id)).where(LogORM.incident_id == incident.incident_id)
                )).scalar_one()

                # Second ingest (idempotent overwrite)
                await ingest_incident_evidence(session, incident, bundle, provider=embedder)

                count_norm_2 = (await session.execute(
                    select(func.count(NormalizedEventORM.id)).where(NormalizedEventORM.incident_id == incident.incident_id)
                )).scalar_one()
                count_logs_2 = (await session.execute(
                    select(func.count(LogORM.id)).where(LogORM.incident_id == incident.incident_id)
                )).scalar_one()

                assert count_norm_1 == count_norm_2 > 0
                assert count_logs_1 == count_logs_2 > 0

        asyncio.run(run_test())

    def test_ingest_is_idempotent_dependency_failure_incident(self):
        async def run_test():
            start = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
            base_env = generate_healthy_environment(seed=84, start=start, duration_minutes=5)
            incident, bundle = generate_dependency_failure_cascade_incident(
                seed=84, base_environment=base_env, incident_start=start, duration_minutes=5
            )

            embedder = DeterministicEmbeddingProvider(dim=384)

            async with get_db_session() as session:
                # First ingest
                await ingest_incident_evidence(session, incident, bundle, provider=embedder)

                # Record counts
                count_norm_1 = (await session.execute(
                    select(func.count(NormalizedEventORM.id)).where(NormalizedEventORM.incident_id == incident.incident_id)
                )).scalar_one()
                count_logs_1 = (await session.execute(
                    select(func.count(LogORM.id)).where(LogORM.incident_id == incident.incident_id)
                )).scalar_one()

                # Second ingest (idempotent overwrite)
                await ingest_incident_evidence(session, incident, bundle, provider=embedder)

                count_norm_2 = (await session.execute(
                    select(func.count(NormalizedEventORM.id)).where(NormalizedEventORM.incident_id == incident.incident_id)
                )).scalar_one()
                count_logs_2 = (await session.execute(
                    select(func.count(LogORM.id)).where(LogORM.incident_id == incident.incident_id)
                )).scalar_one()

                assert count_norm_1 == count_norm_2 > 0
                assert count_logs_1 == count_logs_2 > 0

        asyncio.run(run_test())
