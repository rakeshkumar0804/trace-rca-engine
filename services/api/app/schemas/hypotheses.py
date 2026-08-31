from enum import Enum
from uuid import UUID
from pydantic import BaseModel, Field

from .events import EventSource


class HypothesisStatus(str, Enum):
    """Lifecycle and confidence state of an incident root-cause hypothesis."""
    CANDIDATE = "candidate"
    INVESTIGATING = "investigating"
    SUPPORTED = "supported"
    WEAK = "weak"
    REJECTED = "rejected"
    CONFIRMED = "confirmed"


class EvidenceRef(BaseModel):
    """Pointer to a specific piece of evidence — never inline evidence content, always a reference."""
    evidence_type: EventSource
    evidence_id: UUID
    relevance_note: str


class HypothesisScore(BaseModel):
    """Explicit scoring breakdown — never a single opaque LLM number."""
    temporal_fit: float
    causal_fit: float
    evidence_support: float
    system_dependency_fit: float
    change_proximity: float
    contradictory_evidence_penalty: float
    unexplained_symptoms_penalty: float
    final_score: float


class Hypothesis(BaseModel):
    """Root-cause hypothesis generated during incident investigation with deterministic breakdown scoring and evidence links."""
    id: UUID
    incident_id: UUID
    title: str
    description: str
    status: HypothesisStatus
    score: HypothesisScore
    supporting_evidence: list[EvidenceRef] = Field(default_factory=list)
    contradicting_evidence: list[EvidenceRef] = Field(default_factory=list)
