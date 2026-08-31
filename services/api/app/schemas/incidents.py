from datetime import datetime
from enum import Enum
from uuid import UUID
from pydantic import BaseModel, Field


class IncidentDifficulty(str, Enum):
    """Complexity classification level for benchmarking incident scenarios."""
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class IncidentSeverity(str, Enum):
    """Business impact and urgency classification level of an incident."""
    SEV1 = "sev1"
    SEV2 = "sev2"
    SEV3 = "sev3"


class CausalChainLink(BaseModel):
    """One edge in the ground-truth causal chain. NOT shown to the investigator."""
    from_node: str
    to_node: str
    relationship: str
    explanation: str


class GroundTruth(BaseModel):
    """Hidden from TRACE's investigation input. Used only for benchmark scoring."""
    root_cause: str
    causal_chain: list[CausalChainLink]
    responsible_commit_sha: str | None = None
    responsible_deployment_id: UUID | None = None


class Incident(BaseModel):
    """Production incident case record containing timeline boundaries, symptoms, and ground-truth validation data."""
    incident_id: UUID
    incident_type: str
    start_time: datetime
    end_time: datetime | None = None
    affected_services: list[str]
    expected_symptoms: list[str]
    distractor_event_ids: list[UUID] = Field(default_factory=list)
    difficulty: IncidentDifficulty
    severity: IncidentSeverity
    ground_truth: GroundTruth
