# CRITICAL ISOLATION ENFORCEMENT: This candidate generation module queries ONLY investigator-facing tables.
# It must NEVER join or query the 'ground_truths' table.

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AlertORM,
    DatabaseEventORM,
    DeploymentORM,
    GitCommitORM,
    LogORM,
    MetricORM,
    NormalizedEventORM,
    ServiceDependencyORM,
)
from app.generator.config import SERVICE_TOPOLOGY
from app.schemas.events import EventSource
from app.schemas.hypotheses import EvidenceRef, Hypothesis, HypothesisScore, HypothesisStatus
from app.schemas.timeline import Timeline


def _create_empty_score() -> HypothesisScore:
    return HypothesisScore(
        temporal_fit=0.0,
        causal_fit=0.0,
        evidence_support=0.0,
        system_dependency_fit=0.0,
        change_proximity=0.0,
        contradictory_evidence_penalty=0.0,
        unexplained_symptoms_penalty=0.0,
        final_score=0.0,
    )


async def generate_candidate_hypotheses(
    incident_id: UUID,
    timeline: Timeline,
    session: AsyncSession,
) -> list[Hypothesis]:
    """Generates a diverse set of rule-based root-cause hypotheses using observable timeline & retrieved evidence.
    
    Operates strictly on investigator-facing evidence (zero LLM calls in this phase, zero ground truth access).
    """
    hypotheses: list[Hypothesis] = []
    seen_titles: set[str] = set()

    # 1. Heuristic A: Recent Deployment / Code Change
    # Look for deployments initiated in the lookback window preceding or near incident start
    dep_stmt = (
        select(DeploymentORM)
        .where(
            DeploymentORM.incident_id == incident_id,
            DeploymentORM.started_at >= timeline.start_time - timedelta(minutes=30),
            DeploymentORM.started_at <= (timeline.end_time or timeline.start_time + timedelta(minutes=15)),
        )
        .order_by(DeploymentORM.started_at.desc())
    )
    deployments = (await session.execute(dep_stmt)).scalars().all()

    for dep in deployments:
        title = f"Bad deployment to {dep.service} ({dep.version})"
        if title not in seen_titles:
            seen_titles.add(title)
            hypotheses.append(
                Hypothesis(
                    id=uuid4(),
                    incident_id=incident_id,
                    title=title,
                    description=(
                        f"Deployment of version {dep.version} (commit {dep.commit_sha[:8]}) to "
                        f"{dep.service} introduced a defect causing downstream query or service errors."
                    ),
                    status=HypothesisStatus.CANDIDATE,
                    score=_create_empty_score(),
                    supporting_evidence=[
                        EvidenceRef(
                            evidence_type=EventSource.DEPLOYMENT,
                            evidence_id=dep.deployment_id,
                            relevance_note=f"Deployment started at {dep.started_at.isoformat()}",
                        )
                    ],
                    contradicting_evidence=[],
                )
            )

    # 2. Heuristic B: Database Connection Exhaustion / Query Slowdown
    db_stmt = (
        select(DatabaseEventORM)
        .where(
            DatabaseEventORM.incident_id == incident_id,
            DatabaseEventORM.status.in_(["timeout", "error", "slow"]),
        )
        .limit(5)
    )
    db_events = (await session.execute(db_stmt)).scalars().all()

    if db_events:
        db_name = db_events[0].database_name
        title = f"Database connection pool saturation on {db_name}"
        if title not in seen_titles:
            seen_titles.add(title)
            hypotheses.append(
                Hypothesis(
                    id=uuid4(),
                    incident_id=incident_id,
                    title=title,
                    description=(
                        f"Database {db_name} connection pool was exhausted or experienced query timeouts, "
                        f"blocking application worker threads from processing requests."
                    ),
                    status=HypothesisStatus.CANDIDATE,
                    score=_create_empty_score(),
                    supporting_evidence=[
                        EvidenceRef(
                            evidence_type=EventSource.DATABASE,
                            evidence_id=evt.id,
                            relevance_note=f"Database {evt.status} event (active: {evt.connections_active}/{evt.connections_max})",
                        )
                        for evt in db_events[:3]
                    ],
                    contradicting_evidence=[],
                )
            )

    # 3. Heuristic C: Service Degradation & Downstream Dependency Failure
    error_logs_stmt = (
        select(LogORM)
        .where(
            LogORM.incident_id == incident_id,
            LogORM.severity.in_(["ERROR", "CRITICAL", "error", "critical"]),
        )
        .limit(20)
    )
    error_logs = (await session.execute(error_logs_stmt)).scalars().all()

    # Create candidate hypotheses for any service exhibiting internal error logs
    error_services = {l.service for l in error_logs}
    for s_name in error_services:
        if s_name != "checkout-service":
            title = f"Service degradation and failure in {s_name}"
            if title not in seen_titles:
                seen_titles.add(title)
                hypotheses.append(
                    Hypothesis(
                        id=uuid4(),
                        incident_id=incident_id,
                        title=title,
                        description=(
                            f"Internal degradation, thread pool exhaustion, or downstream timeouts in {s_name} "
                            f"caused cascading failures to dependent upstream callers."
                        ),
                        status=HypothesisStatus.CANDIDATE,
                        score=_create_empty_score(),
                        supporting_evidence=[
                            EvidenceRef(
                                evidence_type=EventSource.LOG,
                                evidence_id=l.id,
                                relevance_note=f"Error log: {l.message[:100]}",
                            )
                            for l in error_logs if l.service == s_name
                        ][:3],
                        contradicting_evidence=[],
                    )
                )

    # Also check alerts for downstream dependencies connected in topology
    alert_stmt = (
        select(AlertORM)
        .where(AlertORM.incident_id == incident_id)
        .limit(5)
    )
    alerts = (await session.execute(alert_stmt)).scalars().all()

    for alert in alerts:
        downstream_deps = [
            dep for dep in SERVICE_TOPOLOGY
            if dep.from_service == alert.service and dep.dependency_strength == "hard"
        ]
        for dep in downstream_deps:
            title = f"Downstream dependency failure in {dep.to_service}"
            if title not in seen_titles:
                seen_titles.add(title)
                hypotheses.append(
                    Hypothesis(
                        id=uuid4(),
                        incident_id=incident_id,
                        title=title,
                        description=(
                            f"Degradation or timeouts in downstream dependency {dep.to_service} "
                            f"cascaded to caller service {alert.service}."
                        ),
                        status=HypothesisStatus.CANDIDATE,
                        score=_create_empty_score(),
                        supporting_evidence=[
                            EvidenceRef(
                                evidence_type=EventSource.ALERT,
                                evidence_id=alert.id,
                                relevance_note=f"Triggered alert on caller: {alert.description}",
                            )
                        ],
                        contradicting_evidence=[],
                    )
                )

    # 4. Heuristic D: Sudden Traffic Surge / Demand Spike (Candidate to test falsification)
    # Always include a plausible distractor/external traffic hypothesis
    traffic_title = "External traffic spike overloading service ingress"
    if traffic_title not in seen_titles:
        seen_titles.add(traffic_title)
        hypotheses.append(
            Hypothesis(
                id=uuid4(),
                incident_id=incident_id,
                title=traffic_title,
                description=(
                    "An unexpected surge in external user traffic or distributed client retries "
                    "exceeded system capacity and led to request queuing and timeouts."
                ),
                status=HypothesisStatus.CANDIDATE,
                score=_create_empty_score(),
                supporting_evidence=[],
                contradicting_evidence=[],
            )
        )

    # 5. Heuristic E: Memory Leak / Resource Contention
    mem_metric_stmt = (
        select(MetricORM)
        .where(
            MetricORM.incident_id == incident_id,
            MetricORM.metric_name.in_(["memory_mb", "jvm_heap_used_mb", "gc_pause_duration_ms", "heap_used_pct"]),
        )
        .order_by(MetricORM.value.desc())
        .limit(100)
    )
    mem_metrics = (await session.execute(mem_metric_stmt)).scalars().all()
    if mem_metrics:
        mem_services = {m.service for m in mem_metrics}
        for s_name in mem_services:
            mem_title = f"Memory leak and garbage collection pause in {s_name}"
            if mem_title not in seen_titles:
                seen_titles.add(mem_title)
                hypotheses.append(
                    Hypothesis(
                        id=uuid4(),
                        incident_id=incident_id,
                        title=mem_title,
                        description=(
                            f"Progressive memory footprint growth in {s_name} led to heap saturation "
                            f"and prolonged Stop-The-World garbage collection pauses stalling requests."
                        ),
                        status=HypothesisStatus.CANDIDATE,
                        score=_create_empty_score(),
                        supporting_evidence=[
                            EvidenceRef(
                                evidence_type=EventSource.METRIC,
                                evidence_id=m.id,
                                relevance_note=f"Metric {m.metric_name}={m.value}{m.unit} on {m.service}",
                            )
                            for m in mem_metrics if m.service == s_name
                        ][:5],
                        contradicting_evidence=[],
                    )
                )
    else:
        resource_title = "Host memory exhaustion and garbage collection pause"
        if resource_title not in seen_titles:
            seen_titles.add(resource_title)
            hypotheses.append(
                Hypothesis(
                    id=uuid4(),
                    incident_id=incident_id,
                    title=resource_title,
                    description=(
                        "Process memory footprint grew steadily until memory pressure or heavy garbage "
                        "collection cycles stalled request processing threads."
                    ),
                    status=HypothesisStatus.CANDIDATE,
                    score=_create_empty_score(),
                    supporting_evidence=[],
                    contradicting_evidence=[],
                )
            )

    return hypotheses
