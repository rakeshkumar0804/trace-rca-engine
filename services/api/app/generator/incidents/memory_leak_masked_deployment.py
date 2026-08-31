from copy import deepcopy
from datetime import datetime, timedelta, timezone
from random import Random
from typing import Any
from uuid import UUID

from app.schemas.alerts import Alert, AlertSeverity
from app.schemas.database_events import DatabaseEvent, DatabaseEventStatus
from app.schemas.deployments import Deployment, DeploymentStatus, GitCommit
from app.schemas.events import EventSeverity, EventSource, LogEntry, MetricPoint, TraceSpan
from app.schemas.incidents import (
    CausalChainLink,
    GroundTruth,
    Incident,
    IncidentDifficulty,
    IncidentSeverity,
)

from .distractors import inject_distractors
from .incident_types import IncidentType, register_incident_type


def generate_memory_leak_masked_deployment_incident(
    seed: int,
    base_environment: dict[str, list[Any]],
    incident_start: datetime,
    duration_minutes: int = 45,
) -> tuple[Incident, dict[str, list[Any]]]:
    """Generates the 'Memory Leak masked by a coincidental, unrelated deployment' incident scenario.

    Causal Chain (Hidden Ground Truth):
      1. checkout-service has a progressive heap memory leak starting at T=0.
      2. Memory usage climbs linearly at a steady slope (+35MB/min) over the 45-minute window.
      3. At T=15m, a coincidental deployment (v2.16.0 - 'Add caching layer') completes.
         The memory growth rate (slope) remains IDENTICAL before and after this deployment.
      4. At T=35m, memory crosses the 1650MB threshold (>80% heap), causing frequent Stop-The-World
         GC pauses (>1800ms) and latency spikes.
      5. GC stalls cause request timeouts and cascading 5xx errors to api-gateway, firing an alert.

    Returns:
        tuple[Incident, dict]:
            - Incident: Benchmark incident record with isolated GroundTruth.
            - dict: Investigator-facing evidence bundle with realistic telemetry.
    """
    rng = Random(seed)
    bundle: dict[str, list[Any]] = {k: list(v) for k, v in base_environment.items()}
    incident_id = UUID(int=rng.getrandbits(128))
    incident_end = incident_start + timedelta(minutes=duration_minutes)

    # --------------------------------------------------------------------------
    # 1. Inject Red-Herring Deployment (at T=15m partway through leak)
    # --------------------------------------------------------------------------
    red_herring_commit_sha = f"{rng.getrandbits(160):040x}"
    red_herring_dep_id = UUID(int=rng.getrandbits(128))

    dep_commit_time = incident_start + timedelta(minutes=13, seconds=rng.uniform(0, 30))
    dep_start_time = incident_start + timedelta(minutes=15, seconds=rng.uniform(0, 20))
    dep_completed_time = dep_start_time + timedelta(minutes=2, seconds=rng.uniform(10, 40))

    red_herring_commit = GitCommit(
        commit_sha=red_herring_commit_sha,
        author="alex.mercer@corp.internal",
        timestamp=dep_commit_time,
        repository="corp/checkout-service",
        files_changed=[
            "src/cache/lru_cache.py",
            "src/services/discounts.py",
            "config/cache.yaml",
        ],
        diff_summary="Add in-memory LRU response caching layer for discount lookups",
    )
    bundle.setdefault("commits", []).append(red_herring_commit)

    red_herring_dep = Deployment(
        deployment_id=red_herring_dep_id,
        service="checkout-service",
        version="v2.16.0",
        commit_sha=red_herring_commit_sha,
        started_at=dep_start_time,
        completed_at=dep_completed_time,
        environment="production",
        status=DeploymentStatus.SUCCESS,
    )
    bundle.setdefault("deployments", []).append(red_herring_dep)

    # --------------------------------------------------------------------------
    # 2. Inject Memory Growth MetricPoints (Strictly Constant Slope from T=0 to T=45)
    # Slope: ~33.3 MB per minute from base 400MB up to ~1900MB at T=45m.
    # --------------------------------------------------------------------------
    base_heap_mb = 400.0
    slope_mb_per_min = 33.33  # Identical slope before & after deployment

    # Remove background healthy memory_mb for checkout-service so the leak series is clean
    bundle["metrics"] = [
        m for m in bundle.get("metrics", [])
        if not (m.service == "checkout-service" and m.metric_name == "memory_mb")
    ]

    for minute in range(0, duration_minutes + 1):
        pt_time = incident_start + timedelta(minutes=minute, seconds=rng.uniform(0, 15))
        heap_val = base_heap_mb + (minute * slope_mb_per_min) + rng.uniform(-4.0, 4.0)

        bundle.setdefault("metrics", []).append(
            MetricPoint(
                service="checkout-service",
                metric_name="memory_mb",
                timestamp=pt_time,
                value=round(heap_val, 2),
                unit="megabytes",
                labels={
                    "host": "checkout-svc-prod-01",
                    "heap_max_mb": "2048",
                    "heap_used_pct": f"{((heap_val / 2048.0) * 100):.2f}",
                },
            )
        )

    # --------------------------------------------------------------------------
    # 3. Inject GC Pause Events, Latency Spikes, and 5xx Errors (Triggered at T >= 35m)
    # --------------------------------------------------------------------------
    threshold_minute = 35  # Memory crosses > 1600MB
    for minute in range(threshold_minute, duration_minutes + 1):
        t_base = incident_start + timedelta(minutes=minute)

        # GC pause metric & logs
        gc_duration_ms = rng.uniform(1600.0, 2400.0)
        bundle["metrics"].append(
            MetricPoint(
                service="checkout-service",
                metric_name="gc_pause_duration_ms",
                timestamp=t_base + timedelta(seconds=10),
                value=round(gc_duration_ms, 2),
                unit="milliseconds",
                labels={"gc_type": "Major_G1_StopTheWorld", "host": "checkout-svc-prod-01"},
            )
        )

        bundle.setdefault("logs", []).append(
            LogEntry(
                service="checkout-service",
                timestamp=t_base + timedelta(seconds=12),
                severity=EventSeverity.WARNING if minute < 38 else EventSeverity.ERROR,
                message=f"High JVM garbage collection pause duration: gc_time={gc_duration_ms:.0f}ms, host=checkout-svc-prod-01",
                metadata={
                    "gc_duration_ms": f"{gc_duration_ms:.2f}",
                    "event_type": "gc_pause_warning",
                },
            )
        )

        # Latency metric spike
        p95_val = rng.uniform(2800.0, 3900.0)
        bundle["metrics"].append(
            MetricPoint(
                service="checkout-service",
                metric_name="p95_latency_ms",
                timestamp=t_base + timedelta(seconds=25),
                value=round(p95_val, 2),
                unit="milliseconds",
                labels={"endpoint": "/v1/checkout", "status": "degraded"},
            )
        )

        # 5xx error rate metric spike
        bundle["metrics"].append(
            MetricPoint(
                service="checkout-service",
                metric_name="error_rate_5xx",
                timestamp=t_base + timedelta(seconds=30),
                value=round(rng.uniform(0.06, 0.12), 4),
                unit="ratio",
                labels={"service": "checkout-service"},
            )
        )

        # Traces with 504 / 500 status
        trace_id = f"{rng.getrandbits(64):016x}"
        span_id = f"{rng.getrandbits(64):016x}"
        bundle.setdefault("traces", []).append(
            TraceSpan(
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=None,
                service="checkout-service",
                operation="HTTP GET /v1/checkout",
                start_time=t_base + timedelta(seconds=35),
                duration_ms=round(rng.uniform(3200.0, 4800.0), 2),
                status="error",
                attributes={"http.status_code": "504", "error": "Gateway Timeout during GC stall"},
            )
        )

    # --------------------------------------------------------------------------
    # 4. Inject 5xx Alert at T=38m
    # --------------------------------------------------------------------------
    alert_time = incident_start + timedelta(minutes=38, seconds=15)
    alert = Alert(
        timestamp=alert_time,
        alert_type="High5xxErrorRate",
        service="checkout-service",
        severity=AlertSeverity.CRITICAL,
        description="checkout-service 5xx error rate exceeded 5% threshold (observed 8.4%)",
    )
    bundle.setdefault("alerts", []).append(alert)

    # --------------------------------------------------------------------------
    # 5. Inject Distractors (e.g. distractor deployment to inventory-service at T=8m)
    # --------------------------------------------------------------------------
    distractor_ids: list[UUID] = []
    inv_dep_time = incident_start + timedelta(minutes=8)
    inv_dep_id = UUID(int=rng.getrandbits(128))
    distractor_ids.append(inv_dep_id)

    bundle["deployments"].append(
        Deployment(
            deployment_id=inv_dep_id,
            service="inventory-service",
            version="v1.8.2",
            commit_sha=f"{rng.getrandbits(160):040x}",
            started_at=inv_dep_time,
            completed_at=inv_dep_time + timedelta(minutes=2),
            environment="production",
            status=DeploymentStatus.SUCCESS,
        )
    )

    # --------------------------------------------------------------------------
    # 6. Build Isolated GroundTruth
    # --------------------------------------------------------------------------
    causal_chain = [
        CausalChainLink(
            from_node="unbounded_object_cache_leak",
            to_node="progressive_memory_growth",
            relationship="caused",
            explanation="Unbounded discount computation object caching accumulated heap memory at ~33MB/min from T=0",
        ),
        CausalChainLink(
            from_node="progressive_memory_growth",
            to_node="heap_threshold_saturation",
            relationship="caused",
            explanation="Heap usage crossed the 1650MB threshold (>80% capacity) at T=35m",
        ),
        CausalChainLink(
            from_node="heap_threshold_saturation",
            to_node="stop_the_world_gc_pauses",
            relationship="caused",
            explanation="Frequent major Stop-The-World garbage collection cycles stalled request worker threads for >1800ms",
        ),
        CausalChainLink(
            from_node="stop_the_world_gc_pauses",
            to_node="checkout_latency_and_5xx_timeouts",
            relationship="caused",
            explanation="GC pause thread stalls caused HTTP 504 gateway timeouts and 5xx errors to cascade to callers",
        ),
        CausalChainLink(
            from_node="checkout_latency_and_5xx_timeouts",
            to_node="alert_high_5xx_rate",
            relationship="caused",
            explanation="5xx error rate exceeded 5% threshold, firing High5xxErrorRate alert",
        ),
    ]

    ground_truth = GroundTruth(
        root_cause=(
            "Progressive heap memory leak and unbounded object accumulation in checkout-service caused "
            "severe garbage collection pauses and request timeouts once heap crossed threshold. The coincidental "
            "deployment of v2.16.0 at T=15m was non-causal as memory growth rate was identical before and after."
        ),
        causal_chain=causal_chain,
        responsible_commit_sha=None,
        responsible_deployment_id=None,
    )

    incident = Incident(
        incident_id=incident_id,
        incident_type=IncidentType.MEMORY_LEAK_MASKED_DEPLOYMENT.value,
        start_time=incident_start,
        end_time=incident_end,
        difficulty=IncidentDifficulty.HARD,
        severity=IncidentSeverity.SEV1,
        ground_truth=ground_truth,
        affected_services=["checkout-service", "api-gateway"],
        expected_symptoms=[
            "checkout-service memory_mb linear increase from T=0",
            "JVM major garbage collection pauses (>1800ms) after T=35m",
            "checkout-service p95 latency spike (>3000ms)",
            "High 5xx error rate alert on checkout-service",
        ],
        distractor_event_ids=distractor_ids,
    )

    return incident, bundle


# Register generator in the global registry
register_incident_type(
    IncidentType.MEMORY_LEAK_MASKED_DEPLOYMENT.value,
    generate_memory_leak_masked_deployment_incident,
)
