# CRITICAL ISOLATION ENFORCEMENT: This retrieval module queries ONLY investigator-facing tables.
# It must NEVER join or query the 'ground_truths' table.

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.conversions import orm_to_deployment, orm_to_git_commit
from app.db.models import DeploymentORM, GitCommitORM
from app.schemas.deployments import Deployment, GitCommit

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


async def get_changes_before(
    session: AsyncSession,
    incident_id: UUID,
    timestamp: datetime,
    lookback_minutes: int = 60,
    limit: int = DEFAULT_LIMIT,
) -> list[Deployment | GitCommit]:
    """Retrieves all code commits and service deployments occurring within a lookback window prior to a timestamp."""
    safe_limit = max(1, min(limit, MAX_LIMIT))
    window_start = timestamp - timedelta(minutes=lookback_minutes)

    changes: list[tuple[datetime, Deployment | GitCommit]] = []

    # 1. Query Deployments
    dep_stmt = (
        select(DeploymentORM)
        .where(
            DeploymentORM.incident_id == incident_id,
            DeploymentORM.started_at >= window_start,
            DeploymentORM.started_at <= timestamp,
        )
        .order_by(DeploymentORM.started_at.desc())
        .limit(safe_limit)
    )
    dep_rows = (await session.execute(dep_stmt)).scalars().all()
    for d in dep_rows:
        changes.append((d.started_at, orm_to_deployment(d)))

    # 2. Query Commits
    commit_stmt = (
        select(GitCommitORM)
        .where(
            GitCommitORM.incident_id == incident_id,
            GitCommitORM.timestamp >= window_start,
            GitCommitORM.timestamp <= timestamp,
        )
        .order_by(GitCommitORM.timestamp.desc())
        .limit(safe_limit)
    )
    commit_rows = (await session.execute(commit_stmt)).scalars().all()
    for c in commit_rows:
        changes.append((c.timestamp, orm_to_git_commit(c)))

    # Sort combined changes chronologically descending (most recent first)
    changes.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in changes[:safe_limit]]
