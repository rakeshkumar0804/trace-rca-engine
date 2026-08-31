"""Evidence API Router."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_fastapi_session
from app.db.models import (
    AlertORM,
    DatabaseEventORM,
    DeploymentORM,
    GitCommitORM,
    LogORM,
    MetricORM,
    NormalizedEventORM,
    TraceSpanORM,
)

router = APIRouter(prefix="/api/evidence", tags=["Evidence"])


@router.get("/{evidence_id}")
async def get_evidence_item(
    evidence_id: UUID,
    session: AsyncSession = Depends(get_fastapi_session),
) -> dict[str, Any]:
    """Fetches a single evidence item across all telemetry tables with full details."""
    # 1. Check LogORM
    log_stmt = select(LogORM).where(LogORM.id == evidence_id)
    log_row = (await session.execute(log_stmt)).scalar_one_or_none()
    if log_row:
        return {
            "evidence_id": str(log_row.id),
            "evidence_type": "log",
            "service": log_row.service,
            "timestamp": log_row.timestamp.isoformat(),
            "severity": log_row.severity,
            "message": log_row.message,
            "metadata": log_row.metadata_json or {},
        }

    # 2. Check MetricORM
    metric_stmt = select(MetricORM).where(MetricORM.id == evidence_id)
    metric_row = (await session.execute(metric_stmt)).scalar_one_or_none()
    if metric_row:
        return {
            "evidence_id": str(metric_row.id),
            "evidence_type": "metric",
            "service": metric_row.service,
            "timestamp": metric_row.timestamp.isoformat(),
            "metric_name": metric_row.metric_name,
            "value": metric_row.value,
            "unit": metric_row.unit,
            "labels": metric_row.labels or {},
        }

    # 3. Check DeploymentORM
    dep_stmt = select(DeploymentORM).where(DeploymentORM.deployment_id == evidence_id)
    dep_row = (await session.execute(dep_stmt)).scalar_one_or_none()
    if dep_row:
        return {
            "evidence_id": str(dep_row.deployment_id),
            "evidence_type": "deployment",
            "service": dep_row.service,
            "timestamp": dep_row.started_at.isoformat(),
            "completed_at": dep_row.completed_at.isoformat() if dep_row.completed_at else None,
            "version": dep_row.version,
            "commit_sha": dep_row.commit_sha,
            "status": dep_row.status,
        }

    # 4. Check TraceSpanORM
    trace_stmt = select(TraceSpanORM).where(TraceSpanORM.id == evidence_id)
    trace_row = (await session.execute(trace_stmt)).scalar_one_or_none()
    if trace_row:
        return {
            "evidence_id": str(trace_row.id),
            "evidence_type": "trace",
            "service": trace_row.service,
            "timestamp": trace_row.start_time.isoformat(),
            "operation": trace_row.operation,
            "duration_ms": trace_row.duration_ms,
            "status": trace_row.status,
            "trace_id": trace_row.trace_id,
            "attributes": trace_row.attributes or {},
        }

    # 5. Check AlertORM
    alert_stmt = select(AlertORM).where(AlertORM.id == evidence_id)
    alert_row = (await session.execute(alert_stmt)).scalar_one_or_none()
    if alert_row:
        return {
            "evidence_id": str(alert_row.id),
            "evidence_type": "alert",
            "service": alert_row.service,
            "timestamp": alert_row.timestamp.isoformat(),
            "severity": alert_row.severity,
            "description": alert_row.description,
            "alert_type": alert_row.alert_type,
        }

    # 6. Check DatabaseEventORM
    db_stmt = select(DatabaseEventORM).where(DatabaseEventORM.id == evidence_id)
    db_row = (await session.execute(db_stmt)).scalar_one_or_none()
    if db_row:
        return {
            "evidence_id": str(db_row.id),
            "evidence_type": "database",
            "service": db_row.service,
            "timestamp": db_row.timestamp.isoformat(),
            "database_name": db_row.database_name,
            "status": db_row.status,
            "latency_ms": db_row.latency_ms,
        }

    # 7. Check NormalizedEventORM (universal telemetry lookup)
    norm_stmt = select(NormalizedEventORM).where(NormalizedEventORM.id == evidence_id)
    norm_row = (await session.execute(norm_stmt)).scalar_one_or_none()
    if norm_row:
        src_val = norm_row.source.value if hasattr(norm_row.source, "value") else str(norm_row.source)
        sev_val = norm_row.severity.value if hasattr(norm_row.severity, "value") else str(norm_row.severity)
        return {
            "evidence_id": str(norm_row.id),
            "evidence_type": src_val,
            "service": norm_row.service,
            "timestamp": norm_row.timestamp.isoformat(),
            "severity": sev_val,
            "message": norm_row.attributes.get("message") if isinstance(norm_row.attributes, dict) else None,
            "description": (norm_row.attributes.get("description") or norm_row.attributes.get("diff_summary")) if isinstance(norm_row.attributes, dict) else None,
            "attributes": norm_row.attributes or {},
        }

    # 8. Check GitCommitORM
    commit_stmt = select(GitCommitORM).where(GitCommitORM.commit_sha == str(evidence_id))
    commit_row = (await session.execute(commit_stmt)).scalar_one_or_none()
    if commit_row:
        return {
            "evidence_id": commit_row.commit_sha,
            "evidence_type": "commit",
            "service": commit_row.repository,
            "timestamp": commit_row.timestamp.isoformat(),
            "author": commit_row.author,
            "repository": commit_row.repository,
            "description": commit_row.diff_summary,
            "files_changed": commit_row.files_changed or [],
            "symbols_changed": commit_row.symbols_changed or [],
        }

    raise HTTPException(status_code=404, detail="Evidence item not found")
