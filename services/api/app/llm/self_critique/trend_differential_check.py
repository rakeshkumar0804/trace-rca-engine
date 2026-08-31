"""Deterministic trend differential falsification check.

Evaluates whether a deployment hypothesis is contradicted by a pre-existing continuous metric trend
(e.g., progressive memory leak) that started before the deployment and whose growth rate (slope)
remained statistically unchanged across the deployment boundary.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DeploymentORM, MetricORM
from app.schemas.events import EventSeverity, EventSource, NormalizedEvent
from app.schemas.hypotheses import EvidenceRef, Hypothesis
from ..schemas import EvidenceVerdict


def compute_linear_slope(points: Sequence[tuple[datetime, float]]) -> float:
    """Computes the linear regression slope (units per minute) for a time series of (datetime, value)."""
    if len(points) < 2:
        return 0.0

    t0 = points[0][0]
    xs = [(p[0] - t0).total_seconds() / 60.0 for p in points]
    ys = [p[1] for p in points]
    n = len(points)

    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xy = sum(x * y for x, y in zip(xs, ys))
    sum_xx = sum(x * x for x in xs)

    denominator = (n * sum_xx) - (sum_x * sum_x)
    if abs(denominator) < 1e-9:
        # Fallback to simple endpoint slope
        dt_min = (points[-1][0] - points[0][0]).total_seconds() / 60.0
        return (points[-1][1] - points[0][1]) / dt_min if dt_min > 0 else 0.0

    return ((n * sum_xy) - (sum_x * sum_y)) / denominator


@dataclass
class TrendDifferentialAnalysis:
    """Outcome of comparing metric growth rate before vs after a deployment timestamp."""
    is_applicable: bool
    service: str
    metric_name: str
    slope_before: float
    slope_after: float
    relative_difference: float
    is_trend_unchanged: bool
    reasoning: str
    pre_deployment_events: list[NormalizedEvent]
    post_deployment_events: list[NormalizedEvent]


def analyze_metric_trend_across_boundary(
    metric_events: list[NormalizedEvent],
    deployment_time: datetime,
    tolerance: float = 0.20,
) -> TrendDifferentialAnalysis:
    """Analyzes whether a metric slope changed across the deployment boundary.
    
    If slope_before > 0.05 and relative difference <= tolerance (20%), the deployment is non-causal.
    """
    if not metric_events:
        return TrendDifferentialAnalysis(
            is_applicable=False,
            service="",
            metric_name="",
            slope_before=0.0,
            slope_after=0.0,
            relative_difference=0.0,
            is_trend_unchanged=False,
            reasoning="No metric events provided for trend differential check.",
            pre_deployment_events=[],
            post_deployment_events=[],
        )

    # Sort events by timestamp
    sorted_events = sorted(metric_events, key=lambda e: e.timestamp)
    pre_events = [e for e in sorted_events if e.timestamp < deployment_time]
    post_events = [e for e in sorted_events if e.timestamp >= deployment_time]

    if len(pre_events) < 3 or len(post_events) < 3:
        return TrendDifferentialAnalysis(
            is_applicable=False,
            service=sorted_events[0].service or "",
            metric_name=sorted_events[0].event_type,
            slope_before=0.0,
            slope_after=0.0,
            relative_difference=0.0,
            is_trend_unchanged=False,
            reasoning="Insufficient data points before or after deployment boundary.",
            pre_deployment_events=pre_events,
            post_deployment_events=post_events,
        )

    # Extract (datetime, value) points
    def _extract_val(e: NormalizedEvent) -> float:
        v = e.attributes.get("value", 0.0)
        return float(v) if isinstance(v, (int, float)) else 0.0

    pts_before = [(e.timestamp, _extract_val(e)) for e in pre_events]
    pts_after = [(e.timestamp, _extract_val(e)) for e in post_events]

    slope_before = compute_linear_slope(pts_before)
    slope_after = compute_linear_slope(pts_after)

    # If before-deployment slope was non-trivial (> 0.05 units/min, e.g. active memory growth)
    if slope_before > 0.05:
        rel_diff = abs(slope_after - slope_before) / slope_before
        if rel_diff <= tolerance:
            reasoning = (
                f"Deterministic Trend Differential Check: {sorted_events[0].event_type} growth rate before deployment was "
                f"{slope_before:.2f} units/min. Rate after deployment was {slope_after:.2f} units/min "
                f"(relative diff {rel_diff * 100:.1f}% <= {tolerance * 100:.0f}%). "
                f"No statistically significant change — deployment did not affect the pre-existing trend."
            )
            return TrendDifferentialAnalysis(
                is_applicable=True,
                service=sorted_events[0].service or "",
                metric_name=sorted_events[0].event_type,
                slope_before=slope_before,
                slope_after=slope_after,
                relative_difference=rel_diff,
                is_trend_unchanged=True,
                reasoning=reasoning,
                pre_deployment_events=pre_events,
                post_deployment_events=post_events,
            )
        else:
            reasoning = (
                f"Deterministic Trend Differential Check: {sorted_events[0].event_type} growth rate changed post-deployment "
                f"(before: {slope_before:.2f}, after: {slope_after:.2f}, relative diff: {rel_diff * 100:.1f}%)."
            )
            return TrendDifferentialAnalysis(
                is_applicable=True,
                service=sorted_events[0].service or "",
                metric_name=sorted_events[0].event_type,
                slope_before=slope_before,
                slope_after=slope_after,
                relative_difference=rel_diff,
                is_trend_unchanged=False,
                reasoning=reasoning,
                pre_deployment_events=pre_events,
                post_deployment_events=post_events,
            )
    else:
        # Before deployment was flat
        rel_diff = 1.0 if slope_after > 0.1 else 0.0
        reasoning = (
            f"Deterministic Trend Differential Check: Metric was flat before deployment ({slope_before:.2f}) "
            f"and slope after was {slope_after:.2f}."
        )
        return TrendDifferentialAnalysis(
            is_applicable=True,
            service=sorted_events[0].service or "",
            metric_name=sorted_events[0].event_type,
            slope_before=slope_before,
            slope_after=slope_after,
            relative_difference=rel_diff,
            is_trend_unchanged=False,
            reasoning=reasoning,
            pre_deployment_events=pre_events,
            post_deployment_events=post_events,
        )


async def evaluate_trend_differential_falsification(
    active_hypothesis: Hypothesis,
    all_candidate_hypotheses: list[Hypothesis],
    session: AsyncSession,
    incident_id: UUID,
    tolerance: float = 0.20,
) -> tuple[EvidenceVerdict | None, NormalizedEvent | None]:
    """Evaluates the mandatory deterministic trend differential falsification check if trigger condition is met.
    
    Trigger Condition:
      1. active_hypothesis cites a Deployment as causal trigger.
      2. all_candidate_hypotheses contains a competing hypothesis based on a continuous MetricPoint series (e.g. memory leak).
    
    Returns:
      tuple[EvidenceVerdict | None, NormalizedEvent | None]:
        - EvidenceVerdict with verdict="contradicts" (or "supports") and verdict_source="deterministic_trend_check".
        - NormalizedEvent to attach as evidence (or None if check is not applicable).
    """
    # 1. Check Trigger Condition
    active_title = active_hypothesis.title.lower()
    is_deployment = "deployment" in active_title or any(e.evidence_type == EventSource.DEPLOYMENT for e in active_hypothesis.supporting_evidence)
    if not is_deployment:
        return None, None

    # Check for competing metric/resource/leak hypothesis
    has_competing_metric = False
    for h in all_candidate_hypotheses:
        if h.id == active_hypothesis.id:
            continue
        h_title = h.title.lower()
        if any(k in h_title for k in ["memory", "heap", "leak", "resource", "exhaustion", "garbage collection"]):
            has_competing_metric = True
            break
        if any(e.evidence_type == EventSource.METRIC for e in h.supporting_evidence):
            has_competing_metric = True
            break

    if not has_competing_metric:
        return None, None

    # 2. Retrieve Deployment Timestamp
    dep_stmt = (
        select(DeploymentORM)
        .where(DeploymentORM.incident_id == incident_id)
        .order_by(DeploymentORM.started_at.asc())
    )
    deployments = (await session.execute(dep_stmt)).scalars().all()
    if not deployments:
        return None, None

    # Find deployment relevant to active hypothesis or target service
    target_dep = deployments[0]
    for d in deployments:
        if d.service in active_title or str(d.deployment_id) in str(active_hypothesis.supporting_evidence):
            target_dep = d
            break

    deployment_time = target_dep.started_at
    target_service = target_dep.service

    # 3. Retrieve Metric Series for target service
    metric_stmt = (
        select(MetricORM)
        .where(
            MetricORM.incident_id == incident_id,
            MetricORM.service == target_service,
            MetricORM.metric_name.in_(["memory_mb", "jvm_heap_used_mb", "heap_usage_mb", "heap_used_pct"]),
        )
        .order_by(MetricORM.timestamp.asc())
    )
    metric_rows = (await session.execute(metric_stmt)).scalars().all()
    if not metric_rows:
        return None, None

    # Convert to NormalizedEvent objects
    norm_metric_events = [
        NormalizedEvent(
            id=m.id,
            timestamp=m.timestamp,
            source=EventSource.METRIC,
            entity=m.service,
            event_type=m.metric_name,
            service=m.service,
            severity=EventSeverity.INFO,
            attributes={"value": m.value, "unit": m.unit, "service": m.service},
        )
        for m in metric_rows
    ]

    # 4. Analyze Trend Differential
    analysis = analyze_metric_trend_across_boundary(
        metric_events=norm_metric_events,
        deployment_time=deployment_time,
        tolerance=tolerance,
    )

    if not analysis.is_applicable:
        return None, None

    if analysis.is_trend_unchanged:
        # Strong contradiction: trend was already progressing before deployment
        earliest_pre_evt = analysis.pre_deployment_events[0]
        verdict = EvidenceVerdict(
            question="Deterministic Trend Check: Did deployment initiate or accelerate pre-existing metric growth?",
            evidence_ids_cited=[earliest_pre_evt.id],
            verdict="contradicts",
            reasoning=analysis.reasoning,
            verdict_source="deterministic_trend_check",
        )
        return verdict, earliest_pre_evt
    else:
        # Supporting: slope changed post-deployment
        first_post_evt = analysis.post_deployment_events[0]
        verdict = EvidenceVerdict(
            question="Deterministic Trend Check: Did deployment initiate or accelerate metric growth?",
            evidence_ids_cited=[first_post_evt.id],
            verdict="supports",
            reasoning=analysis.reasoning,
            verdict_source="deterministic_trend_check",
        )
        return verdict, first_post_evt
