from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field


class EventSource(str, Enum):
    """Source domain or subsystem generating an observable event."""
    LOG = "log"
    METRIC = "metric"
    TRACE = "trace"
    DEPLOYMENT = "deployment"
    COMMIT = "commit"
    DATABASE = "database"
    ALERT = "alert"


class EventSeverity(str, Enum):
    """Severity classification level for events and log entries."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class NormalizedEvent(BaseModel):
    """Normalized common event representation converted from disparate raw telemetry and lifecycle signals."""
    id: UUID
    timestamp: datetime
    source: EventSource
    entity: str
    event_type: str
    service: str | None = None
    severity: EventSeverity | None = None
    attributes: dict[str, str | int | float | bool]
    relationships: list[str] = Field(default_factory=list)


class LogEntry(BaseModel):
    """Raw application or system log message captured during runtime execution."""
    timestamp: datetime
    service: str
    severity: EventSeverity
    message: str
    trace_id: str | None = None
    request_id: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class MetricPoint(BaseModel):
    """Point-in-time quantitative measurement sampled from service or host telemetry."""
    timestamp: datetime
    service: str
    metric_name: str
    value: float
    unit: str
    labels: dict[str, str] = Field(default_factory=dict)


class TraceSpan(BaseModel):
    """Distributed tracing span representing an individual timed unit of execution within a distributed transaction."""
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    service: str
    operation: str
    start_time: datetime
    duration_ms: float
    status: Literal["ok", "error"]
    attributes: dict[str, str] = Field(default_factory=dict)
