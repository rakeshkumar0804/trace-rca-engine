from datetime import datetime, timezone
from random import Random
from typing import Any

from app.schemas.database_events import DatabaseEvent
from app.schemas.deployments import Deployment, GitCommit
from app.schemas.events import LogEntry, MetricPoint, TraceSpan

from .clock import time_window
from .commits_generator import generate_healthy_commits
from .config import SERVICE_CONFIGS
from .database_generator import generate_healthy_database_events
from .deployments_generator import generate_healthy_deployments
from .logs_generator import generate_healthy_logs
from .metrics_generator import generate_healthy_metrics
from .traces_generator import generate_healthy_traces


def generate_healthy_environment(
    seed: int,
    start: datetime,
    duration_minutes: int = 15,
) -> dict[str, list[Any]]:
    """Orchestrates all generators for a healthy operating window across all 7 services.
    
    Returns a deterministic dictionary containing validated Pydantic model lists:
    {
        "logs": list[LogEntry],
        "metrics": list[MetricPoint],
        "traces": list[TraceSpan],
        "deployments": list[Deployment],
        "commits": list[GitCommit],
        "database_events": list[DatabaseEvent],
    }
    """
    rng = Random(seed)
    
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
        
    services = list(SERVICE_CONFIGS.keys())
    
    # 1. Generate non-uniform timestamps across time window
    # Tick every ~10 seconds
    ticks = time_window(start=start, duration_minutes=duration_minutes, seed=rng, interval_seconds=10.0)
    
    # 2. Logs for all services
    all_logs: list[LogEntry] = []
    for service in services:
        all_logs.extend(generate_healthy_logs(service, ticks, rng))
    # Sort logs chronologically
    all_logs.sort(key=lambda x: x.timestamp)
    
    # 3. Metrics for all services
    all_metrics: list[MetricPoint] = []
    for service in services:
        all_metrics.extend(generate_healthy_metrics(service, ticks, rng))
    all_metrics.sort(key=lambda x: x.timestamp)
    
    # 4. Traces across topology
    all_traces: list[TraceSpan] = generate_healthy_traces(ticks, rng, sample_every_n=3)
    all_traces.sort(key=lambda x: x.start_time)
    
    # 5. Git Commits and Deployments
    commits = generate_healthy_commits(services, start, rng, count=3)
    deployments = generate_healthy_deployments(commits, rng)
    commits.sort(key=lambda x: x.timestamp)
    deployments.sort(key=lambda x: x.started_at)
    
    # 6. Database events for DB-owning services
    all_db_events: list[DatabaseEvent] = []
    for service in services:
        all_db_events.extend(generate_healthy_database_events(service, ticks, rng))
    all_db_events.sort(key=lambda x: x.timestamp)
    
    return {
        "logs": all_logs,
        "metrics": all_metrics,
        "traces": all_traces,
        "deployments": deployments,
        "commits": commits,
        "database_events": all_db_events,
        "alerts": [],
    }
