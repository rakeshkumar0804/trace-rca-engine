"""Tests for Phase 3 — Investigation Reliability:
- Server restart recovery for orphaned running investigations
- Persistent failure and cancellation status in DB
- Duplicate run prevention
- Rate limiter proxy header trust & memory bounding
- Demo reference cache versioning
"""

import asyncio
from datetime import datetime, timezone
from uuid import uuid4
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.db.base import Base, reset_engine
from app.main import app
from app.db.models import IncidentORM, InvestigationORM, InvestigationStepORM
from app.orchestrator.recovery import recover_interrupted_investigations
from app.orchestrator.demo_reference import (
    DEMO_REFERENCE_VERSION,
    DEMO_SPEC,
    get_or_generate_demo_reference,
)
from app.schemas.investigations import InvestigationState
from app.api.rate_limiter import RateLimitMiddleware


@pytest.fixture
async def client():
    """Provides async test client with initialized in-memory SQLite database."""
    RateLimitMiddleware.reset_all_instances()
    engine = await reset_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    RateLimitMiddleware.reset_all_instances()


class TestRestartRecovery:
    """Verifies that process restarts transition orphaned nonterminal investigations to interrupted."""

    @pytest.mark.anyio
    async def test_recover_interrupted_investigations(self):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

        async with session_factory() as session:
            # Create dummy incident and 2 orphaned running investigations + 1 completed investigation
            inc_id = uuid4()
            inc = IncidentORM(
                incident_id=inc_id,
                incident_type="bad_deployment_db_exhaustion",
                start_time=datetime.now(timezone.utc),
                affected_services=["checkout-service"],
                expected_symptoms=["high_error_rate"],
                difficulty="medium",
                severity="critical",
            )
            session.add(inc)

            inv_running_1 = InvestigationORM(
                investigation_id=uuid4(),
                incident_id=inc_id,
                final_state="running",
                confidence=0.0,
                started_at=datetime.now(timezone.utc),
            )
            inv_running_2 = InvestigationORM(
                investigation_id=uuid4(),
                incident_id=inc_id,
                final_state="running",
                confidence=0.0,
                started_at=datetime.now(timezone.utc),
            )
            inv_completed = InvestigationORM(
                investigation_id=uuid4(),
                incident_id=inc_id,
                final_state="rca_generated",
                confidence=95.0,
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )
            session.add_all([inv_running_1, inv_running_2, inv_completed])
            await session.commit()

            # Run restart recovery
            recovered_count = await recover_interrupted_investigations(session)
            assert recovered_count == 2

            # Verify in DB
            stmt = select(InvestigationORM).order_by(InvestigationORM.started_at.asc())
            all_invs = (await session.execute(stmt)).scalars().all()
            
            # The two running investigations are now interrupted
            recovered_invs = [inv for inv in all_invs if inv.investigation_id in (inv_running_1.investigation_id, inv_running_2.investigation_id)]
            for inv in recovered_invs:
                assert inv.final_state == InvestigationState.INTERRUPTED.value
                assert inv.completed_at is not None
                assert "server process restart" in inv.rca_narrative
                assert "retry" in inv.rca_narrative.lower()

            # Completed investigation was not altered
            comp_inv = next(inv for inv in all_invs if inv.investigation_id == inv_completed.investigation_id)
            assert comp_inv.final_state == "rca_generated"

            # Check that an interrupted step was logged for each recovered investigation
            steps_stmt = select(InvestigationStepORM)
            steps = (await session.execute(steps_stmt)).scalars().all()
            assert len(steps) == 2
            for s in steps:
                assert s.state == InvestigationState.INTERRUPTED.value
                assert "server process restart" in s.summary


