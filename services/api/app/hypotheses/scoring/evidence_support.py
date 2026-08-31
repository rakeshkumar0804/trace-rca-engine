# CRITICAL ISOLATION ENFORCEMENT: This scoring module operates ONLY on investigator-facing evidence.
# It must NEVER join or query the 'ground_truths' table.

from typing import Union
from app.schemas.events import EventSource, NormalizedEvent
from app.schemas.hypotheses import EvidenceRef, Hypothesis


def calculate_evidence_support(
    hypothesis: Hypothesis,
    supporting_evidence: list[Union[NormalizedEvent, EvidenceRef]],
) -> float:
    """Calculates evidence support score in range [0.0, 20.0].
    
    Evaluates both the quantity and multi-source diversity of evidence corroborating the hypothesis.
    Corroboration across independent telemetries (e.g. Log + Metric + DB + Deployment) receives a high multiplier.
    """
    if not supporting_evidence:
        return 0.0

    distinct_sources: set[EventSource] = set()
    total_count = len(supporting_evidence)

    for item in supporting_evidence:
        if isinstance(item, NormalizedEvent):
            distinct_sources.add(item.source)
        elif isinstance(item, EvidenceRef):
            distinct_sources.add(item.evidence_type)

    diversity_count = len(distinct_sources)

    # Base score derived from evidence volume (capped at 8.0)
    # 1 item = 3.0, 3 items = 6.0, 5+ items = 8.0
    volume_score = min(8.0, 2.0 + (total_count * 1.2))

    # Diversity score (up to 12.0)
    # 1 source = 3.0, 2 sources = 6.0, 3 sources = 9.0, 4+ sources = 12.0
    diversity_score = min(12.0, diversity_count * 3.0)

    total_support = volume_score + diversity_score
    return max(0.0, min(20.0, round(total_support, 2)))
