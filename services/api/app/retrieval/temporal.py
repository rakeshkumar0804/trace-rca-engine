# CRITICAL ISOLATION ENFORCEMENT: This retrieval module queries ONLY investigator-facing tables.
# It must NEVER join or query the 'ground_truths' table.

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.conversions import orm_to_normalized_event
from app.db.models import NormalizedEventORM
from app.schemas.events import NormalizedEvent

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


async def get_events_in_window(
    session: AsyncSession,
    incident_id: UUID,
    start: datetime,
    end: datetime,
    limit: int = DEFAULT_LIMIT,
) -> list[NormalizedEvent]:
    """Retrieves all normalized events occurring within a specified time window for an incident.
    
    Safe parameterized query with strictly enforced result bounds.
    """
    safe_limit = max(1, min(limit, MAX_LIMIT))
    
    stmt = (
        select(NormalizedEventORM)
        .where(
            NormalizedEventORM.incident_id == incident_id,
            NormalizedEventORM.timestamp >= start,
            NormalizedEventORM.timestamp <= end,
        )
        .order_by(NormalizedEventORM.timestamp.asc())
        .limit(safe_limit)
    )
    
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [orm_to_normalized_event(r) for r in rows]
