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


async def ingest_incident_evidence(
    session: AsyncSession,
    incident: Incident,
    bundle: dict[str, list[Any]],
    provider: EmbeddingProvider | None = None,
) -> None:
    """Ingests a generated incident and its evidence bundle into the database idempotently.
    
    1. Removes existing records for incident_id (idempotency guarantee).
    2. Persists IncidentORM (without ground truth).
    3. Persists GroundTruthORM in the isolated 'ground_truths' table.
    4. Computes batch embeddings for text fields and persists all raw telemetry and lifecycle tables.
    5. Normalizes all evidence items and persists them into 'normalized_events'.
    """
    embedder = provider or get_embedding_provider()
    inc_id = incident.incident_id

    # --------------------------------------------------------------------------
    # 1. Idempotency: Clean up any prior data for this incident_id
    # --------------------------------------------------------------------------
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

    # --------------------------------------------------------------------------
    # 2. Persist Incident & GroundTruth
    # --------------------------------------------------------------------------
    inc_orm = incident_to_orm(incident)
    gt_orm = ground_truth_to_orm(incident.ground_truth, inc_id)
    session.add(inc_orm)
    session.add(gt_orm)

    normalized_events: list[NormalizedEventORM] = []

    # --------------------------------------------------------------------------
    # 3. Ingest Logs (with batch text embeddings)
    # --------------------------------------------------------------------------
    logs: list[LogEntry] = bundle.get("logs", [])
    if logs:
        log_messages = [log.message for log in logs]
        log_embeddings = embedder.embed_batch(log_messages)
        for raw_log, emb in zip(logs, log_embeddings, strict=False):
            log_orm = log_entry_to_orm(raw_log, inc_id, embedding=emb)
            session.add(log_orm)
            
            norm_evt = raw_to_normalized_event(raw_log, event_id=log_orm.id)
            normalized_events.append(normalized_event_to_orm(norm_evt, inc_id))

    # --------------------------------------------------------------------------
    # 4. Ingest Metrics
    # --------------------------------------------------------------------------
    for raw_metric in bundle.get("metrics", []):
        assert isinstance(raw_metric, MetricPoint)
        m_orm = metric_point_to_orm(raw_metric, inc_id)
        session.add(m_orm)
        
        norm_evt = raw_to_normalized_event(raw_metric, event_id=m_orm.id)
        normalized_events.append(normalized_event_to_orm(norm_evt, inc_id))

    # --------------------------------------------------------------------------
    # 5. Ingest Traces
    # --------------------------------------------------------------------------
    for raw_trace in bundle.get("traces", []):
        assert isinstance(raw_trace, TraceSpan)
        t_orm = trace_span_to_orm(raw_trace, inc_id)
        session.add(t_orm)
        
        norm_evt = raw_to_normalized_event(raw_trace, event_id=t_orm.id)
        normalized_events.append(normalized_event_to_orm(norm_evt, inc_id))

    # --------------------------------------------------------------------------
    # 6. Ingest Deployments
    # --------------------------------------------------------------------------
    for raw_dep in bundle.get("deployments", []):
        assert isinstance(raw_dep, Deployment)
        dep_orm = deployment_to_orm(raw_dep, inc_id)
        session.add(dep_orm)
        
        norm_evt = raw_to_normalized_event(raw_dep, event_id=raw_dep.deployment_id)
        normalized_events.append(normalized_event_to_orm(norm_evt, inc_id))

    # --------------------------------------------------------------------------
    # 7. Ingest Commits (with batch text embeddings)
    # --------------------------------------------------------------------------
    commits: list[GitCommit] = bundle.get("commits", [])
    if commits:
        commit_summaries = [c.diff_summary for c in commits]
        commit_embeddings = embedder.embed_batch(commit_summaries)
        for raw_commit, emb in zip(commits, commit_embeddings, strict=False):
            c_orm = git_commit_to_orm(raw_commit, inc_id, embedding=emb)
            session.add(c_orm)
            
            norm_evt = raw_to_normalized_event(raw_commit)
            normalized_events.append(normalized_event_to_orm(norm_evt, inc_id))

    # --------------------------------------------------------------------------
    # 8. Ingest Database Events
    # --------------------------------------------------------------------------
    for raw_db in bundle.get("database_events", []):
        assert isinstance(raw_db, DatabaseEvent)
        db_orm = database_event_to_orm(raw_db, inc_id)
        session.add(db_orm)
        
        norm_evt = raw_to_normalized_event(raw_db, event_id=db_orm.id)
        normalized_events.append(normalized_event_to_orm(norm_evt, inc_id))

    # --------------------------------------------------------------------------
    # 9. Ingest Alerts (with batch text embeddings)
    # --------------------------------------------------------------------------
    alerts: list[Alert] = bundle.get("alerts", [])
    if alerts:
        alert_descriptions = [a.description for a in alerts]
        alert_embeddings = embedder.embed_batch(alert_descriptions)
        for raw_alert, emb in zip(alerts, alert_embeddings, strict=False):
            a_orm = alert_to_orm(raw_alert, inc_id, embedding=emb)
            session.add(a_orm)
            
            norm_evt = raw_to_normalized_event(raw_alert, event_id=a_orm.id)
            normalized_events.append(normalized_event_to_orm(norm_evt, inc_id))

    # --------------------------------------------------------------------------
    # 10. Persist Normalized Events
    # --------------------------------------------------------------------------
    session.add_all(normalized_events)
    await session.flush()
