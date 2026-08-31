# CRITICAL ISOLATION ENFORCEMENT: This retrieval module queries ONLY investigator-facing tables.
# It must NEVER join or query the 'ground_truths' table.

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.conversions import orm_to_normalized_event
from app.db.models import NormalizedEventORM
from app.generator.config import SERVICE_TOPOLOGY
from app.schemas.events import NormalizedEvent

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


async def get_events_for_dependencies(
    session: AsyncSession,
    incident_id: UUID,
    service_name: str,
    limit: int = DEFAULT_LIMIT,
) -> list[NormalizedEvent]:
    """Retrieves normalized events from services directly connected to service_name in the dependency graph.
    
    Includes both downstream services depended on by service_name and upstream callers that depend on service_name.
    """
    safe_limit = max(1, min(limit, MAX_LIMIT))

    # Identify upstream and downstream connected entities
    related_services: set[str] = set()
    for dep in SERVICE_TOPOLOGY:
        if dep.from_service == service_name:
            related_services.add(dep.to_service)
        elif dep.to_service == service_name:
            related_services.add(dep.from_service)

    if not related_services:
        return []

    stmt = (
        select(NormalizedEventORM)
        .where(
            NormalizedEventORM.incident_id == incident_id,
            or_(
                NormalizedEventORM.entity.in_(related_services),
                NormalizedEventORM.service.in_(related_services),
            ),
        )
        .order_by(NormalizedEventORM.timestamp.asc())
        .limit(safe_limit)
    )

    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [orm_to_normalized_event(r) for r in rows]
