from datetime import datetime
from enum import Enum
from uuid import UUID
from pydantic import BaseModel, Field


class InvestigationState(str, Enum):
    """Lifecycle states of the TRACE investigation orchestrator pipeline."""
    INCIDENT_DETECTED = "incident_detected"
    SCOPING = "scoping"
    TIMELINE_BUILT = "timeline_built"
    EVIDENCE_RETRIEVED = "evidence_retrieved"
    HYPOTHESES_GENERATED = "hypotheses_generated"
    HYPOTHESES_RANKED = "hypotheses_ranked"
    INVESTIGATING_HYPOTHESIS = "investigating_hypothesis"
    RCA_GENERATED = "rca_generated"
    INCONCLUSIVE = "inconclusive"
    FAILED = "failed"


InvestigationStepDetailPrimitive = str | int | float | bool
InvestigationStepDetailDict = dict[str, InvestigationStepDetailPrimitive]

InvestigationStepDetailNested = (
    InvestigationStepDetailPrimitive
    | list[str]
    | list[InvestigationStepDetailDict]
)

InvestigationStepDetailValue = (
    InvestigationStepDetailPrimitive
    | list[str]
    | list[int]
    | list[float]
    | InvestigationStepDetailDict
    | list[dict[str, InvestigationStepDetailNested]]
)


class InvestigationStep(BaseModel):
    """An immutable, logged state transition step within an investigation."""
    step_number: int
    state: InvestigationState
    timestamp: datetime
    summary: str  # Short human-readable line, e.g. "Hypothesis H1 strengthened"
    details: dict[str, InvestigationStepDetailValue] = Field(default_factory=dict)  # Strictly typed step metadata


class Investigation(BaseModel):
    """Complete orchestrated investigation run containing lifecycle steps and final RCA result."""
    investigation_id: UUID
    incident_id: UUID
    steps: list[InvestigationStep] = Field(default_factory=list)
    final_state: InvestigationState
    leading_hypothesis_id: UUID | None = None
    confidence: float | None = None
    started_at: datetime
    completed_at: datetime | None = None
    rca_narrative: str | None = None
