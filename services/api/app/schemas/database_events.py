from datetime import datetime
from enum import Enum
from pydantic import BaseModel


class DatabaseEventStatus(str, Enum):
    """Execution status or performance health condition of a database query/event."""
    OK = "ok"
    SLOW = "slow"
    TIMEOUT = "timeout"
    ERROR = "error"


class DatabaseEvent(BaseModel):
    """Telemetry record capturing database engine state, active connections, locks, and query execution metrics."""
    timestamp: datetime
    database: str
    query_fingerprint: str
    duration_ms: float
    connections_active: int
    connections_max: int
    locks_held: int
    rows_affected: int
    status: DatabaseEventStatus
