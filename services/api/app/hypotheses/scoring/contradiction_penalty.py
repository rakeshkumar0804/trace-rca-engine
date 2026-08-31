# CRITICAL ISOLATION ENFORCEMENT: This scoring module operates ONLY on investigator-facing evidence.
# It must NEVER join or query the 'ground_truths' table.

from typing import Union
from app.schemas.events import NormalizedEvent
from app.schemas.hypotheses import EvidenceRef, Hypothesis


def calculate_contradiction_penalty(
    hypothesis: Hypothesis,
    contradicting_evidence: list[Union[NormalizedEvent, EvidenceRef]],
) -> float:
    """Calculates contradictory evidence penalty in range [0.0, 20.0].
    
    Evaluates evidence that directly conflicts with the hypothesis premise
    (e.g. implicated service metrics showing 100% health, or flat traffic during an alleged spike).
    """
    if not contradicting_evidence:
        return 0.0

    count = len(contradicting_evidence)
    # Each distinct piece of conflicting evidence imposes significant penalty
    # 1 contradiction = 6.0, 2 contradictions = 12.0, 3+ = 18.0 - 20.0
    penalty = min(20.0, count * 6.0)
    return round(penalty, 2)
