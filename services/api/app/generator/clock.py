from datetime import datetime, timedelta, timezone
from random import Random


def get_rng(seed_or_rng: int | Random) -> Random:
    """Returns a Random instance given either an integer seed or an existing Random instance."""
    if isinstance(seed_or_rng, Random):
        return seed_or_rng
    return Random(seed_or_rng)


def time_window(
    start: datetime,
    duration_minutes: int,
    seed: int | Random,
    interval_seconds: float = 10.0,
    jitter_ratio: float = 0.2,
) -> list[datetime]:
    """Generates realistic non-uniform event timestamps with deterministic jitter within a time window.
    
    Args:
        start: Starting datetime boundary.
        duration_minutes: Length of the time window in minutes.
        seed: Random seed or Random instance for deterministic generation.
        interval_seconds: Average step size between successive timestamps.
        jitter_ratio: Maximum jitter displacement fraction around interval_seconds.
        
    Returns:
        A strictly ascending list of datetime timestamps spanning the duration.
    """
    rng = get_rng(seed)
    end = start + timedelta(minutes=duration_minutes)
    
    # Ensure UTC timezone awareness
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
        end = end.replace(tzinfo=timezone.utc)
        
    timestamps: list[datetime] = []
    current_time = start
    
    while current_time < end:
        timestamps.append(current_time)
        # Jitter delta: e.g. interval 10s with 0.2 ratio -> random in [8.0s, 12.0s]
        jitter_delta = interval_seconds * (1.0 + rng.uniform(-jitter_ratio, jitter_ratio))
        current_time += timedelta(seconds=max(0.1, jitter_delta))
        
    return timestamps
