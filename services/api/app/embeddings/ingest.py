import gc
from typing import Any
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.conversions import (
    alert_to_orm,
    database_event_to_orm,
    deployment_to_orm,
    git_commit_to_orm,
    ground_truth_to_orm,
    incident_to_orm,
    log_entry_to_orm,
    metric_point_to_orm,
    normalized_event_to_orm,
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
    LogORM,
    MetricORM,
    NormalizedEventORM,
    TraceSpanORM,
)
from app.schemas.alerts import Alert
from app.schemas.database_events import DatabaseEvent
from app.schemas.deployments import Deployment, GitCommit
from app.schemas.events import LogEntry, MetricPoint, TraceSpan
from app.schemas.incidents import Incident

from .provider import EmbeddingProvider, get_embedding_provider


async def _batch_flush_objects(session: AsyncSession, objects: list[Any], chunk_size: int = 400) -> None:
    """Flushes objects to DB in small batches to keep memory consumption low."""
    for i in range(0, len(objects), chunk_size):
        chunk = objects[i : i + chunk_size]
        session.add_all(chunk)
        await session.flush()
        import asyncio
        await asyncio.sleep(0.02)


async def ingest_incident_evidence(
    session: AsyncSession,
    incident: Incident,
    bundle: dict[str, list[Any]],
    provider: EmbeddingProvider | None = None,
) -> None:
    """Ingests a generated incident and its evidence bundle into the database idempotently.
    
    Uses chunked batch inserts to guarantee memory usage remains strictly < 40MB on free tiers.
    """
    embedder = provider or get_embedding_provider()
    inc_id = incident.incident_id

    # 1. Idempotency cleanup
    await session.execute(delete(NormalizedEventORM).where(NormalizedEventORM.incident_id == inc_id))
    await session.execute(delete(LogORM).where(LogORM.incident_id == inc_id))
    await session.execute(delete(MetricORM).where(MetricORM.incident_id == inc_id))
    await session.execute(delete(TraceSpanORM).where(TraceSpanORM.incident_id == inc_id))
    await session.execute(delete(DeploymentORM).where(DeploymentORM.incident_id == inc_id))
    await session.execute(delete(GitCommitORM).where(GitCommitORM.incident_id == inc_id))
    await session.execute(delete(DatabaseEventORM).where(DatabaseEventORM.incident_id == inc_id))
    await session.execute(delete(AlertORM).where(AlertORM.incident_id == inc_id))
    await session.execute(delete(GroundTruthORM).where(GroundTruthORM.incident_id == inc_id))
    await session.execute(delete(IncidentORM).where(IncidentORM.incident_id == inc_id))

    # 2. Persist Incident & GroundTruth
    inc_orm = incident_to_orm(incident)
    gt_orm = ground_truth_to_orm(incident.ground_truth, inc_id)
    session.add(inc_orm)
    session.add(gt_orm)
    await session.flush()

    normalized_events: list[NormalizedEventORM] = []

    # 3. Ingest Logs (batch embedded)
    logs: list[LogEntry] = bundle.get("logs", [])
    if logs:
        log_messages = [log.message for log in logs]
        log_embeddings = embedder.embed_batch(log_messages)
        log_orms: list[LogORM] = []
        for raw_log, emb in zip(logs, log_embeddings, strict=False):
            log_orm = log_entry_to_orm(raw_log, inc_id, embedding=emb)
            log_orms.append(log_orm)
            norm_evt = raw_to_normalized_event(raw_log, event_id=log_orm.id)
            normalized_events.append(normalized_event_to_orm(norm_evt, inc_id))
        await _batch_flush_objects(session, log_orms)
        del log_messages, log_embeddings, log_orms

    # 4. Ingest Metrics
    metrics = bundle.get("metrics", [])
    if metrics:
        metric_orms = []
        for raw_metric in metrics:
            assert isinstance(raw_metric, MetricPoint)
            metric_orm = metric_point_to_orm(raw_metric, inc_id)
            metric_orms.append(metric_orm)
            norm_evt = raw_to_normalized_event(raw_metric, event_id=metric_orm.id)
            normalized_events.append(normalized_event_to_orm(norm_evt, inc_id))
        await _batch_flush_objects(session, metric_orms)
        del metric_orms

    # 5. Ingest Traces
    traces = bundle.get("traces", [])
    if traces:
        trace_orms = []
        for raw_trace in traces:
            assert isinstance(raw_trace, TraceSpan)
            trace_orm = trace_span_to_orm(raw_trace, inc_id)
            trace_orms.append(trace_orm)
            norm_evt = raw_to_normalized_event(raw_trace, event_id=trace_orm.id)
            normalized_events.append(normalized_event_to_orm(norm_evt, inc_id))
        await _batch_flush_objects(session, trace_orms)
        del trace_orms

    # 6. Ingest Deployments
    deployments = bundle.get("deployments", [])
    if deployments:
        dep_orms = []
        for raw_dep in deployments:
            assert isinstance(raw_dep, Deployment)
            dep_orm = deployment_to_orm(raw_dep, inc_id)
            dep_orms.append(dep_orm)
            norm_evt = raw_to_normalized_event(raw_dep, event_id=dep_orm.deployment_id)
            normalized_events.append(normalized_event_to_orm(norm_evt, inc_id))
        await _batch_flush_objects(session, dep_orms)
        del dep_orms

    # 7. Ingest Commits
    commits = bundle.get("commits", [])
    if commits:
        commit_summaries = [c.diff_summary for c in commits]
        commit_embeddings = embedder.embed_batch(commit_summaries)
        commit_orms = []
        for raw_commit, emb in zip(commits, commit_embeddings, strict=False):
            assert isinstance(raw_commit, GitCommit)
            commit_orm = git_commit_to_orm(raw_commit, inc_id, embedding=emb)
            commit_orms.append(commit_orm)
            norm_evt = raw_to_normalized_event(raw_commit)
            normalized_events.append(normalized_event_to_orm(norm_evt, inc_id))
        await _batch_flush_objects(session, commit_orms)
        del commit_summaries, commit_embeddings, commit_orms

    # 8. Ingest Database Events
    db_events = bundle.get("database_events", [])
    if db_events:
        db_orms = []
        for raw_db_evt in db_events:
            assert isinstance(raw_db_evt, DatabaseEvent)
            db_orm = database_event_to_orm(raw_db_evt, inc_id)
            db_orms.append(db_orm)
            norm_evt = raw_to_normalized_event(raw_db_evt, event_id=db_orm.id)
            normalized_events.append(normalized_event_to_orm(norm_evt, inc_id))
        await _batch_flush_objects(session, db_orms)
        del db_orms

    # 9. Ingest Alerts
    alerts = bundle.get("alerts", [])
    if alerts:
        alert_texts = [f"{a.alert_type} {a.service} {a.description}" for a in alerts]
        alert_embeddings = embedder.embed_batch(alert_texts)
        alert_orms = []
        for raw_alert, emb in zip(alerts, alert_embeddings, strict=False):
            assert isinstance(raw_alert, Alert)
            alert_orm = alert_to_orm(raw_alert, inc_id, embedding=emb)
            alert_orms.append(alert_orm)
            norm_evt = raw_to_normalized_event(raw_alert, event_id=alert_orm.id)
            normalized_events.append(normalized_event_to_orm(norm_evt, inc_id))
        await _batch_flush_objects(session, alert_orms)
        del alert_texts, alert_embeddings, alert_orms

    # 10. Persist Normalized Events in Batches
    if normalized_events:
        await _batch_flush_objects(session, normalized_events)
        del normalized_events

    await session.commit()
    gc.collect()
