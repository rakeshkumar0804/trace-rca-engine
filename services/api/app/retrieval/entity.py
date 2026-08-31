# CRITICAL ISOLATION ENFORCEMENT: This retrieval module queries ONLY investigator-facing tables.
# It must NEVER join or query the 'ground_truths' table.

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.conversions import orm_to_normalized_event
from app.db.models import NormalizedEventORM
from app.schemas.events import NormalizedEvent

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


async def get_events_for_entity(
    session: AsyncSession,
    incident_id: UUID,
    entity: str,
    limit: int = DEFAULT_LIMIT,
) -> list[NormalizedEvent]:
    """Retrieves all normalized events associated with a specific service or entity name.
    
    Safe parameterized query searching both entity and service columns with strictly enforced result bounds.
    """
    safe_limit = max(1, min(limit, MAX_LIMIT))
    
    stmt = (
        select(NormalizedEventORM)
        .where(
            NormalizedEventORM.incident_id == incident_id,
            or_(
                NormalizedEventORM.entity == entity,
                NormalizedEventORM.service == entity,
            ),
        )
        .order_by(NormalizedEventORM.timestamp.asc())
        .limit(safe_limit)
    )
    
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [orm_to_normalized_event(r) for r in rows]
