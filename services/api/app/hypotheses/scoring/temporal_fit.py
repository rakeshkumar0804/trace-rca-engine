# CRITICAL ISOLATION ENFORCEMENT: This scoring module operates ONLY on investigator-facing evidence.
# It must NEVER join or query the 'ground_truths' table.

from datetime import datetime, timezone
from app.schemas.events import NormalizedEvent
from app.schemas.hypotheses import Hypothesis


def calculate_temporal_fit(
    hypothesis: Hypothesis,
    candidate_cause_events: list[NormalizedEvent],
    symptom_onset_time: datetime,
) -> float:
    """Calculates temporal fit score in range [0.0, 20.0].
    
    Rewards hypotheses where candidate causal events occur immediately prior to or at symptom onset.
    Penalizes hypotheses where candidate cause occurs significantly after symptoms already began.
    """
    if not candidate_cause_events:
        # Default baseline when no specific candidate events are linked
        return 5.0

    # Ensure UTC timezone awareness
    if symptom_onset_time.tzinfo is None:
        symptom_onset_time = symptom_onset_time.replace(tzinfo=timezone.utc)

    # Find the earliest implicated causal event timestamp
    event_times = [
        e.timestamp if e.timestamp.tzinfo is not None else e.timestamp.replace(tzinfo=timezone.utc)
        for e in candidate_cause_events
    ]
    earliest_cause_time = min(event_times)

    # Delta in minutes: positive if cause preceded symptoms (cause <= onset)
    delta_seconds = (symptom_onset_time - earliest_cause_time).total_seconds()
    delta_minutes = delta_seconds / 60.0

    if delta_minutes < -5.0:
        # Cause occurred > 5 minutes AFTER symptoms started -> highly implausible causality
        return max(0.0, 5.0 + delta_minutes)  # decays to 0
    elif -5.0 <= delta_minutes < 0:
        # Cause occurred slightly after first anomalous detection (detection lag possible)
        return 10.0 + (delta_minutes * 1.5)
    elif 0.0 <= delta_minutes <= 15.0:
        # Cause occurred 0 to 15 minutes before symptoms -> optimal causal window
        return 20.0 - (delta_minutes * 0.4)  # 20.0 down to 14.0
    elif 15.0 < delta_minutes <= 60.0:
        # Cause occurred 15-60 minutes before symptoms
        return max(5.0, 14.0 - ((delta_minutes - 15.0) * 0.2))
    else:
        # Cause occurred hours before symptoms -> weak temporal link
        return 4.0
