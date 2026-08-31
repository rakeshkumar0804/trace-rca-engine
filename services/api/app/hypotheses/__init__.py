# CRITICAL ISOLATION ENFORCEMENT: This hypotheses module operates ONLY on investigator-facing evidence.
# It must NEVER join or query the 'ground_truths' table.

from .candidate_generation import generate_candidate_hypotheses
from .scoring import (
    ScoringContext,
    calculate_causal_fit,
    calculate_change_proximity,
    calculate_contradiction_penalty,
    calculate_evidence_support,
    calculate_system_dependency_fit,
    calculate_temporal_fit,
    calculate_unexplained_symptoms_penalty,
    rank_hypotheses,
    score_hypothesis,
)

__all__ = [
    "generate_candidate_hypotheses",
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