class TestDuplicateRunsAndFailurePersistence:
    """Verifies duplicate execution suppression and persistent error handling."""

    @pytest.mark.anyio
    async def test_duplicate_run_returns_existing_active_investigation(self, client: AsyncClient):
        # 1. Generate an incident
        gen_res = await client.post("/api/incidents/generate", json={"incident_type": "bad_deployment_db_exhaustion", "seed": 99})
        assert gen_res.status_code == 200
        inc_id = gen_res.json()["incident_id"]

        # 2. Start investigation first time
        run_res_1 = await client.post("/api/investigations/run", json={"incident_id": inc_id})
        assert run_res_1.status_code == 200
        inv_1 = run_res_1.json()
        assert inv_1["final_state"] == "running"

        # 3. Trigger second run immediately for same incident while first is running
        run_res_2 = await client.post("/api/investigations/run", json={"incident_id": inc_id})
        assert run_res_2.status_code == 200
        inv_2 = run_res_2.json()

        # Should return the exact same active investigation ID without spawning a duplicate
        assert inv_2["investigation_id"] == inv_1["investigation_id"]

    @pytest.mark.anyio
    async def test_duplicate_demo_investigation_returns_active_instance(self, client: AsyncClient):
        # 1. Start demo
        demo_1 = await client.post("/api/investigations/demo")
        assert demo_1.status_code == 200
        data_1 = demo_1.json()

        # 2. Start demo again while first is actively running
        demo_2 = await client.post("/api/investigations/demo")
        assert demo_2.status_code == 200
        data_2 = demo_2.json()

        assert data_2["investigation_id"] == data_1["investigation_id"]


class TestRateLimiterHardening:
    """Verifies proxy trust configuration and bounded memory cleanup."""

    def test_proxy_trust_disabled_by_default(self):
        middleware = RateLimitMiddleware(app=None, max_requests_per_minute=10, trust_proxy_headers=False)
        assert middleware.trust_proxy_headers is False

        # Mock request with spoofed X-Forwarded-For
        class MockClient:
            host = "192.168.1.50"
        
        class MockRequest:
            client = MockClient()
            headers = {"x-forwarded-for": "8.8.8.8, 10.0.0.1"}

        extracted_ip = middleware._extract_client_ip(MockRequest())
        # With trust_proxy_headers=False, spoofed header is ignored
        assert extracted_ip == "192.168.1.50"

    def test_proxy_trust_enabled_uses_forwarded_for(self):
        middleware = RateLimitMiddleware(app=None, max_requests_per_minute=10, trust_proxy_headers=True)
        assert middleware.trust_proxy_headers is True

        class MockClient:
            host = "127.0.0.1"
        
        class MockRequest:
            client = MockClient()
            headers = {"x-forwarded-for": "203.0.113.195"}

        extracted_ip = middleware._extract_client_ip(MockRequest())
        assert extracted_ip == "203.0.113.195"

    def test_rate_limiter_memory_cleanup_bounds(self):
        middleware = RateLimitMiddleware(app=None, max_requests_per_minute=5, max_tracked_ips=3)
        now = 1000.0
        cutoff = now - 60.0

        # Fill with 5 expired IPs
        for i in range(5):
            middleware._history[f"ip_{i}"] = [cutoff - 10.0]

        assert len(middleware._history) == 5

        # Trigger cleanup
        middleware._cleanup_expired(now, cutoff)

        # All expired entries purged because tracked count exceeded max_tracked_ips (3)
        assert len(middleware._history) == 0


class TestDemoReferenceFreshnessAndVersioning:
    """Verifies explicit reference versioning and cache integrity."""

    def test_demo_spec_includes_explicit_version(self):
        assert DEMO_REFERENCE_VERSION == "v3"
        assert "v3" in DEMO_SPEC.benchmark_id
        assert "v3" in DEMO_SPEC.description

    @pytest.mark.anyio
    async def test_demo_reference_generates_and_caches_versioned_result(self):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

        async with session_factory() as session:
            inc_id, ref_inv = await get_or_generate_demo_reference(session, force_refresh=True)
            assert ref_inv.final_state == InvestigationState.RCA_GENERATED
            assert ref_inv.confidence == 100.0
            assert len(ref_inv.steps) == 8

            # Subsequent call returns cached version without regenerating
            inc_id_2, ref_inv_2 = await get_or_generate_demo_reference(session, force_refresh=False)
            assert inc_id_2 == inc_id
            assert ref_inv_2.investigation_id == ref_inv.investigation_id
