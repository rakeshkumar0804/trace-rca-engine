from datetime import datetime
from enum import Enum
from pydantic import BaseModel


class AlertSeverity(str, Enum):
    """Urgency level classification for monitoring alerts."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Alert(BaseModel):
    """Triggered monitoring notification or threshold violation from alerting systems."""
    timestamp: datetime
    alert_type: str
    service: str
    severity: AlertSeverity
    description: str
