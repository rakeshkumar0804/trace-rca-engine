from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID
from dataclasses import dataclass

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.conversions import orm_to_normalized_event
from app.db.models import IncidentORM, NormalizedEventORM
from app.schemas.events import EventSource, NormalizedEvent
from app.schemas.timeline import Timeline, TimelineEventCluster


@dataclass
class _LightweightEvent:
    id: UUID
    timestamp: datetime
    source: EventSource


def _detect_clusters(
    events: list[Any],
    cluster_window_seconds: float = 60.0,
) -> list[TimelineEventCluster]:
    """Detects multi-source correlated event clusters within a sliding time window."""
    if not events:
        return []

    clusters: list[TimelineEventCluster] = []
    window_delta = timedelta(seconds=cluster_window_seconds)

    i = 0
    cluster_idx = 1

    while i < len(events):
        current_cluster_events: list[Any] = [events[i]]
        sources: set[EventSource] = {events[i].source}
        window_end_limit = events[i].timestamp + window_delta

        j = i + 1
        while j < len(events) and events[j].timestamp <= window_end_limit:
            current_cluster_events.append(events[j])
            sources.add(events[j].source)
            # Expand window slightly if continuous activity
            window_end_limit = max(window_end_limit, events[j].timestamp + timedelta(seconds=15.0))
            j += 1

        # A cluster is significant if it involves at least 2 distinct event sources
        if len(sources) >= 2 and len(current_cluster_events) >= 3:
            start_ts = current_cluster_events[0].timestamp
            end_ts = current_cluster_events[-1].timestamp
            source_names = ", ".join(sorted([s.value if hasattr(s, 'value') else str(s) for s in sources]))
            summary = (
                f"Cluster {cluster_idx}: {len(current_cluster_events)} correlated events "
                f"across sources [{source_names}] within {(end_ts - start_ts).total_seconds():.1f}s"
            )
            clusters.append(
                TimelineEventCluster(
                    cluster_id=f"cluster-{cluster_idx:03d}",
                    start_time=start_ts,
                    end_time=end_ts,
                    event_ids=[e.id for e in current_cluster_events],
                    involved_sources=list(sources),
                    summary=summary,
                )
            )
            cluster_idx += 1
            i = j  # Advance past this cluster
        else:
            i += 1

    return clusters


async def build_timeline(
    session: AsyncSession,
    incident_id: UUID,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    cluster_window_seconds: float = 60.0,
    include_raw_events: bool = False,
) -> Timeline:
    """Builds a memory-optimized chronologically partitioned, cluster-annotated incident Timeline.
    
    Queries lightweight (id, timestamp, source) tuples to detect clusters with minimal RAM overhead.
    """
    # 1. Fetch Incident boundary metadata
    inc_stmt = select(IncidentORM).where(IncidentORM.incident_id == incident_id)
    inc_row = (await session.execute(inc_stmt)).scalar_one_or_none()

    if inc_row is None:
        raise ValueError(f"Incident with ID {incident_id} not found.")

    incident_start = inc_row.start_time if inc_row.start_time.tzinfo is not None else inc_row.start_time.replace(tzinfo=timezone.utc)
    incident_end = inc_row.end_time if (inc_row.end_time is None or inc_row.end_time.tzinfo is not None) else inc_row.end_time.replace(tzinfo=timezone.utc)

    # 2. Fetch lightweight projection (event_id, timestamp, source)
    if include_raw_events:
        query = select(NormalizedEventORM).where(NormalizedEventORM.incident_id == incident_id)
        if window_start is not None:
            query = query.where(NormalizedEventORM.timestamp >= window_start)
        if window_end is not None:
            query = query.where(NormalizedEventORM.timestamp <= window_end)
        query = query.order_by(NormalizedEventORM.timestamp.asc())
        rows = (await session.execute(query)).scalars().all()
        events = [orm_to_normalized_event(r) for r in rows]
        
        pre_events = [e for e in events if e.timestamp < incident_start]
        post_events = [e for e in events if incident_end is not None and e.timestamp > incident_end]
        during_events = [e for e in events if (incident_start <= e.timestamp and (incident_end is None or e.timestamp <= incident_end))]
        clusters = _detect_clusters(events, cluster_window_seconds=cluster_window_seconds)

        return Timeline(
            incident_id=incident_id,
            start_time=incident_start,
            end_time=incident_end,
            events=events,
            pre_incident_events=pre_events,
            during_incident_events=during_events,
            post_incident_events=post_events,
            clusters=clusters,
        )
    else:
        # Lightweight tuple query for zero memory bloat
        query = select(
            NormalizedEventORM.id,
            NormalizedEventORM.timestamp,
            NormalizedEventORM.source,
            NormalizedEventORM.entity,
            NormalizedEventORM.event_type,
        ).where(NormalizedEventORM.incident_id == incident_id)
        
        if window_start is not None:
            query = query.where(NormalizedEventORM.timestamp >= window_start)
        if window_end is not None:
            query = query.where(NormalizedEventORM.timestamp <= window_end)
        query = query.order_by(NormalizedEventORM.timestamp.asc())
        
        results = (await session.execute(query)).all()
        events = [
            NormalizedEvent(
                id=r[0],
                timestamp=r[1] if r[1].tzinfo is not None else r[1].replace(tzinfo=timezone.utc),
                source=EventSource(r[2]) if hasattr(EventSource, '__members__') and r[2] in EventSource._value2member_map_ else EventSource.LOG,
                entity=r[3] or "unknown",
                event_type=r[4] or "event",
                attributes={},
                relationships=[],
            )
            for r in results
        ]
        
        pre_events = [e for e in events if e.timestamp < incident_start]
        post_events = [e for e in events if incident_end is not None and e.timestamp > incident_end]
        during_events = [e for e in events if (incident_start <= e.timestamp and (incident_end is None or e.timestamp <= incident_end))]
        clusters = _detect_clusters(events, cluster_window_seconds=cluster_window_seconds)

        return Timeline(
            incident_id=incident_id,
            start_time=incident_start,
            end_time=incident_end,
            events=events,
            pre_incident_events=pre_events,
            during_incident_events=during_events,
            post_incident_events=post_events,
            clusters=clusters,
        )
