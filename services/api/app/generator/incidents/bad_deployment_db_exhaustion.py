from copy import deepcopy
from datetime import datetime, timedelta
from random import Random
from typing import Any
from uuid import UUID

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


def strip_ground_truth_for_investigator(incident: Incident) -> dict[str, Any]:
    """Strips the ground_truth field from the incident model for investigator-facing presentation.
    
    This function establishes the explicit boundary ensuring the evaluation ground truth is NEVER
    leaked to the investigator in API responses or input payloads.
    """
    data = incident.model_dump(mode="json")
    data.pop("ground_truth", None)
    return data


def generate_bad_deployment_db_exhaustion_incident(
    seed: int,
    base_environment: dict[str, list[Any]],
    incident_start: datetime,
    duration_minutes: int = 15,
) -> tuple[Incident, dict[str, list[Any]]]:
    """Injects the 'Bad deployment -> N+1 query -> DB pool saturation -> 5xx errors' incident.
    
    Returns:
        tuple[Incident, dict]:
            - Incident: The benchmark incident record containing isolated GroundTruth and metadata.
            - dict: The mutated, investigator-facing evidence bundle with observable symptoms only.
    """
    rng = Random(seed)
    # Deep copy base environment so input is not mutated unexpectedly
    bundle: dict[str, list[Any]] = {k: list(v) for k, v in base_environment.items()}

    # --------------------------------------------------------------------------
    # 1. Inject Causal Deployment and Commit (timestamped shortly before symptoms)
    # --------------------------------------------------------------------------
    causal_commit_sha = f"{rng.getrandbits(160):040x}"
    causal_dep_id = UUID(int=rng.getrandbits(128))

    commit_time = incident_start - timedelta(minutes=rng.uniform(4.0, 6.0))
    dep_start_time = commit_time + timedelta(minutes=rng.uniform(1.0, 2.0))
    dep_completed_time = dep_start_time + timedelta(minutes=rng.uniform(2.0, 3.0))

    # Commit describes the feature addition factually WITHOUT narrating any bug or defect
    causal_commit = GitCommit(
        commit_sha=causal_commit_sha,
        author="marcus.vance@corp.internal",
        timestamp=commit_time,
        repository="corp/checkout-service",
        files_changed=[
            "src/checkout/summary.py",
            "src/services/discounts.py",
            "src/models/discount_rule.py",
        ],
        diff_summary="Add itemized discount breakdown and promotional rebate calculation to checkout summary response",
        symbols_changed=[
            "summary.calculate_itemized_discounts",
            "discounts.lookup_item_rebate",
        ],
    )

    causal_deployment = Deployment(
        deployment_id=causal_dep_id,
        service="checkout-service",
        version="v2.15.0",
        commit_sha=causal_commit_sha,
        started_at=dep_start_time,
        completed_at=dep_completed_time,
        environment="production",
        status=DeploymentStatus.SUCCESS,
    )

    bundle.setdefault("commits", []).append(causal_commit)
    bundle.setdefault("deployments", []).append(causal_deployment)

    # --------------------------------------------------------------------------
    # 2. Inject Corrupted Database Telemetry on checkout_db (Post-deployment)
    # --------------------------------------------------------------------------
    # Filter and mutate database events during the incident window for checkout_db
    incident_end = incident_start + timedelta(minutes=duration_minutes)

    new_db_events: list[DatabaseEvent] = []
    for db_evt in bundle.get("database_events", []):
        if db_evt.database == "checkout_db" and db_evt.timestamp >= dep_completed_time:
            # Time elapsed since deployment completion in minutes
            elapsed = (db_evt.timestamp - dep_completed_time).total_seconds() / 60.0

            # Escalating active connections: baseline (28) -> 55 -> 88 -> 100 (max)
            raw_conns = int(28 + elapsed * 20 + rng.randint(0, 4))
            
            if elapsed >= 2.5 or raw_conns >= 90:
                # Connection pool saturated (92-100) -> query timeouts
                active_conns = min(100, max(92, raw_conns))
                duration = 5000.0 + round(rng.uniform(10.0, 120.0), 2)
                status = DatabaseEventStatus.TIMEOUT
                locks = rng.randint(6, 15)
                rows = 0
            elif elapsed >= 1.2 or raw_conns >= 65:
                # Severe contention -> slow queries
                active_conns = min(91, max(65, raw_conns))
                duration = round(rng.uniform(1200.0, 3200.0), 2)
                status = DatabaseEventStatus.SLOW
                locks = rng.randint(3, 8)
                rows = 1
            else:
                active_conns = min(64, max(28, raw_conns))
                duration = round(rng.uniform(80.0, 450.0), 2)
                status = DatabaseEventStatus.OK
                locks = rng.randint(1, 4)
                rows = 1

            query = rng.choice([
                "SELECT * FROM discount_rules WHERE item_id = ? AND is_active = TRUE",
                "SELECT rebate_cents, rule_type FROM promotional_rebates WHERE sku = ?",
                "SELECT * FROM cart WHERE user_id = ?",
            ])

            mutated_evt = DatabaseEvent(
                timestamp=db_evt.timestamp,
                database="checkout_db",
                query_fingerprint=query,
                duration_ms=duration,
                connections_active=active_conns,
                connections_max=100,
                locks_held=locks,
                rows_affected=rows,
                status=status,
            )
            new_db_events.append(mutated_evt)
        else:
            new_db_events.append(db_evt)

    bundle["database_events"] = new_db_events

    # --------------------------------------------------------------------------
    # 3. Inject Spiking Metrics for checkout-service
    # --------------------------------------------------------------------------
    new_metrics: list[MetricPoint] = []
    for m in bundle.get("metrics", []):
        if m.service == "checkout-service" and m.timestamp >= dep_completed_time:
            elapsed = (m.timestamp - dep_completed_time).total_seconds() / 60.0
            
            if m.metric_name == "latency_p95_ms":
                # Spikes from ~110ms to > 3500ms
                mutated_val = round(min(5200.0, 110.0 + elapsed * 950.0 + rng.uniform(-50.0, 150.0)), 2)
                new_metrics.append(m.model_copy(update={"value": mutated_val}))
            elif m.metric_name == "latency_p50_ms":
                # Spikes from ~45ms to ~1800ms
                mutated_val = round(min(2800.0, 45.0 + elapsed * 420.0 + rng.uniform(-20.0, 60.0)), 2)
                new_metrics.append(m.model_copy(update={"value": mutated_val}))
            elif m.metric_name == "error_rate":
                # Spikes from 0.2% to 15-22%
                mutated_val = round(min(22.0, 0.2 + elapsed * 4.2 + rng.uniform(-0.3, 0.8)), 4)
                new_metrics.append(m.model_copy(update={"value": mutated_val}))
            elif m.metric_name == "db_connections_active":
                # Spikes to pool limit (100)
                mutated_val = round(min(100.0, 28.0 + elapsed * 18.0 + rng.uniform(-1.0, 3.0)), 1)
                new_metrics.append(m.model_copy(update={"value": mutated_val}))
            else:
                new_metrics.append(m)
        else:
            new_metrics.append(m)

    bundle["metrics"] = new_metrics

    # --------------------------------------------------------------------------
    # 4. Inject Error Logs from checkout-service
    # --------------------------------------------------------------------------
    error_log_templates = [
        "Database connection pool exhausted: connection acquisition timed out after 5000ms host=checkout-db:5432",
        "Failed to compute checkout summary: upstream database query timeout database=checkout_db user_id=usr-{user_id}",
        "HTTP 504 Gateway Timeout returned for checkout_id={checkout_id} duration_ms=5021.3",
        "Cart discount evaluation failed: database connection timeout after 5000ms item_count={qty}",
    ]

    # Add realistic error logs during the active incident window
    ticks = sorted(list({db.timestamp for db in new_db_events if db.timestamp >= incident_start}))
    for ts in ticks[::2]:  # Every ~20 seconds
        trace_hex = f"{rng.getrandbits(128):032x}"
        req_hex = f"{rng.getrandbits(48):012x}"
        uid = rng.randint(10000, 99999)
        chk_id = f"chk-{rng.getrandbits(32):08x}"
        msg = rng.choice(error_log_templates).format(
            user_id=uid,
            checkout_id=chk_id,
            qty=rng.randint(2, 6),
        )
        bundle.setdefault("logs", []).append(
            LogEntry(
                timestamp=ts,
                service="checkout-service",
                severity=EventSeverity.ERROR,
                message=msg,
                trace_id=trace_hex,
                request_id=f"req-{req_hex}",
                metadata={"env": "production", "component": "checkout-engine"},
            )
        )

    # --------------------------------------------------------------------------
    # 5. Inject Error Trace Spans during Incident Window
    # --------------------------------------------------------------------------
    new_traces: list[TraceSpan] = []
    for span in bundle.get("traces", []):
        if span.start_time >= incident_start + timedelta(minutes=2.0):
            if span.service == "checkout-service" and "checkout" in span.operation:
                # Checkout span errors with 5000ms timeout duration
                mutated_span = span.model_copy(update={
                    "duration_ms": round(5000.0 + rng.uniform(15.0, 80.0), 2),
                    "status": "error",
                    "attributes": {
                        **span.attributes,
                        "error": "true",
                        "error.type": "DatabaseTimeoutException",
                        "http.status_code": "500",
                    },
                })
                new_traces.append(mutated_span)
            elif span.service == "api-gateway" and span.parent_span_id is None and "checkout" in span.operation:
                # Gateway root span bubbles up HTTP 504
                mutated_span = span.model_copy(update={
                    "duration_ms": round(5025.0 + rng.uniform(20.0, 95.0), 2),
                    "status": "error",
                    "attributes": {
                        **span.attributes,
                        "http.status_code": "504",
                        "error": "true",
                    },
                })
                new_traces.append(mutated_span)
            else:
                new_traces.append(span)
        else:
            new_traces.append(span)

    bundle["traces"] = new_traces

    # --------------------------------------------------------------------------
    # 6. Inject Critical Alert (fires partway through the incident window)
    # --------------------------------------------------------------------------
    alert_time = incident_start + timedelta(minutes=rng.uniform(3.5, 4.5))
    critical_alert = Alert(
        timestamp=alert_time,
        alert_type="High5xxErrorRate",
        service="checkout-service",
        severity=AlertSeverity.CRITICAL,
        description="5xx error rate on checkout-service exceeded 5% threshold (current: 16.4%) over 3m evaluation window",
    )
    bundle.setdefault("alerts", []).append(critical_alert)

    # --------------------------------------------------------------------------
    # 7. Inject 3 Distractor Events
    # --------------------------------------------------------------------------
    distractor_ids = inject_distractors(bundle, incident_start, rng)

    # Sort all bundle streams chronologically
    bundle["logs"].sort(key=lambda x: x.timestamp)
    bundle["metrics"].sort(key=lambda x: x.timestamp)
    bundle["traces"].sort(key=lambda x: x.start_time)
    bundle["deployments"].sort(key=lambda x: x.started_at)
    bundle["commits"].sort(key=lambda x: x.timestamp)
    bundle["database_events"].sort(key=lambda x: x.timestamp)
    bundle["alerts"].sort(key=lambda x: x.timestamp)

    # --------------------------------------------------------------------------
    # 8. Build Hidden GroundTruth and Incident Model
    # --------------------------------------------------------------------------
    causal_chain = [
        CausalChainLink(
            from_node="checkout_service_deployment",
            to_node="n_plus_one_query_pattern",
            relationship="introduced",
            explanation="Deployment v2.15.0 introduced itemized discount calculations executing query-in-loop per cart item",
        ),
        CausalChainLink(
            from_node="n_plus_one_query_pattern",
            to_node="checkout_db_query_volume_surge",
            relationship="increased",
            explanation="Discount query volume against checkout_db surged 10x per checkout summary request",
        ),
        CausalChainLink(
            from_node="checkout_db_query_volume_surge",
            to_node="connection_pool_saturation",
            relationship="caused",
            explanation="Active connections against checkout_db saturated the pool capacity limit of 100 connections",
        ),
        CausalChainLink(
            from_node="connection_pool_saturation",
            to_node="database_query_timeouts",
            relationship="caused",
            explanation="Connection acquisition blocked and timed out after 5000ms threshold",
        ),
        CausalChainLink(
            from_node="database_query_timeouts",
            to_node="checkout_latency_spike",
            relationship="caused",
            explanation="checkout-service p95 latency spiked from 110ms to >3500ms due to connection acquisition timeouts",
        ),
        CausalChainLink(
            from_node="checkout_latency_spike",
            to_node="cascading_5xx_errors",
            relationship="caused",
            explanation="Cascading timeouts returned HTTP 504 and HTTP 500 error responses to api-gateway",
        ),
        CausalChainLink(
            from_node="cascading_5xx_errors",
            to_node="alert_high_5xx_rate",
            relationship="caused",
            explanation="checkout-service 5xx error rate exceeded 5% threshold, firing a critical alert",
        ),
    ]

    ground_truth = GroundTruth(
        root_cause="Deployment of checkout-service version v2.15.0 introduced an N+1 database query pattern in item discount calculation, exhausting the checkout_db connection pool and causing query timeouts and cascading HTTP 5xx errors.",
        causal_chain=causal_chain,
        responsible_commit_sha=causal_commit_sha,
        responsible_deployment_id=causal_dep_id,
    )

    incident = Incident(
        incident_id=UUID(int=rng.getrandbits(128)),
        incident_type=IncidentType.BAD_DEPLOYMENT_DB_EXHAUSTION.value,
        start_time=incident_start,
        end_time=incident_end,
        affected_services=["checkout-service", "api-gateway"],
        expected_symptoms=[
            "checkout-service p95 latency spike (>3000ms)",
            "checkout_db connection pool saturation (100/100 active connections)",
            "Database query timeout errors in checkout-service logs",
            "High 5xx error rate alert on checkout-service",
        ],
        distractor_event_ids=distractor_ids,
        difficulty=IncidentDifficulty.MEDIUM,
        severity=IncidentSeverity.SEV1,
        ground_truth=ground_truth,
    )

    return incident, bundle


# Register generator with global registry
register_incident_type(
    IncidentType.BAD_DEPLOYMENT_DB_EXHAUSTION.value,
    generate_bad_deployment_db_exhaustion_incident,
)
