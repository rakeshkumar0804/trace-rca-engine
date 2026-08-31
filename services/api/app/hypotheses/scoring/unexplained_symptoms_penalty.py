# CRITICAL ISOLATION ENFORCEMENT: This scoring module operates ONLY on investigator-facing evidence.
# It must NEVER join or query the 'ground_truths' table.

from app.schemas.hypotheses import Hypothesis


def calculate_unexplained_symptoms_penalty(
    hypothesis: Hypothesis,
    all_observed_symptoms: list[str],
    symptoms_explained: list[str] | None = None,
) -> float:
    """Calculates unexplained symptoms penalty in range [0.0, 20.0].
    
    Penalizes hypotheses that fail to account for a substantial portion of the symptoms
    observed during the incident.
    """
    if not all_observed_symptoms:
        return 0.0

    total_symptoms = len(all_observed_symptoms)
    
    # If explicitly provided explained symptoms
    if symptoms_explained is not None:
        explained_count = len([s for s in symptoms_explained if s in all_observed_symptoms])
    else:
        # Heuristic matching: check which symptoms are addressed in the hypothesis description / title
        text = f"{hypothesis.title} {hypothesis.description}".lower()
        explained_count = 0
        for symptom in all_observed_symptoms:
            symptom_tokens = [w.lower() for w in symptom.split("_") if len(w) > 2]
            if any(tok in text for tok in symptom_tokens):
                explained_count += 1

    unexplained_fraction = max(0.0, 1.0 - (explained_count / total_symptoms))
    # Penalty scales from 0.0 (all explained) up to 20.0 (none explained)
    penalty = 20.0 * unexplained_fraction
    return round(penalty, 2)
