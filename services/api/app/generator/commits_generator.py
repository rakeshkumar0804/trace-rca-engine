from datetime import datetime, timedelta
from random import Random
import uuid

from app.schemas.deployments import GitCommit

NORMAL_COMMIT_TEMPLATES: list[dict[str, str | list[str]]] = [
    {
        "diff_summary": "Add exponential backoff retry logic to external gateway client",
        "files_changed": ["src/clients/gateway.py", "tests/test_gateway.py"],
        "symbols_changed": ["gateway.send_with_retry", "gateway.calculate_backoff"],
    },
    {
        "diff_summary": "Update dependencies to latest security patches and bump base image",
        "files_changed": ["requirements.txt", "Dockerfile", "pyproject.toml"],
        "symbols_changed": [],
    },
    {
        "diff_summary": "Add detailed prometheus latency histograms for core API routes",
        "files_changed": ["src/metrics/instrumentation.py", "src/middleware/timing.py"],
        "symbols_changed": ["timing.record_route_latency", "instrumentation.setup_metrics"],
    },
    {
        "diff_summary": "Optimize database index query filters for user order lookup",
        "files_changed": ["migrations/0042_add_user_idx.sql", "src/db/queries.py"],
        "symbols_changed": ["queries.get_orders_by_user"],
    },
    {
        "diff_summary": "Refactor session token caching layer to reduce redis call volume",
        "files_changed": ["src/auth/token_cache.py", "src/auth/session.py"],
        "symbols_changed": ["token_cache.get_or_set", "session.validate_token"],
    },
    {
        "diff_summary": "Improve log sanitization to scrub sensitive customer PII fields",
        "files_changed": ["src/logging/sanitizer.py", "src/middleware/logging.py"],
        "symbols_changed": ["sanitizer.redact_payload", "logging.log_request"],
    },
]

AUTHORS: list[str] = [
    "sarah.chen@corp.internal",
    "marcus.vance@corp.internal",
    "elena.rostova@corp.internal",
    "devon.miles@corp.internal",
    "priya.sharma@corp.internal",
]


def generate_healthy_commits(
    services: list[str],
    window_start: datetime,
    rng: Random,
    count: int = 3,
) -> list[GitCommit]:
    """Generates realistic normal git commits that occurred prior to or during the window."""
    commits: list[GitCommit] = []
    
    for i in range(count):
        service = rng.choice(services)
        template = rng.choice(NORMAL_COMMIT_TEMPLATES)
        sha = f"{rng.getrandbits(160):040x}"
        
        # Commit timestamp between 30 to 180 minutes before window_start
        offset_minutes = rng.uniform(30.0, 180.0) + (i * 20.0)
        commit_time = window_start - timedelta(minutes=offset_minutes)
        
        commit = GitCommit(
            commit_sha=sha,
            author=rng.choice(AUTHORS),
            timestamp=commit_time,
            repository=f"corp/{service}",
            files_changed=list(template["files_changed"]),
            diff_summary=str(template["diff_summary"]),
            symbols_changed=list(template["symbols_changed"]),
        )
        commits.append(commit)
        
    return commits
