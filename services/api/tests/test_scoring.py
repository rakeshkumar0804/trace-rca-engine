import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from uuid import UUID, uuid4

import pytest

# Ensure app package is importable regardless of working directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.base import Base, get_db_session, reset_engine
from app.embeddings.ingest import ingest_incident_evidence
from app.embeddings.provider import DeterministicEmbeddingProvider
from app.generator import (
    generate_bad_deployment_db_exhaustion_incident,
    generate_healthy_environment,
)
from app.generator.config import SERVICE_TOPOLOGY
from app.hypotheses.candidate_generation import generate_candidate_hypotheses
from app.hypotheses.scoring import (
    ScoringContext,
    calculate_causal_fit,
    calculate_change_proximity,
    calculate_contradiction_penalty,
    calculate_evidence_support,
    calculate_system_dependency_fit,
    calculate_temporal_fit,
    calculate_unexplained_symptoms_penalty,
    rank_hypotheses,
    score_hypothesis,
)
from app.retrieval import get_changes_before, get_events_for_entity
from app.schemas.deployments import Deployment, DeploymentStatus, GitCommit
from app.schemas.events import EventSeverity, EventSource, NormalizedEvent
from app.schemas.hypotheses import EvidenceRef, Hypothesis, HypothesisScore, HypothesisStatus
from app.schemas.services import ServiceDependency
from app.timeline.engine import build_timeline


def _create_sample_hypothesis(title: str, description: str) -> Hypothesis:
    return Hypothesis(
        id=uuid4(),
        incident_id=uuid4(),
        title=title,
        description=description,
        status=HypothesisStatus.CANDIDATE,
        score=HypothesisScore(
            temporal_fit=0, causal_fit=0, evidence_support=0, system_dependency_fit=0,
            change_proximity=0, contradictory_evidence_penalty=0, unexplained_symptoms_penalty=0,
            final_score=0,
        ),
    )


