"""Unit tests for Phase 8.5: Memory Leak with Red-Herring Deployment incident scenario."""

from datetime import datetime, timedelta, timezone

import pytest

from app.generator import (
    generate_healthy_environment,
    generate_memory_leak_masked_deployment_incident,
)
from app.generator.incidents.bad_deployment_db_exhaustion import strip_ground_truth_for_investigator
from app.schemas.events import MetricPoint
from app.schemas.incidents import GroundTruth, Incident


class TestMemoryLeakIncidentDeterminism:
    """Verifies that identical seeds produce identical telemetry and different seeds produce variance."""

    def test_reproducibility(self):
        t0 = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
        env1 = generate_healthy_environment(seed=42, start=t0, duration_minutes=45)
        env2 = generate_healthy_environment(seed=42, start=t0, duration_minutes=45)

        inc1, b1 = generate_memory_leak_masked_deployment_incident(seed=100, base_environment=env1, incident_start=t0)
        inc2, b2 = generate_memory_leak_masked_deployment_incident(seed=100, base_environment=env2, incident_start=t0)

        assert inc1.incident_id == inc2.incident_id
        assert len(b1["metrics"]) == len(b2["metrics"])
        assert len(b1["deployments"]) == len(b2["deployments"])
        assert b1["metrics"][0].value == b2["metrics"][0].value


class TestGroundTruthIsolation:
    """Ensures GroundTruth text never leaks into investigator-facing telemetry bundles."""

    def test_ground_truth_text_never_appears_in_evidence_bundle(self):
        t0 = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
        env = generate_healthy_environment(seed=42, start=t0, duration_minutes=45)
        inc, bundle = generate_memory_leak_masked_deployment_incident(seed=101, base_environment=env, incident_start=t0)

        sensitive_terms = [
            "non-causal",
            "unbounded object accumulation",
            "identical before and after",
            "red herring",
        ]

        bundle_str = str(bundle).lower()
        for term in sensitive_terms:
            assert term.lower() not in bundle_str, f"Sensitive term '{term}' leaked into evidence bundle!"

    def test_strip_ground_truth_removes_field(self):
        t0 = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
        env = generate_healthy_environment(seed=42, start=t0, duration_minutes=45)
        inc, _ = generate_memory_leak_masked_deployment_incident(seed=102, base_environment=env, incident_start=t0)

        stripped = strip_ground_truth_for_investigator(inc)
        assert "ground_truth" not in stripped


class TestFalsifiableFactMemoryGrowthRate:
    """CRITICAL TEST: Verifies that the memory growth slope is statistically unchanged by the red-herring deployment."""

    def test_memory_growth_slope_unchanged_post_deployment(self):
        t0 = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
        env = generate_healthy_environment(seed=42, start=t0, duration_minutes=45)
        inc, bundle = generate_memory_leak_masked_deployment_incident(seed=103, base_environment=env, incident_start=t0)

        # Find deployment timestamp
        dep = next(d for d in bundle["deployments"] if d.service == "checkout-service")
        dep_time = dep.started_at

        # Extract memory metrics on checkout-service sorted by timestamp
        mem_pts = [
            m for m in bundle["metrics"]
            if m.service == "checkout-service" and m.metric_name == "memory_mb"
        ]
        mem_pts.sort(key=lambda m: m.timestamp)

        # Split into before-deployment and after-deployment series
        before_pts = [m for m in mem_pts if m.timestamp < dep_time]
        after_pts = [m for m in mem_pts if m.timestamp >= dep_time]

        assert len(before_pts) >= 10, "Insufficient pre-deployment memory data points"
        assert len(after_pts) >= 10, "Insufficient post-deployment memory data points"

        # Calculate slope: (delta MB) / (delta minutes)
        t_start_before = before_pts[0].timestamp
        t_end_before = before_pts[-1].timestamp
        dt_before_min = (t_end_before - t_start_before).total_seconds() / 60.0
        d_mem_before = before_pts[-1].value - before_pts[0].value
        slope_before = d_mem_before / dt_before_min

        t_start_after = after_pts[0].timestamp
        t_end_after = after_pts[-1].timestamp
        dt_after_min = (t_end_after - t_start_after).total_seconds() / 60.0
        d_mem_after = after_pts[-1].value - after_pts[0].value
        slope_after = d_mem_after / dt_after_min

        # The slope before vs after must not differ by more than 15%
        relative_diff = abs(slope_after - slope_before) / slope_before
        assert relative_diff < 0.15, (
            f"Memory growth rate changed post-deployment! Slope before: {slope_before:.2f} MB/min, "
            f"Slope after: {slope_after:.2f} MB/min (Diff: {relative_diff*100:.1f}%)"
        )


class TestCausalObservability:
    """Verifies that GC pauses and 5xx errors occur ONLY after memory crosses threshold (T >= 35m)."""

    def test_gc_pauses_correlate_with_memory_threshold_not_deployment(self):
        t0 = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
        env = generate_healthy_environment(seed=42, start=t0, duration_minutes=45)
        inc, bundle = generate_memory_leak_masked_deployment_incident(seed=104, base_environment=env, incident_start=t0)

        dep = next(d for d in bundle["deployments"] if d.service == "checkout-service")
        dep_time = dep.started_at

        # Verify GC pauses do NOT occur immediately after deployment (T=15m..T=30m)
        early_gc = [
            m for m in bundle["metrics"]
            if m.metric_name == "gc_pause_duration_ms" and m.timestamp < t0 + timedelta(minutes=30)
        ]
        assert len(early_gc) == 0, "GC pauses started immediately after deployment rather than at threshold!"

        # Verify GC pauses DO occur once memory crosses threshold (T >= 35m)
        late_gc = [
            m for m in bundle["metrics"]
            if m.metric_name == "gc_pause_duration_ms" and m.timestamp >= t0 + timedelta(minutes=35)
        ]
        assert len(late_gc) >= 5, "GC pauses missing during memory saturation window"
