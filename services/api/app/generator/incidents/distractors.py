from datetime import datetime, timedelta
from random import Random
from typing import Any
from uuid import UUID

from app.schemas.deployments import Deployment, DeploymentStatus, GitCommit
from app.schemas.events import EventSeverity, LogEntry, MetricPoint


def inject_distractors(
    bundle: dict[str, list[Any]],
    incident_start: datetime,
    rng: Random,
) -> list[UUID]:
    """Injects 3 plausible but non-causal distractor events into the evidence bundle.
    
    1. Unrelated healthy deployment to notification-service.
    2. Transient latency blip in inventory-service metrics.
    3. Benign warning log in auth-service regarding a slow session cache lookup.
    
    Distractor events are completely indistinguishable from organic background noise
    when viewed in isolation, and do NOT contain any distractor-identifying tags in their
    metadata, labels, or attributes.
    
    Returns:
        List of 3 UUIDs tracking the distractor events on the evaluation-side Incident record.
    """
    distractor_ids: list[UUID] = []

    # --------------------------------------------------------------------------
    # Distractor 1: Unrelated deployment + commit to notification-service
    # --------------------------------------------------------------------------
    notif_dep_id = UUID(int=rng.getrandbits(128))
    distractor_ids.append(notif_dep_id)
    
    notif_commit_sha = f"{rng.getrandbits(160):040x}"
    notif_commit_time = incident_start - timedelta(minutes=rng.uniform(6.0, 10.0))
    notif_dep_start = notif_commit_time + timedelta(minutes=rng.uniform(1.0, 3.0))
    notif_dep_end = notif_dep_start + timedelta(minutes=rng.uniform(2.0, 4.0))

    notif_commit = GitCommit(
        commit_sha=notif_commit_sha,
        author="priya.sharma@corp.internal",
        timestamp=notif_commit_time,
        repository="corp/notification-service",
        files_changed=["src/templates/email_header.html", "src/styles/email.css"],
        diff_summary="Update corporate branding styles and logo dimensions in transactional email header templates",
        symbols_changed=["templates.render_header"],
    )
    notif_deployment = Deployment(
        deployment_id=notif_dep_id,
        service="notification-service",
        version="v1.19.4",
        commit_sha=notif_commit_sha,
        started_at=notif_dep_start,
        completed_at=notif_dep_end,
        environment="production",
        status=DeploymentStatus.SUCCESS,
    )
    bundle.setdefault("commits", []).append(notif_commit)
    bundle.setdefault("deployments", []).append(notif_deployment)

    # --------------------------------------------------------------------------
    # Distractor 2: Transient metric jitter in inventory-service
    # --------------------------------------------------------------------------
    metric_distractor_id = UUID(int=rng.getrandbits(128))
    distractor_ids.append(metric_distractor_id)

    # Add a brief, isolated latency metric spike around incident_start that resolves in 30s
    blip_ts = incident_start + timedelta(seconds=rng.uniform(15.0, 45.0))
    bundle.setdefault("metrics", []).append(
        MetricPoint(
            timestamp=blip_ts,
            service="inventory-service",
            metric_name="latency_p95_ms",
            value=round(rng.uniform(145.0, 185.0), 2),  # transient jump from baseline ~40ms
            unit="ms",
            labels={
                "service": "inventory-service",
                "env": "production",
                "host": "inventory-service-pod-1",
            },
        )
    )

    # --------------------------------------------------------------------------
    # Distractor 3: Slow cache lookup warning log in auth-service
    # --------------------------------------------------------------------------
    log_distractor_id = UUID(int=rng.getrandbits(128))
    distractor_ids.append(log_distractor_id)

    warn_ts = incident_start + timedelta(minutes=rng.uniform(1.0, 3.0))
    bundle.setdefault("logs", []).append(
        LogEntry(
            timestamp=warn_ts,
            service="auth-service",
            severity=EventSeverity.WARNING,
            message="Slow session cache read operation duration_ms=284.1 host=session-redis:6379 key=user:91024",
            trace_id=f"{rng.getrandbits(128):032x}",
            request_id=f"req-{rng.getrandbits(48):012x}",
            metadata={
                "env": "production",
                "host": "auth-service-pod-2",
            },
        )
    )

    return distractor_ids