class TestPureSubScoringFunctions:
    """1-2. Independent behavioral tests for all 7 sub-scoring functions with hand-crafted inputs."""

    def test_temporal_fit_scoring(self):
        hyp = _create_sample_hypothesis("Bad deployment", "Defect in release")
        onset = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)

        # Strong fit: event happened 2 minutes before symptoms
        strong_event = NormalizedEvent(
            id=uuid4(),
            timestamp=onset - timedelta(minutes=2),
            source=EventSource.DEPLOYMENT,
            entity="checkout-service",
            event_type="deployment",
            service="checkout-service",
            severity=EventSeverity.INFO,
            attributes={},
        )
        score_strong = calculate_temporal_fit(hyp, [strong_event], onset)

        # Weak fit: event happened 20 minutes AFTER symptoms already started
        weak_event = NormalizedEvent(
            id=uuid4(),
            timestamp=onset + timedelta(minutes=20),
            source=EventSource.DEPLOYMENT,
            entity="checkout-service",
            event_type="deployment",
            service="checkout-service",
            severity=EventSeverity.INFO,
            attributes={},
        )
        score_weak = calculate_temporal_fit(hyp, [weak_event], onset)

        # Baseline: empty events
        score_empty = calculate_temporal_fit(hyp, [], onset)

        assert score_strong > score_weak
        assert score_strong >= 18.0
        assert score_weak <= 2.0
        assert score_empty == 5.0

    def test_causal_fit_scoring(self):
        hyp_checkout = _create_sample_hypothesis("Checkout Defect", "checkout-service issue")
        hyp_isolated = _create_sample_hypothesis("Isolated Service Defect", "email-service issue")

        # Checkout is an affected service
        score_direct = calculate_causal_fit(hyp_checkout, SERVICE_TOPOLOGY, ["checkout-service", "api-gateway"])
        score_isolated = calculate_causal_fit(hyp_isolated, SERVICE_TOPOLOGY, ["checkout-service", "inventory-service"])

        assert score_direct > score_isolated
        assert score_direct == 20.0
        assert score_isolated <= 5.0

    def test_causal_fit_distance_decay_and_strength(self):
        """Verify distance decay: direct (20.0) > 1-hop hard (16.0) > 2-hop soft (1.44) > disconnected (0.0)."""
        hyp_checkout = _create_sample_hypothesis("Checkout Defect", "checkout-service issue")
        hyp_order = _create_sample_hypothesis("Order service failure", "order-service issue")
        hyp_notification = _create_sample_hypothesis("Notification failure", "notification-service issue")
        hyp_unrelated = _create_sample_hypothesis("Unrelated failure", "billing-service issue")

        affected = ["checkout-service"]

        score_0hop = calculate_causal_fit(hyp_checkout, SERVICE_TOPOLOGY, affected)
        score_1hop_hard = calculate_causal_fit(hyp_order, SERVICE_TOPOLOGY, affected)
        score_2hop_soft = calculate_causal_fit(hyp_notification, SERVICE_TOPOLOGY, affected)
        score_disconnected = calculate_causal_fit(hyp_unrelated, SERVICE_TOPOLOGY, affected)

        assert score_0hop == 20.0
        assert score_1hop_hard == 16.0
        assert score_2hop_soft < 3.0  # Decayed heavily due to 2 hops and soft dependency
        assert score_disconnected <= 2.0
        assert score_0hop > score_1hop_hard > score_2hop_soft >= score_disconnected

    def test_evidence_support_scoring(self):
        hyp = _create_sample_hypothesis("Database Saturation", "DB connection leak")

        # Diverse multi-source evidence (4 distinct sources: LOG, METRIC, DATABASE, ALERT)
        diverse_evidence = [
            NormalizedEvent(id=uuid4(), timestamp=datetime.now(timezone.utc), source=EventSource.LOG, entity="s1", event_type="e1", attributes={}),
            NormalizedEvent(id=uuid4(), timestamp=datetime.now(timezone.utc), source=EventSource.METRIC, entity="s1", event_type="e2", attributes={}),
            NormalizedEvent(id=uuid4(), timestamp=datetime.now(timezone.utc), source=EventSource.DATABASE, entity="s1", event_type="e3", attributes={}),
            NormalizedEvent(id=uuid4(), timestamp=datetime.now(timezone.utc), source=EventSource.ALERT, entity="s1", event_type="e4", attributes={}),
        ]
        score_diverse = calculate_evidence_support(hyp, diverse_evidence)

        # Single piece of evidence
        single_evidence = [
            NormalizedEvent(id=uuid4(), timestamp=datetime.now(timezone.utc), source=EventSource.LOG, entity="s1", event_type="e1", attributes={})
        ]
        score_single = calculate_evidence_support(hyp, single_evidence)

        # Empty evidence
        score_empty = calculate_evidence_support(hyp, [])

        assert score_diverse > score_single > score_empty
        assert score_diverse >= 15.0
        assert score_single <= 7.0
        assert score_empty == 0.0

    def test_system_dependency_fit_scoring(self):
        hyp_db = _create_sample_hypothesis("Database connection pool issue", "checkout_db saturation")
        hyp_unrelated = _create_sample_hypothesis("Auth service outage", "auth-service failure")

        # Checkout-service relies on checkout_db, but order-service doesn't call auth-service
        score_db = calculate_system_dependency_fit(hyp_db, SERVICE_TOPOLOGY, ["checkout-service"])
        score_unrelated = calculate_system_dependency_fit(hyp_unrelated, SERVICE_TOPOLOGY, ["order-service"])

        assert score_db > score_unrelated
        assert score_db >= 18.0
        assert score_unrelated <= 5.0

    def test_system_dependency_fit_distance_decay(self):
        """Verify topological distance decay in system_dependency_fit."""
        hyp_checkout = _create_sample_hypothesis("Checkout Defect", "checkout-service issue")
        hyp_order = _create_sample_hypothesis("Order service failure", "order-service issue")
        hyp_notification = _create_sample_hypothesis("Notification failure", "notification-service issue")

        affected = ["checkout-service"]

        score_0hop = calculate_system_dependency_fit(hyp_checkout, SERVICE_TOPOLOGY, affected)
        score_1hop = calculate_system_dependency_fit(hyp_order, SERVICE_TOPOLOGY, affected)
        score_2hop = calculate_system_dependency_fit(hyp_notification, SERVICE_TOPOLOGY, affected)

        assert score_0hop == 20.0
        assert score_1hop == 16.0
        assert score_2hop < 3.0
        assert score_0hop > score_1hop > score_2hop

    def test_change_proximity_scoring(self):
        hyp_deploy = _create_sample_hypothesis("Bad deployment to checkout-service", "Release v2.15.0")
        hyp_traffic = _create_sample_hypothesis("Organic traffic surge", "User load spike")
        onset = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)

        # Deployment 3 minutes prior
        recent_deployment = [
            Deployment(
                deployment_id=uuid4(),
                service="checkout-service",
                version="v2.15.0",
                commit_sha="abc12345",
                started_at=onset - timedelta(minutes=3),
                completed_at=onset - timedelta(minutes=1),
                environment="production",
                status=DeploymentStatus.SUCCESS,
            )
        ]

        # Deployment 3 hours prior
        old_deployment = [
            Deployment(
                deployment_id=uuid4(),
                service="checkout-service",
                version="v2.14.0",
                commit_sha="def67890",
                started_at=onset - timedelta(hours=3),
                completed_at=onset - timedelta(hours=3),
                environment="production",
                status=DeploymentStatus.SUCCESS,
            )
        ]

        score_recent = calculate_change_proximity(hyp_deploy, recent_deployment, [], onset)
        score_old = calculate_change_proximity(hyp_deploy, old_deployment, [], onset)
        score_traffic = calculate_change_proximity(hyp_traffic, recent_deployment, [], onset)

        assert score_recent > score_old
        assert score_recent > score_traffic
        assert score_recent >= 15.0
        assert score_old <= 2.0

    def test_contradiction_penalty_scoring(self):
        hyp = _create_sample_hypothesis("Auth service outage", "Auth service completely down")

        # Conflicting evidence: 2 pieces of evidence showing 100% normal operation
        contradicting = [
            NormalizedEvent(id=uuid4(), timestamp=datetime.now(timezone.utc), source=EventSource.LOG, entity="auth-service", event_type="health_ok", attributes={}),
            NormalizedEvent(id=uuid4(), timestamp=datetime.now(timezone.utc), source=EventSource.METRIC, entity="auth-service", event_type="error_rate_zero", attributes={}),
        ]

        penalty_high = calculate_contradiction_penalty(hyp, contradicting)
        penalty_none = calculate_contradiction_penalty(hyp, [])

        assert penalty_high > penalty_none
        assert penalty_high == 12.0
        assert penalty_none == 0.0

    def test_unexplained_symptoms_penalty_scoring(self):
        hyp_good = _create_sample_hypothesis("Checkout error and db timeout", "Explains 5xx and db timeout")
        symptoms = ["5xx_rate_high", "db_connection_timeout", "latency_p95_high"]

        # Explains all symptoms
        penalty_zero = calculate_unexplained_symptoms_penalty(hyp_good, symptoms, symptoms_explained=symptoms)
        
        # Explains no symptoms
        penalty_full = calculate_unexplained_symptoms_penalty(hyp_good, symptoms, symptoms_explained=[])

        # Explains 1 of 3 symptoms
        penalty_partial = calculate_unexplained_symptoms_penalty(hyp_good, symptoms, symptoms_explained=["5xx_rate_high"])

        assert penalty_full > penalty_partial > penalty_zero
        assert penalty_zero == 0.0
        assert penalty_full == 20.0
        assert round(penalty_partial, 1) == 13.3


