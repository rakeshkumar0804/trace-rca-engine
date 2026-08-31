from copy import deepcopy
from datetime import datetime, timedelta
from random import Random
from typing import Any
from uuid import UUID, uuid4

from app.schemas.alerts import Alert, AlertSeverity
from app.schemas.database_events import DatabaseEvent, DatabaseEventStatus
from app.schemas.deployments import Deployment, DeploymentStatus, GitCommit
from app.schemas.events import EventSeverity, LogEntry, MetricPoint, TraceSpan
from app.schemas.incidents import (
    CausalChainLink,
    GroundTruth,
    Incident,
    IncidentDifficulty,
    IncidentSeverity,
)

from .distractors import inject_distractors
from .incident_types import IncidentType, register_incident_type


def generate_dependency_failure_cascade_incident(
    seed: int,
    base_environment: dict[str, list[Any]],
    incident_start: datetime,
    duration_minutes: int = 15,
) -> tuple[Incident, dict[str, list[Any]]]:
    """Injects the 'Dependency Failure: payment-service degradation cascades to checkout-service' incident.
    
    Causal Chain (Hidden Ground Truth):
    1. payment-service internal worker thread pool becomes exhausted / begins timing out.
    2. payment-service request latency spikes and error rate rises.
    3. checkout-service synchronous calls to payment-service start timing out.
    4. checkout-service thread pool becomes saturated waiting on payment-service responses.
    5. checkout-service latency spikes and timeouts cascade to api-gateway.
    6. Alert fires: elevated 5xx rate on checkout-service.

    Returns:
        tuple[Incident, dict]:
            - Incident: Benchmark incident record with isolated GroundTruth.
            - dict: Investigator-facing evidence bundle with observable symptoms and distractors.
    """
    rng = Random(seed)
    bundle: dict[str, list[Any]] = {k: list(v) for k, v in base_environment.items()}

    incident_id = UUID(int=rng.getrandbits(128))

    # --------------------------------------------------------------------------
    # 1. Distractor Deployment in an UNRELATED Service (inventory-service)
    #    (Tests whether TRACE avoids blindly pattern-matching "any deployment = cause")
    # --------------------------------------------------------------------------
    distractor_commit_sha = f"{rng.getrandbits(160):040x}"
    distractor_dep_id = UUID(int=rng.getrandbits(128))
    distractor_dep_time = incident_start - timedelta(minutes=rng.uniform(6.0, 9.0))

    distractor_commit = GitCommit(
        commit_sha=distractor_commit_sha,
        author="elena.rostova@corp.internal",
        timestamp=distractor_dep_time - timedelta(minutes=2),
        repository="corp/inventory-service",
        files_changed=[
            "src/inventory/reorder.py",
            "src/models/warehouse.py",
        ],
        diff_summary="Update safety stock calculation logic for regional warehouses",
        symbols_changed=["recalculate_safety_stock", "WarehouseLocation"],
    )

    distractor_dep = Deployment(
        deployment_id=distractor_dep_id,
        service="inventory-service",
        version="v1.8.2",
        commit_sha=distractor_commit_sha,
        started_at=distractor_dep_time,
        completed_at=distractor_dep_time + timedelta(minutes=2.5),
        environment="production",
        status=DeploymentStatus.SUCCESS,
    )

    bundle["commits"].append(distractor_commit)
    bundle["deployments"].append(distractor_dep)

    # --------------------------------------------------------------------------
    # 2. payment-service Initial Degradation (starts 2-3 mins BEFORE checkout symptoms)
    # --------------------------------------------------------------------------
    payment_degradation_start = incident_start - timedelta(minutes=rng.uniform(2.0, 3.0))

    # Internal payment-service warning and error logs
    bundle["logs"].append(
        LogEntry(
            timestamp=payment_degradation_start + timedelta(seconds=15),
            service="payment-service",
            severity=EventSeverity.WARNING,
            message="Payment gateway thread pool reaching high concurrency: 45/50 workers active",
            metadata={"pool_active": "45", "pool_max": "50", "queue_depth": "120"},
        )
    )
    bundle["logs"].append(
        LogEntry(
            timestamp=payment_degradation_start + timedelta(seconds=45),
            service="payment-service",
            severity=EventSeverity.ERROR,
            message="Payment worker thread pool exhausted: queue capacity exceeded, dropping requests",
            metadata={"pool_active": "50", "pool_max": "50", "queue_depth": "500", "rejected_count": "35"},
        )
    )
    bundle["logs"].append(
        LogEntry(
            timestamp=payment_degradation_start + timedelta(seconds=75),
            service="payment-service",
            severity=EventSeverity.ERROR,
            message="Transaction authorization timed out: worker thread failed to acquire connection within 5000ms",
            metadata={"timeout_ms": "5000", "error": "WorkerTimeoutException"},
        )
    )

    # Metric points for payment-service: Latency and error rate spiking early
    curr_time = payment_degradation_start
    while curr_time <= incident_start + timedelta(minutes=duration_minutes):
        progress = (curr_time - payment_degradation_start).total_seconds() / 60.0
        if progress > 0:
            payment_lat = min(4200.0, 120.0 + progress * 650.0 + rng.uniform(-50, 50))
            payment_err = min(0.28, 0.001 + progress * 0.04 + rng.uniform(-0.005, 0.005))
            bundle["metrics"].append(
                MetricPoint(
                    timestamp=curr_time,
                    service="payment-service",
                    metric_name="latency_p95_ms",
                    value=payment_lat,
                    unit="milliseconds",
                )
            )
            bundle["metrics"].append(
                MetricPoint(
                    timestamp=curr_time,
                    service="payment-service",
                    metric_name="error_rate",
                    value=payment_err,
                    unit="ratio",
                )
            )
        curr_time += timedelta(minutes=1)

    # --------------------------------------------------------------------------
    # 3. checkout-service Cascading Failure (starts at incident_start)
    # --------------------------------------------------------------------------
    for m in range(0, duration_minutes + 1):
        step_time = incident_start + timedelta(minutes=m)

        # checkout-service latency & error rate metrics
        checkout_lat = min(4500.0, 180.0 + (m + 1) * 700.0 + rng.uniform(-60, 60))
        checkout_err = min(0.32, 0.002 + (m + 1) * 0.045 + rng.uniform(-0.005, 0.005))
        bundle["metrics"].append(
            MetricPoint(
                timestamp=step_time,
                service="checkout-service",
                metric_name="latency_p95_ms",
                value=checkout_lat,
                unit="milliseconds",
            )
        )
        bundle["metrics"].append(
            MetricPoint(
                timestamp=step_time,
                service="checkout-service",
                metric_name="error_rate",
                value=checkout_err,
                unit="ratio",
            )
        )

        # api-gateway cascading latency
        bundle["metrics"].append(
            MetricPoint(
                timestamp=step_time,
                service="api-gateway",
                metric_name="latency_p95_ms",
                value=min(4800.0, 210.0 + (m + 1) * 680.0 + rng.uniform(-40, 40)),
                unit="milliseconds",
            )
        )

        # Timeout error logs in checkout-service explicitly referencing payment-service
        bundle["logs"].append(
            LogEntry(
                timestamp=step_time + timedelta(seconds=rng.uniform(5, 25)),
                service="checkout-service",
                severity=EventSeverity.ERROR,
                message="HTTP request to payment-service failed: connection timed out after 5000ms",
                metadata={
                    "target_service": "payment-service",
                    "endpoint": "/payments/authorize",
                    "timeout_ms": "5000",
                    "error": "ConnectTimeoutError",
                },
            )
        )
        bundle["logs"].append(
            LogEntry(
                timestamp=step_time + timedelta(seconds=rng.uniform(30, 50)),
                service="checkout-service",
                severity=EventSeverity.ERROR,
                message="Checkout workflow failed: upstream payment gateway dependency unresponsive",
                metadata={"status_code": "504", "upstream": "payment-service"},
            )
        )

        # Trace spans showing checkout-service -> payment-service call duration blowing up
        trace_id = f"{rng.getrandbits(128):032x}"
        parent_span_id = f"{rng.getrandbits(64):016x}"
        child_span_id = f"{rng.getrandbits(64):016x}"

        bundle["traces"].append(
            TraceSpan(
                trace_id=trace_id,
                span_id=parent_span_id,
                service="checkout-service",
                operation="POST /checkout/submit",
                start_time=step_time + timedelta(seconds=10),
                duration_ms=5200.0,
                status="error",
                attributes={"http.status_code": "504", "user_id": "usr_9912"},
            )
        )
        bundle["traces"].append(
            TraceSpan(
                trace_id=trace_id,
                span_id=child_span_id,
                parent_span_id=parent_span_id,
                service="checkout-service",
                operation="HTTP POST http://payment-service/payments/authorize",
                start_time=step_time + timedelta(seconds=10, milliseconds=100),
                duration_ms=5000.0,
                status="error",
                attributes={"peer.service": "payment-service", "error": "timeout"},
            )
        )

    # --------------------------------------------------------------------------
    # 4. Critical Alert on checkout-service 5xx Spike
    # --------------------------------------------------------------------------
    alert_time = incident_start + timedelta(minutes=2)
    bundle["alerts"].append(
        Alert(
            id=UUID(int=rng.getrandbits(128)),
            timestamp=alert_time,
            alert_type="high_error_rate_5xx",
            service="checkout-service",
            severity=AlertSeverity.CRITICAL,
            description="High 5xx error rate alert on checkout-service (error rate > 20%)",
            metadata={"error_rate": "0.24", "threshold": "0.05"},
        )
    )

    # --------------------------------------------------------------------------
    # 5. Normal checkout_db State (Negative Evidence)
    #    Demonstrates checkout_db is healthy, ruling out database exhaustion
    # --------------------------------------------------------------------------
    for m in range(0, duration_minutes + 1, 3):
        db_time = incident_start + timedelta(minutes=m)
        bundle["database_events"].append(
            DatabaseEvent(
                timestamp=db_time,
                database="checkout_db",
                query_fingerprint="SELECT id, status, total FROM orders WHERE user_id = ?",
                duration_ms=8.5 + rng.uniform(-1.0, 2.0),
                connections_active=12,
                connections_max=100,
                locks_held=0,
                rows_affected=1,
                status=DatabaseEventStatus.OK,
            )
        )

    # --------------------------------------------------------------------------
    # 6. Additional Distractors (Clean of identifying metadata)
    # --------------------------------------------------------------------------
    inject_distractors(
        bundle=bundle,
        incident_start=incident_start,
        rng=rng,
    )

    # Sort all collections chronologically
    bundle["logs"].sort(key=lambda x: x.timestamp)
    bundle["metrics"].sort(key=lambda x: x.timestamp)
    bundle["traces"].sort(key=lambda x: x.start_time)
    bundle["database_events"].sort(key=lambda x: x.timestamp)
    bundle["alerts"].sort(key=lambda x: x.timestamp)
    bundle["deployments"].sort(key=lambda x: x.started_at)
    bundle["commits"].sort(key=lambda x: x.timestamp)

    # --------------------------------------------------------------------------
    # 7. Ground Truth Model (Strictly Isolated from Evidence Text)
    # --------------------------------------------------------------------------
    causal_chain = [
        CausalChainLink(
            from_node="payment_gateway_thread_exhaustion",
            to_node="payment_latency_and_error_spike",
            relationship="caused",
            explanation="Internal payment gateway worker thread pool reached max capacity of 50 active workers and began rejecting requests",
        ),
        CausalChainLink(
            from_node="payment_latency_and_error_spike",
            to_node="checkout_to_payment_timeouts",
            relationship="caused",
            explanation="payment-service p95 latency spiked over 3500ms causing synchronous calls from checkout-service to block and time out",
        ),
        CausalChainLink(
            from_node="checkout_to_payment_timeouts",
            to_node="checkout_worker_thread_saturation",
            relationship="caused",
            explanation="checkout-service worker threads became saturated waiting on blocked HTTP requests to payment-service",
        ),
        CausalChainLink(
            from_node="checkout_worker_thread_saturation",
            to_node="checkout_latency_and_504_spike",
            relationship="caused",
            explanation="checkout-service latency spiked and 504 Gateway Timeout errors cascaded upstream to api-gateway",
        ),
        CausalChainLink(
            from_node="checkout_latency_and_504_spike",
            to_node="alert_high_5xx_rate",
            relationship="caused",
            explanation="checkout-service 5xx error rate exceeded 5% threshold, firing a critical alert",
        ),
    ]

    ground_truth = GroundTruth(
        root_cause=(
            "Internal thread pool exhaustion and timeout degradation in payment-service caused "
            "cascading request timeouts and worker pool saturation in checkout-service."
        ),
        causal_chain=causal_chain,
        responsible_commit_sha=None,
        responsible_deployment_id=None,
    )

    incident = Incident(
        incident_id=incident_id,
        incident_type=IncidentType.DEPENDENCY_FAILURE_CASCADE.value,
        start_time=incident_start,
        end_time=incident_start + timedelta(minutes=duration_minutes),
        difficulty=IncidentDifficulty.MEDIUM,
        severity=IncidentSeverity.SEV1,
        ground_truth=ground_truth,
        affected_services=["checkout-service", "payment-service", "api-gateway"],
        expected_symptoms=[
            "checkout-service p95 latency spike (>3000ms)",
            "payment-service worker thread pool exhaustion and latency spike",
            "HTTP 504 Gateway Timeout errors in checkout-service logs waiting on payment-service",
            "High 5xx error rate alert on checkout-service",
        ],
    )

    return incident, bundle


# Register incident generator in the global registry
register_incident_type(
    IncidentType.DEPENDENCY_FAILURE_CASCADE.value,
    generate_dependency_failure_cascade_incident,
)
