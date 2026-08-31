from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field

from .events import EventSource, NormalizedEvent


class TimelineEventCluster(BaseModel):
    """A temporal cluster of correlated events from multiple distinct sources occurring within a tight time window."""
    cluster_id: str
    start_time: datetime
    end_time: datetime
    event_ids: list[UUID] = Field(default_factory=list)
    involved_sources: list[EventSource] = Field(default_factory=list)
    summary: str


class Timeline(BaseModel):
    """Chronologically ordered incident timeline partitioned into pre, during, and post phases with annotated clusters."""
    incident_id: UUID
    start_time: datetime
    end_time: datetime | None = None
    events: list[NormalizedEvent] = Field(default_factory=list)
    pre_incident_events: list[NormalizedEvent] = Field(default_factory=list)
    during_incident_events: list[NormalizedEvent] = Field(default_factory=list)
    post_incident_events: list[NormalizedEvent] = Field(default_factory=list)
    clusters: list[TimelineEventCluster] = Field(default_factory=list)
