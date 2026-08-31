# CRITICAL ISOLATION ENFORCEMENT: This scoring module operates ONLY on investigator-facing evidence.
# It must NEVER join or query the 'ground_truths' table.

from .aggregate import ScoringContext, rank_hypotheses, score_hypothesis
from .causal_fit import calculate_causal_fit
from .change_proximity import calculate_change_proximity
from .contradiction_penalty import calculate_contradiction_penalty
from .evidence_support import calculate_evidence_support
from .system_dependency_fit import calculate_system_dependency_fit
from .temporal_fit import calculate_temporal_fit
from .unexplained_symptoms_penalty import calculate_unexplained_symptoms_penalty

__all__ = [
    "ScoringContext",
    "score_hypothesis",
    "rank_hypotheses",
    "calculate_temporal_fit",
    "calculate_causal_fit",
    "calculate_evidence_support",
    "calculate_system_dependency_fit",
    "calculate_change_proximity",
    "calculate_contradiction_penalty",
    "calculate_unexplained_symptoms_penalty",
]
