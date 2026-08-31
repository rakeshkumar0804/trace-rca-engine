# CRITICAL ISOLATION ENFORCEMENT: This scoring module operates ONLY on investigator-facing evidence.
# It must NEVER join or query the 'ground_truths' table.

from datetime import datetime, timezone
import math
from app.schemas.deployments import Deployment, GitCommit
from app.schemas.hypotheses import Hypothesis


def calculate_change_proximity(
    hypothesis: Hypothesis,
    deployments: list[Deployment],
    commits: list[GitCommit],
    symptom_onset_time: datetime,
) -> float:
    """Calculates change proximity score in range [0.0, 20.0].
    
    Evaluates whether a software deployment or commit occurred close to symptom onset.
    Decays smoothly with time delta and rewards matching service targets.
    """
    text = f"{hypothesis.title} {hypothesis.description}".lower()
    is_change_hypothesis = any(w in text for w in ["deploy", "deployment", "commit", "release", "version", "patch", "rollout"])

    if not is_change_hypothesis and not deployments and not commits:
        return 0.0

    if symptom_onset_time.tzinfo is None:
        symptom_onset_time = symptom_onset_time.replace(tzinfo=timezone.utc)

    # Filter relevant deployments occurring before or very near symptom onset
    best_deployment_score = 0.0
    for dep in deployments:
        dep_time = dep.started_at if dep.started_at.tzinfo is not None else dep.started_at.replace(tzinfo=timezone.utc)
        delta_seconds = (symptom_onset_time - dep_time).total_seconds()
        delta_minutes = delta_seconds / 60.0

        if delta_minutes >= -2.0:  # Allow small clock skew / onset estimation buffer
            # Exponential decay: 20 at 0 min, 15 at 10 min, 7.3 at 30 min
            service_bonus = 1.2 if (dep.service.lower() in text) else 0.8
            proximity = 18.0 * math.exp(-max(0.0, delta_minutes) / 20.0) * service_bonus
            best_deployment_score = max(best_deployment_score, proximity)

    # Filter relevant commits
    best_commit_score = 0.0
    for c in commits:
        c_time = c.timestamp if c.timestamp.tzinfo is not None else c.timestamp.replace(tzinfo=timezone.utc)
        delta_seconds = (symptom_onset_time - c_time).total_seconds()
        delta_minutes = delta_seconds / 60.0

        if delta_minutes >= -2.0:
            repo_name = c.repository.split("/")[-1].lower()
            service_bonus = 1.2 if (repo_name in text) else 0.8
            proximity = 15.0 * math.exp(-max(0.0, delta_minutes) / 25.0) * service_bonus
            best_commit_score = max(best_commit_score, proximity)

    max_score = max(best_deployment_score, best_commit_score)

    if not is_change_hypothesis:
        # Non-change hypothesis (e.g. organic traffic surge) gets low baseline
        return max(0.0, min(6.0, round(max_score * 0.3, 2)))

    return max(0.0, min(20.0, round(max_score, 2)))
