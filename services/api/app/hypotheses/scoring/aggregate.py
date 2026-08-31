# CRITICAL ISOLATION ENFORCEMENT: This scoring module operates ONLY on investigator-facing evidence.
# It must NEVER join or query the 'ground_truths' table.

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from app.schemas.deployments import Deployment, GitCommit
from app.schemas.events import NormalizedEvent
from app.schemas.hypotheses import Hypothesis, HypothesisScore, HypothesisStatus
from app.schemas.services import ServiceDependency

from .causal_fit import calculate_causal_fit
from .change_proximity import calculate_change_proximity
from .contradiction_penalty import calculate_contradiction_penalty
from .evidence_support import calculate_evidence_support
from .system_dependency_fit import calculate_system_dependency_fit
from .temporal_fit import calculate_temporal_fit
from .unexplained_symptoms_penalty import calculate_unexplained_symptoms_penalty


@dataclass
class ScoringContext:
    """Investigator-facing incident context required for deterministic hypothesis evaluation."""
    symptom_onset_time: datetime
    service_dependencies: list[ServiceDependency] = field(default_factory=list)
    affected_services: list[str] = field(default_factory=list)
    all_observed_symptoms: list[str] = field(default_factory=list)
    deployments: list[Deployment] = field(default_factory=list)
    commits: list[GitCommit] = field(default_factory=list)
    supporting_events_map: dict[UUID, list[NormalizedEvent]] = field(default_factory=dict)
    contradicting_events_map: dict[UUID, list[NormalizedEvent]] = field(default_factory=dict)
    symptoms_explained_map: dict[UUID, list[str]] = field(default_factory=dict)


def score_hypothesis(
    hypothesis: Hypothesis,
    context: ScoringContext,
) -> HypothesisScore:
    """Computes all 7 deterministic sub-scores and aggregates them into a normalized 0-100 final_score.
    
    Formula:
    final_score = temporal_fit + causal_fit + evidence_support + system_dependency_fit
                  + change_proximity - contradictory_evidence_penalty - unexplained_symptoms_penalty
    """
    # 1. Supporting and contradicting events for this hypothesis
    supporting_events = context.supporting_events_map.get(hypothesis.id, [])
    contradicting_events = context.contradicting_events_map.get(hypothesis.id, [])

    # If events aren't in map, fallback to hypothesis.supporting_evidence EvidenceRefs
    supp_items = supporting_events if supporting_events else hypothesis.supporting_evidence
    contra_items = contradicting_events if contradicting_events else hypothesis.contradicting_evidence

    # 2. Compute 7 pure sub-scores
    temporal = calculate_temporal_fit(
        hypothesis=hypothesis,
        candidate_cause_events=supporting_events,
        symptom_onset_time=context.symptom_onset_time,
    )

    causal = calculate_causal_fit(
        hypothesis=hypothesis,
        service_dependencies=context.service_dependencies,
        affected_services=context.affected_services,
    )

    support = calculate_evidence_support(
        hypothesis=hypothesis,
        supporting_evidence=supp_items,
    )

    sys_dep = calculate_system_dependency_fit(
        hypothesis=hypothesis,
        service_dependencies=context.service_dependencies,
        affected_services=context.affected_services,
    )

    change_prox = calculate_change_proximity(
        hypothesis=hypothesis,
        deployments=context.deployments,
        commits=context.commits,
        symptom_onset_time=context.symptom_onset_time,
    )

    contra_penalty = calculate_contradiction_penalty(
        hypothesis=hypothesis,
        contradicting_evidence=contra_items,
    )

    explained_symptoms = context.symptoms_explained_map.get(hypothesis.id)
    unexplained_penalty = calculate_unexplained_symptoms_penalty(
        hypothesis=hypothesis,
        all_observed_symptoms=context.all_observed_symptoms,
        symptoms_explained=explained_symptoms,
    )

    # 3. Aggregate formula from doc Section 14
    raw_score = (
        temporal
        + causal
        + support
        + sys_dep
        + change_prox
        - contra_penalty
        - unexplained_penalty
    )

    normalized_final = max(0.0, min(100.0, round(raw_score, 2)))

    return HypothesisScore(
        temporal_fit=temporal,
        causal_fit=causal,
        evidence_support=support,
        system_dependency_fit=sys_dep,
        change_proximity=change_prox,
        contradictory_evidence_penalty=contra_penalty,
        unexplained_symptoms_penalty=unexplained_penalty,
        final_score=normalized_final,
    )


def rank_hypotheses(hypotheses: list[Hypothesis]) -> list[Hypothesis]:
    """Ranks hypotheses in descending order of final_score.
    
    Promotes the top-scoring hypothesis to INVESTIGATING status;
    other candidate hypotheses remain in CANDIDATE status.
    """
    if not hypotheses:
        return []

    sorted_list = sorted(hypotheses, key=lambda h: h.score.final_score, reverse=True)

    ranked_hypotheses: list[Hypothesis] = []
    for idx, hyp in enumerate(sorted_list):
        new_status = HypothesisStatus.INVESTIGATING if idx == 0 else HypothesisStatus.CANDIDATE
        # Create updated copy with appropriate status
        updated_hyp = hyp.model_copy(update={"status": new_status})
        ranked_hypotheses.append(updated_hyp)

    return ranked_hypotheses
