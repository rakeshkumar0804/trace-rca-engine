"""Unit tests for deterministic trend differential falsification check."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.llm.self_critique.trend_differential_check import (
    analyze_metric_trend_across_boundary,
    compute_linear_slope,
)
from app.schemas.events import EventSeverity, EventSource, NormalizedEvent


class TestTrendDifferentialPureMath:
    """Tests pure slope computation and boundary analysis with synthetic time series."""

    def test_compute_linear_slope_perfect_line(self):
        t0 = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
        # 10 MB per minute: (0m, 100), (1m, 110), (2m, 120), (3m, 130)
        pts = [
            (t0 + timedelta(minutes=i), 100.0 + (i * 10.0))
            for i in range(10)
        ]
        slope = compute_linear_slope(pts)
        assert abs(slope - 10.0) < 1e-4

    def test_trend_unchanged_across_deployment_boundary(self):
        t0 = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
        dep_time = t0 + timedelta(minutes=15)
        # 33.3 MB per minute constant slope across all 45 minutes
        events = [
            NormalizedEvent(
                id=uuid4(),
                timestamp=t0 + timedelta(minutes=i),
                source=EventSource.METRIC,
                entity="checkout-service",
                event_type="memory_mb",
                service="checkout-service",
                severity=EventSeverity.INFO,
                attributes={"value": 400.0 + (i * 33.33)},
            )
            for i in range(45)
        ]

        analysis = analyze_metric_trend_across_boundary(events, dep_time, tolerance=0.20)
        assert analysis.is_applicable is True
        assert analysis.is_trend_unchanged is True
        assert analysis.relative_difference < 0.05
        assert "No statistically significant change" in analysis.reasoning

    def test_trend_changed_across_deployment_boundary(self):
        t0 = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
        dep_time = t0 + timedelta(minutes=15)
        # Flat before deployment (slope ~0.0), steep growth after deployment (slope ~50.0)
        events = []
        for i in range(15):
            events.append(
                NormalizedEvent(
                    id=uuid4(),
                    timestamp=t0 + timedelta(minutes=i),
                    source=EventSource.METRIC,
                    entity="checkout-service",
                    event_type="memory_mb",
                    service="checkout-service",
                    severity=EventSeverity.INFO,
                    attributes={"value": 400.0},
                )
            )
        for i in range(15, 45):
            events.append(
                NormalizedEvent(
                    id=uuid4(),
                    timestamp=t0 + timedelta(minutes=i),
                    source=EventSource.METRIC,
                    entity="checkout-service",
                    event_type="memory_mb",
                    service="checkout-service",
                    severity=EventSeverity.INFO,
                    attributes={"value": 400.0 + ((i - 15) * 50.0)},
                )
            )

        analysis = analyze_metric_trend_across_boundary(events, dep_time, tolerance=0.20)
        assert analysis.is_applicable is True
        assert analysis.is_trend_unchanged is False
        assert "flat before deployment" in analysis.reasoning.lower() or "growth rate changed" in analysis.reasoning.lower()


class TestTrendDifferentialIntegration:
    """Verifies that evaluate_trend_differential_falsification fires on deployments and penalizes them when memory leak is present."""

    @pytest.mark.anyio
    async def test_trend_check_penalizes_deployment_hypothesis_on_memory_leak_incident(self):
        from app.db.base import Base, reset_engine, get_db_session
        from app.evaluation.benchmark_incidents import instantiate_benchmark_incident, BenchmarkIncidentSpec
        from app.generator.incidents.incident_types import IncidentType
        from app.embeddings.ingest import ingest_incident_evidence
        from app.embeddings.provider import DeterministicEmbeddingProvider
        from app.hypotheses.candidate_generation import generate_candidate_hypotheses
        from app.timeline.engine import build_timeline
        from app.llm.self_critique.trend_differential_check import evaluate_trend_differential_falsification

        engine = await reset_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        spec = BenchmarkIncidentSpec(
            benchmark_id="test-mem",
            incident_type=IncidentType.MEMORY_LEAK_MASKED_DEPLOYMENT.value,
            seed=21,
            duration_minutes=45,
            description="Test memory leak",
        )
        incident, bundle = instantiate_benchmark_incident(spec)
        embedder = DeterministicEmbeddingProvider(dim=384)

        async with get_db_session() as session:
            await ingest_incident_evidence(session, incident, bundle, provider=embedder)
            timeline = await build_timeline(session, incident.incident_id)
            candidates = await generate_candidate_hypotheses(incident.incident_id, timeline, session)

            dep_hyp = next(h for h in candidates if "deployment" in h.title.lower() and "checkout" in h.title.lower())
            mem_hyp = next(h for h in candidates if "memory" in h.title.lower() or "resource" in h.title.lower())

            # 1. Run check on deployment hypothesis
            det_verdict, det_event = await evaluate_trend_differential_falsification(
                active_hypothesis=dep_hyp,
                all_candidate_hypotheses=candidates,
                session=session,
                incident_id=incident.incident_id,
                tolerance=0.20,
            )
            assert det_verdict is not None
            assert det_verdict.verdict == "contradicts"
            assert det_verdict.verdict_source == "deterministic_trend_check"
            assert "No statistically significant change" in det_verdict.reasoning

            # 2. Run check on memory leak hypothesis (must NOT be triggered / penalized)
            mem_verdict, mem_event = await evaluate_trend_differential_falsification(
                active_hypothesis=mem_hyp,
                all_candidate_hypotheses=candidates,
                session=session,
                incident_id=incident.incident_id,
                tolerance=0.20,
            )
            assert mem_verdict is None
            assert mem_event is None
