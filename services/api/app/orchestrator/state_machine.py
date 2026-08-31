# CRITICAL ISOLATION ENFORCEMENT: This state machine operates ONLY on investigator-facing states.
# It must NEVER process or store 'ground_truths'.

from datetime import datetime, timezone
from app.schemas.investigations import (
    InvestigationState,
    InvestigationStep,
    InvestigationStepDetailValue,
)


# Explicitly permitted state transitions
VALID_TRANSITIONS: dict[InvestigationState, set[InvestigationState]] = {
    InvestigationState.INCIDENT_DETECTED: {
        InvestigationState.SCOPING,
        InvestigationState.FAILED,
    },
    InvestigationState.SCOPING: {
        InvestigationState.TIMELINE_BUILT,
        InvestigationState.FAILED,
    },
    InvestigationState.TIMELINE_BUILT: {
        InvestigationState.EVIDENCE_RETRIEVED,
        InvestigationState.FAILED,
    },
    InvestigationState.EVIDENCE_RETRIEVED: {
        InvestigationState.HYPOTHESES_GENERATED,
        InvestigationState.INCONCLUSIVE,
        InvestigationState.FAILED,
    },
    InvestigationState.HYPOTHESES_GENERATED: {
        InvestigationState.HYPOTHESES_RANKED,
        InvestigationState.INCONCLUSIVE,
        InvestigationState.FAILED,
    },
    InvestigationState.HYPOTHESES_RANKED: {
        InvestigationState.INVESTIGATING_HYPOTHESIS,
        InvestigationState.INCONCLUSIVE,
        InvestigationState.FAILED,
    },
    InvestigationState.INVESTIGATING_HYPOTHESIS: {
        InvestigationState.INVESTIGATING_HYPOTHESIS,  # Transition to next hypothesis in batch
        InvestigationState.RCA_GENERATED,
        InvestigationState.INCONCLUSIVE,
        InvestigationState.FAILED,
    },
    InvestigationState.RCA_GENERATED: set(),   # Terminal state
    InvestigationState.INCONCLUSIVE: set(),     # Terminal state
    InvestigationState.FAILED: set(),           # Terminal state
}


class InvalidStateTransitionError(ValueError):
    """Raised when an illegal state machine transition is attempted."""
    pass


class InvestigationStateMachine:
    """Manages explicit investigation lifecycle states and validates all step transitions."""

    def __init__(self, initial_state: InvestigationState = InvestigationState.INCIDENT_DETECTED):
        self._current_state = initial_state
        self._steps: list[InvestigationStep] = []
        self._step_counter = 0

    @property
    def current_state(self) -> InvestigationState:
        return self._current_state

    @property
    def steps(self) -> list[InvestigationStep]:
        return list(self._steps)

    def is_terminal(self) -> bool:
        return self._current_state in {
            InvestigationState.RCA_GENERATED,
            InvestigationState.INCONCLUSIVE,
            InvestigationState.FAILED,
        }

    def record_initial_step(
        self,
        summary: str,
        details: dict[str, InvestigationStepDetailValue] | None = None,
        timestamp: datetime | None = None,
    ) -> InvestigationStep:
        """Records the initial INCIDENT_DETECTED step."""
        if self._steps:
            raise RuntimeError("Initial step has already been recorded.")
        self._step_counter += 1
        now = timestamp or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        step = InvestigationStep(
            step_number=self._step_counter,
            state=self._current_state,
            timestamp=now,
            summary=summary,
            details=details or {},
        )
        self._steps.append(step)
        return step

    def transition_to(
        self,
        next_state: InvestigationState,
        summary: str,
        details: dict[str, InvestigationStepDetailValue] | None = None,
        timestamp: datetime | None = None,
    ) -> InvestigationStep:
        """Validates and applies a state transition, returning the created InvestigationStep."""
        allowed = VALID_TRANSITIONS.get(self._current_state, set())
        if next_state not in allowed:
            raise InvalidStateTransitionError(
                f"Invalid state transition: Cannot transition from '{self._current_state.value}' to '{next_state.value}'. "
                f"Allowed transitions: {[s.value for s in allowed]}"
            )

        self._current_state = next_state
        self._step_counter += 1
        now = timestamp or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        step = InvestigationStep(
            step_number=self._step_counter,
            state=next_state,
            timestamp=now,
            summary=summary,
            details=details or {},
        )
        self._steps.append(step)
        return step