class TestScoringAggregationAndRanking:
    """3-4. End-to-end scoring of candidate hypotheses on the Phase 3 sample incident and rank ordering."""

    def test_real_incident_candidate_scoring_and_ranking(self):
        async def run_test():
            test_db_url = "sqlite+aiosqlite:///:memory:"
            engine = await reset_engine(test_db_url)
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            start = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
            base_env = generate_healthy_environment(seed=42, start=start, duration_minutes=15)
            incident, bundle = generate_bad_deployment_db_exhaustion_incident(
                seed=42, base_environment=base_env, incident_start=start, duration_minutes=15
            )

            embedder = DeterministicEmbeddingProvider(dim=384)

            async with get_db_session() as session:
                await ingest_incident_evidence(session, incident, bundle, provider=embedder)
                timeline = await build_timeline(session, incident.incident_id)

                # 1. Generate candidate hypotheses
                candidates = await generate_candidate_hypotheses(incident.incident_id, timeline, session)
                assert len(candidates) >= 3

                # 2. Gather context for scoring
                deployments = [c for c in await get_changes_before(session, incident.incident_id, start + timedelta(minutes=15), lookback_minutes=30) if isinstance(c, Deployment)]
                commits = [c for c in await get_changes_before(session, incident.incident_id, start + timedelta(minutes=15), lookback_minutes=30) if isinstance(c, GitCommit)]
                
                checkout_events = await get_events_for_entity(session, incident.incident_id, "checkout-service", limit=50)

                supporting_map: dict[UUID, list[NormalizedEvent]] = {}
                symptoms_map: dict[UUID, list[str]] = {}

                for c in candidates:
                    text = f"{c.title} {c.description}".lower()
                    if "checkout" in text:
                        supporting_map[c.id] = checkout_events[:6]
                        symptoms_map[c.id] = incident.expected_symptoms
                    elif "database" in text:
                        supporting_map[c.id] = [e for e in checkout_events if e.source == EventSource.DATABASE][:3]
                        symptoms_map[c.id] = [s for s in incident.expected_symptoms if "db" in s or "database" in s]
                    elif "notification" in text:
                        # Notification is a downstream distractor service with no checkout error logs
                        supporting_map[c.id] = []
                        symptoms_map[c.id] = []
                    else:
                        supporting_map[c.id] = []
                        symptoms_map[c.id] = []

                context = ScoringContext(
                    symptom_onset_time=incident.start_time,
                    service_dependencies=SERVICE_TOPOLOGY,
                    affected_services=incident.affected_services,
                    all_observed_symptoms=incident.expected_symptoms,
                    deployments=deployments,
                    commits=commits,
                    supporting_events_map=supporting_map,
                    symptoms_explained_map=symptoms_map,
                )

                # 3. Score all candidates
                scored_candidates: list[Hypothesis] = []
                for c in candidates:
                    score = score_hypothesis(c, context)
                    assert 0.0 <= score.final_score <= 100.0
                    updated = c.model_copy(update={"score": score})
                    scored_candidates.append(updated)

                # 4. Rank candidates
                ranked = rank_hypotheses(scored_candidates)

                # Exactly one hypothesis (the top one) has INVESTIGATING status
                investigating_list = [h for h in ranked if h.status == HypothesisStatus.INVESTIGATING]
                assert len(investigating_list) == 1
                assert investigating_list[0] == ranked[0]

                # Other hypotheses remain CANDIDATE
                for other in ranked[1:]:
                    assert other.status == HypothesisStatus.CANDIDATE

                # Strict descending score order
                for i in range(len(ranked) - 1):
                    assert ranked[i].score.final_score >= ranked[i + 1].score.final_score

                # The "Bad deployment to checkout-service" hypothesis must score meaningfully higher
                # than both notification distractor and traffic spike
                deployment_hyp = next(h for h in ranked if "deployment" in h.title.lower() and "checkout" in h.title.lower())
                notification_hyp = next(h for h in ranked if "notification" in h.title.lower())
                traffic_hyp = next(h for h in ranked if "traffic" in h.title.lower())

                # Checkout deployment is Rank 1
                assert ranked[0].id == deployment_hyp.id

                # The score gap between checkout deployment and notification distractor must be > 35 points
                assert deployment_hyp.score.final_score > notification_hyp.score.final_score + 35.0, (
                    f"Expected deployment score ({deployment_hyp.score.final_score}) to be > 35 points higher than notification distractor ({notification_hyp.score.final_score})"
                )

                assert deployment_hyp.score.final_score > traffic_hyp.score.final_score + 35.0

            await reset_engine()

        asyncio.run(run_test())
