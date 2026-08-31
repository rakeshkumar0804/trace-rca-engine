from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.conversions import orm_to_normalized_event
from app.db.models import IncidentORM, NormalizedEventORM
from app.schemas.events import EventSource, NormalizedEvent
from app.schemas.timeline import Timeline, TimelineEventCluster


def _detect_clusters(
    events: list[NormalizedEvent],
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
        current_cluster_events: list[NormalizedEvent] = [events[i]]
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
            source_names = ", ".join(sorted([s.value for s in sources]))
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
) -> Timeline:
    """Builds a complete, chronologically partitioned, cluster-annotated incident Timeline.
    
    1. Fetches incident metadata boundaries.
    2. Retrieves all normalized events in chronological order.
    3. Partitions events into pre-incident, during-incident, and post-incident phases.
    4. Detects multi-source temporal correlation clusters.
    """
    # 1. Fetch Incident boundary metadata
    inc_stmt = select(IncidentORM).where(IncidentORM.incident_id == incident_id)
    inc_row = (await session.execute(inc_stmt)).scalar_one_or_none()

    if inc_row is None:
        raise ValueError(f"Incident with ID {incident_id} not found.")

    incident_start = inc_row.start_time if inc_row.start_time.tzinfo is not None else inc_row.start_time.replace(tzinfo=timezone.utc)
    incident_end = inc_row.end_time if (inc_row.end_time is None or inc_row.end_time.tzinfo is not None) else inc_row.end_time.replace(tzinfo=timezone.utc)

    # 2. Fetch all normalized events for this incident
    query = select(NormalizedEventORM).where(NormalizedEventORM.incident_id == incident_id)
    if window_start is not None:
        query = query.where(NormalizedEventORM.timestamp >= window_start)
    if window_end is not None:
        query = query.where(NormalizedEventORM.timestamp <= window_end)

    query = query.order_by(NormalizedEventORM.timestamp.asc())
    rows = (await session.execute(query)).scalars().all()
    events = [orm_to_normalized_event(r) for r in rows]

    # 3. Partition into phases
    pre_events: list[NormalizedEvent] = []
    during_events: list[NormalizedEvent] = []
    post_events: list[NormalizedEvent] = []

    for evt in events:
        if evt.timestamp < incident_start:
            pre_events.append(evt)
        elif incident_end is not None and evt.timestamp > incident_end:
            post_events.append(evt)
        else:
            during_events.append(evt)

    # 4. Detect temporal correlation clusters
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
