from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

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
from app.schemas.investigations import Investigation, InvestigationState, InvestigationStep
from app.schemas.services import ServiceDefinition, ServiceDependency

from .models import (
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
    ServiceDependencyORM,
    ServiceORM,
    TraceSpanORM,
)


def _ensure_utc(dt: datetime | None) -> datetime | None:
    """Ensures datetime instance is timezone-aware in UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ==============================================================================
# Logs Conversions
# ==============================================================================

def log_entry_to_orm(
    entry: LogEntry,
    incident_id: UUID,
    embedding: list[float] | None = None,
) -> LogORM:
    return LogORM(
        id=uuid4(),
        incident_id=incident_id,
        timestamp=_ensure_utc(entry.timestamp),
        service=entry.service,
        severity=entry.severity.value,
        message=entry.message,
        trace_id=entry.trace_id,
        request_id=entry.request_id,
        metadata_json=entry.metadata,
        embedding=embedding,
    )


def orm_to_log_entry(orm: LogORM) -> LogEntry:
    return LogEntry(
        timestamp=_ensure_utc(orm.timestamp),
        service=orm.service,
        severity=EventSeverity(orm.severity),
        message=orm.message,
        trace_id=orm.trace_id,
        request_id=orm.request_id,
        metadata=dict(orm.metadata_json or {}),
    )


# ==============================================================================
# Metrics Conversions
# ==============================================================================

def metric_point_to_orm(point: MetricPoint, incident_id: UUID) -> MetricORM:
    return MetricORM(
        id=uuid4(),
        incident_id=incident_id,
        timestamp=_ensure_utc(point.timestamp),
        service=point.service,
        metric_name=point.metric_name,
        value=point.value,
        unit=point.unit,
        labels=point.labels,
    )


def orm_to_metric_point(orm: MetricORM) -> MetricPoint:
    return MetricPoint(
        timestamp=_ensure_utc(orm.timestamp),
        service=orm.service,
        metric_name=orm.metric_name,
        value=orm.value,
        unit=orm.unit,
        labels=dict(orm.labels or {}),
    )


# ==============================================================================
# Traces Conversions
# ==============================================================================

def trace_span_to_orm(span: TraceSpan, incident_id: UUID) -> TraceSpanORM:
    return TraceSpanORM(
        id=uuid4(),
        incident_id=incident_id,
        trace_id=span.trace_id,
        span_id=span.span_id,
        parent_span_id=span.parent_span_id,
        service=span.service,
        operation=span.operation,
        start_time=_ensure_utc(span.start_time),
        duration_ms=span.duration_ms,
        status=span.status,
        attributes=span.attributes,
    )


def orm_to_trace_span(orm: TraceSpanORM) -> TraceSpan:
    return TraceSpan(
        trace_id=orm.trace_id,
        span_id=orm.span_id,
        parent_span_id=orm.parent_span_id,
        service=orm.service,
        operation=orm.operation,
        start_time=_ensure_utc(orm.start_time),
        duration_ms=orm.duration_ms,
        status=orm.status,  # type: ignore
        attributes=dict(orm.attributes or {}),
    )


# ==============================================================================
# Deployments & Commits Conversions
# ==============================================================================

def deployment_to_orm(dep: Deployment, incident_id: UUID) -> DeploymentORM:
    return DeploymentORM(
        deployment_id=dep.deployment_id,
        incident_id=incident_id,
        service=dep.service,
        version=dep.version,
        commit_sha=dep.commit_sha,
        started_at=_ensure_utc(dep.started_at),
        completed_at=_ensure_utc(dep.completed_at),
        environment=dep.environment,
        status=dep.status.value,
    )


def orm_to_deployment(orm: DeploymentORM) -> Deployment:
    return Deployment(
        deployment_id=orm.deployment_id,
        service=orm.service,
        version=orm.version,
        commit_sha=orm.commit_sha,
        started_at=_ensure_utc(orm.started_at),
        completed_at=_ensure_utc(orm.completed_at),
        environment=orm.environment,
        status=DeploymentStatus(orm.status),
    )


def git_commit_to_orm(
    commit: GitCommit,
    incident_id: UUID,
    embedding: list[float] | None = None,
) -> GitCommitORM:
    return GitCommitORM(
        commit_sha=commit.commit_sha,
        incident_id=incident_id,
        author=commit.author,
        timestamp=_ensure_utc(commit.timestamp),
        repository=commit.repository,
        files_changed=commit.files_changed,
        diff_summary=commit.diff_summary,
        symbols_changed=commit.symbols_changed,
        embedding=embedding,
    )


def orm_to_git_commit(orm: GitCommitORM) -> GitCommit:
    return GitCommit(
        commit_sha=orm.commit_sha,
        author=orm.author,
        timestamp=_ensure_utc(orm.timestamp),
        repository=orm.repository,
        files_changed=list(orm.files_changed or []),
        diff_summary=orm.diff_summary,
        symbols_changed=list(orm.symbols_changed or []),
    )


# ==============================================================================
# Database Events Conversions
# ==============================================================================

def database_event_to_orm(evt: DatabaseEvent, incident_id: UUID) -> DatabaseEventORM:
    return DatabaseEventORM(
        id=uuid4(),
        incident_id=incident_id,
        timestamp=_ensure_utc(evt.timestamp),
        database_name=evt.database,
        query_fingerprint=evt.query_fingerprint,
        duration_ms=evt.duration_ms,
        connections_active=evt.connections_active,
        connections_max=evt.connections_max,
        locks_held=evt.locks_held,
        rows_affected=evt.rows_affected,
        status=evt.status.value,
    )


def orm_to_database_event(orm: DatabaseEventORM) -> DatabaseEvent:
    return DatabaseEvent(
        timestamp=_ensure_utc(orm.timestamp),
        database=orm.database_name,
        query_fingerprint=orm.query_fingerprint,
        duration_ms=orm.duration_ms,
        connections_active=orm.connections_active,
        connections_max=orm.connections_max,
        locks_held=orm.locks_held,
        rows_affected=orm.rows_affected,
        status=DatabaseEventStatus(orm.status),
    )


# ==============================================================================
# Alerts Conversions
# ==============================================================================

def alert_to_orm(
    alert: Alert,
    incident_id: UUID,
    embedding: list[float] | None = None,
) -> AlertORM:
    return AlertORM(
        id=uuid4(),
        incident_id=incident_id,
        timestamp=_ensure_utc(alert.timestamp),
        alert_type=alert.alert_type,
        service=alert.service,
        severity=alert.severity.value,
        description=alert.description,
        embedding=embedding,
    )


def orm_to_alert(orm: AlertORM) -> Alert:
    return Alert(
        timestamp=_ensure_utc(orm.timestamp),
        alert_type=orm.alert_type,
        service=orm.service,
        severity=AlertSeverity(orm.severity),
        description=orm.description,
    )


# ==============================================================================
# Incident & GroundTruth Conversions
# ==============================================================================

def incident_to_orm(incident: Incident) -> IncidentORM:
    return IncidentORM(
        incident_id=incident.incident_id,
        incident_type=incident.incident_type,
        start_time=_ensure_utc(incident.start_time),
        end_time=_ensure_utc(incident.end_time),
        affected_services=incident.affected_services,
        expected_symptoms=incident.expected_symptoms,
        distractor_event_ids=[str(x) for x in incident.distractor_event_ids],
        difficulty=incident.difficulty.value,
        severity=incident.severity.value,
    )


def ground_truth_to_orm(gt: GroundTruth, incident_id: UUID) -> GroundTruthORM:
    return GroundTruthORM(
        incident_id=incident_id,
        root_cause=gt.root_cause,
        causal_chain=[link.model_dump() for link in gt.causal_chain],
        responsible_commit_sha=gt.responsible_commit_sha,
        responsible_deployment_id=gt.responsible_deployment_id,
    )


def orm_to_ground_truth(orm: GroundTruthORM) -> GroundTruth:
    causal_chain = [CausalChainLink(**link) for link in orm.causal_chain]
    return GroundTruth(
        root_cause=orm.root_cause,
        causal_chain=causal_chain,
        responsible_commit_sha=orm.responsible_commit_sha,
        responsible_deployment_id=orm.responsible_deployment_id,
    )


def orm_to_incident(orm: IncidentORM, ground_truth: GroundTruth | None = None) -> Incident:
    distractor_ids = [UUID(str(x)) for x in (orm.distractor_event_ids or [])]
    gt = ground_truth or GroundTruth(
        root_cause="UNAVAILABLE_IN_INVESTIGATOR_CONTEXT",
        causal_chain=[],
    )
    return Incident(
        incident_id=orm.incident_id,
        incident_type=orm.incident_type,
        start_time=_ensure_utc(orm.start_time),
        end_time=_ensure_utc(orm.end_time),
        affected_services=list(orm.affected_services or []),
        expected_symptoms=list(orm.expected_symptoms or []),
        distractor_event_ids=distractor_ids,
        difficulty=IncidentDifficulty(orm.difficulty),
        severity=IncidentSeverity(orm.severity),
        ground_truth=gt,
    )


# ==============================================================================
# NormalizedEvent Conversions & Raw Mapping
# ==============================================================================

def normalized_event_to_orm(evt: NormalizedEvent, incident_id: UUID) -> NormalizedEventORM:
    return NormalizedEventORM(
        id=evt.id,
        incident_id=incident_id,
        timestamp=_ensure_utc(evt.timestamp),
        source=evt.source.value,
        entity=evt.entity,
        event_type=evt.event_type,
        service=evt.service,
        severity=evt.severity.value if evt.severity else None,
        attributes=evt.attributes,
        relationships=evt.relationships,
    )


def orm_to_normalized_event(orm: NormalizedEventORM) -> NormalizedEvent:
    return NormalizedEvent(
        id=orm.id,
        timestamp=_ensure_utc(orm.timestamp),
        source=EventSource(orm.source),
        entity=orm.entity,
        event_type=orm.event_type,
        service=orm.service,
        severity=EventSeverity(orm.severity) if orm.severity else None,
        attributes=dict(orm.attributes or {}),
        relationships=list(orm.relationships or []),
    )


def raw_to_normalized_event(
    raw: LogEntry | MetricPoint | TraceSpan | DatabaseEvent | Alert | Deployment | GitCommit,
    event_id: UUID | None = None,
) -> NormalizedEvent:
    """Converts any raw telemetry or lifecycle model into the canonical NormalizedEvent model."""
    eid = event_id or uuid4()

    if isinstance(raw, LogEntry):
        attrs: dict[str, str | int | float | bool] = {
            "message": raw.message,
            **{k: v for k, v in raw.metadata.items() if isinstance(v, (str, int, float, bool))},
        }
        if raw.trace_id:
            attrs["trace_id"] = raw.trace_id
        if raw.request_id:
            attrs["request_id"] = raw.request_id
        return NormalizedEvent(
            id=eid,
            timestamp=_ensure_utc(raw.timestamp),
            source=EventSource.LOG,
            entity=raw.service,
            event_type=f"log_{raw.severity.value}",
            service=raw.service,
            severity=raw.severity,
            attributes=attrs,
            relationships=[raw.trace_id] if raw.trace_id else [],
        )

    if isinstance(raw, MetricPoint):
        attrs = {
            "metric_name": raw.metric_name,
            "value": raw.value,
            "unit": raw.unit,
            **{k: v for k, v in raw.labels.items() if isinstance(v, (str, int, float, bool))},
        }
        return NormalizedEvent(
            id=eid,
            timestamp=_ensure_utc(raw.timestamp),
            source=EventSource.METRIC,
            entity=raw.service,
            event_type=f"metric_{raw.metric_name}",
            service=raw.service,
            severity=None,
            attributes=attrs,
            relationships=[],
        )

    if isinstance(raw, TraceSpan):
        attrs = {
            "trace_id": raw.trace_id,
            "span_id": raw.span_id,
            "operation": raw.operation,
            "duration_ms": raw.duration_ms,
            "status": raw.status,
            **{k: v for k, v in raw.attributes.items() if isinstance(v, (str, int, float, bool))},
        }
        severity = EventSeverity.ERROR if raw.status == "error" else EventSeverity.INFO
        rels = [raw.parent_span_id] if raw.parent_span_id else []
        return NormalizedEvent(
            id=eid,
            timestamp=_ensure_utc(raw.start_time),
            source=EventSource.TRACE,
            entity=raw.service,
            event_type="trace_span",
            service=raw.service,
            severity=severity,
            attributes=attrs,
            relationships=rels,
        )

    if isinstance(raw, DatabaseEvent):
        attrs = {
            "database": raw.database,
            "query_fingerprint": raw.query_fingerprint,
            "duration_ms": raw.duration_ms,
            "connections_active": raw.connections_active,
            "connections_max": raw.connections_max,
            "locks_held": raw.locks_held,
            "rows_affected": raw.rows_affected,
            "status": raw.status.value,
        }
        sev = EventSeverity.ERROR if raw.status in (DatabaseEventStatus.ERROR, DatabaseEventStatus.TIMEOUT) else EventSeverity.INFO
        return NormalizedEvent(
            id=eid,
            timestamp=_ensure_utc(raw.timestamp),
            source=EventSource.DATABASE,
            entity=raw.database,
            event_type=f"db_{raw.status.value}",
            service=None,
            severity=sev,
            attributes=attrs,
            relationships=[],
        )

    if isinstance(raw, Alert):
        sev_map = {
            AlertSeverity.LOW: EventSeverity.INFO,
            AlertSeverity.MEDIUM: EventSeverity.WARNING,
            AlertSeverity.HIGH: EventSeverity.ERROR,
            AlertSeverity.CRITICAL: EventSeverity.CRITICAL,
        }
        return NormalizedEvent(
            id=eid,
            timestamp=_ensure_utc(raw.timestamp),
            source=EventSource.ALERT,
            entity=raw.service,
            event_type=f"alert_{raw.alert_type}",
            service=raw.service,
            severity=sev_map.get(raw.severity, EventSeverity.ERROR),
            attributes={
                "alert_type": raw.alert_type,
                "description": raw.description,
                "severity": raw.severity.value,
            },
            relationships=[],
        )

    if isinstance(raw, Deployment):
        return NormalizedEvent(
            id=raw.deployment_id,
            timestamp=_ensure_utc(raw.started_at),
            source=EventSource.DEPLOYMENT,
            entity=raw.service,
            event_type="deployment_rollout",
            service=raw.service,
            severity=EventSeverity.INFO if raw.status == DeploymentStatus.SUCCESS else EventSeverity.ERROR,
            attributes={
                "version": raw.version,
                "commit_sha": raw.commit_sha,
                "environment": raw.environment,
                "status": raw.status.value,
            },
            relationships=[raw.commit_sha],
        )

    if isinstance(raw, GitCommit):
        return NormalizedEvent(
            id=eid,
            timestamp=_ensure_utc(raw.timestamp),
            source=EventSource.COMMIT,
            entity=raw.repository,
            event_type="git_commit",
            service=raw.repository.split("/")[-1],
            severity=EventSeverity.INFO,
            attributes={
                "commit_sha": raw.commit_sha,
                "author": raw.author,
                "diff_summary": raw.diff_summary,
                "files_count": len(raw.files_changed),
            },
            relationships=[],
        )

    raise TypeError(f"Unsupported evidence type: {type(raw)}")


# ==============================================================================
# Investigation Conversions
# ==============================================================================

def investigation_step_to_orm(
    step: InvestigationStep,
    investigation_id: UUID,
) -> InvestigationStepORM:
    return InvestigationStepORM(
        id=uuid4(),
        investigation_id=investigation_id,
        step_number=step.step_number,
        state=step.state.value,
        timestamp=_ensure_utc(step.timestamp),
        summary=step.summary,
        details=step.details,
    )


def orm_to_investigation_step(orm: InvestigationStepORM) -> InvestigationStep:
    return InvestigationStep(
        step_number=orm.step_number,
        state=InvestigationState(orm.state),
        timestamp=_ensure_utc(orm.timestamp),
        summary=orm.summary,
        details=orm.details or {},
    )


def investigation_to_orm(
    inv: Investigation,
) -> InvestigationORM:
    return InvestigationORM(
        investigation_id=inv.investigation_id,
        incident_id=inv.incident_id,
        final_state=inv.final_state.value,
        leading_hypothesis_id=inv.leading_hypothesis_id,
        confidence=inv.confidence,
        started_at=_ensure_utc(inv.started_at),
        completed_at=_ensure_utc(inv.completed_at),
        rca_narrative=inv.rca_narrative,
    )


def orm_to_investigation(
    orm: InvestigationORM,
    steps: list[InvestigationStep] | None = None,
) -> Investigation:
    return Investigation(
        investigation_id=orm.investigation_id,
        incident_id=orm.incident_id,
        steps=steps or [],
        final_state=InvestigationState(orm.final_state),
        leading_hypothesis_id=orm.leading_hypothesis_id,
        confidence=orm.confidence,
        started_at=_ensure_utc(orm.started_at),
        completed_at=_ensure_utc(orm.completed_at),
        rca_narrative=orm.rca_narrative,
    )

