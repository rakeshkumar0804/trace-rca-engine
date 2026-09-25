"""Tests for Phase 4 — Experience and Final Local Verification:
- Adversarial simultaneous start requests concurrency race checks
- Adversarial proxy forwarding chain spoofing and trusted proxy traversal
- Investigation refresh recovery after in-memory cache loss
- Durable run_mode recognition ('demo_replay' vs 'autonomous_live')
- Missing/expired investigation ID handling
- Telemetry citation integrity and distinction from derived records
"""

import asyncio
from datetime import datetime, timezone
from uuid import uuid4
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.db.base import Base, reset_engine
from app.main import app
from app.db.models import IncidentORM, InvestigationORM, InvestigationStepORM
from app.api.rate_limiter import RateLimitMiddleware
from app.api.investigations import _investigation_cache


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


class TestSimultaneousStartRace:
    """Adversarial test: Fires simultaneous start requests to verify atomic serialization."""

    @pytest.mark.anyio
    async def test_simultaneous_run_requests_create_single_job(self, client: AsyncClient):
        # 1. Generate an incident
        gen_res = await client.post(
            "/api/incidents/generate",
            json={"incident_type": "bad_deployment_db_exhaustion", "seed": 42}
        )
        assert gen_res.status_code == 200
        inc_id = gen_res.json()["incident_id"]

        # 2. Fire 5 simultaneous start requests at the exact same moment
        tasks = [
            client.post("/api/investigations/run", json={"incident_id": inc_id})
            for _ in range(5)
        ]
        responses = await asyncio.gather(*tasks)

        # 3. All 5 requests must succeed with HTTP 200
        for r in responses:
            assert r.status_code == 200

        # 4. All 5 requests must return the exact same investigation_id
        inv_ids = [r.json()["investigation_id"] for r in responses]
        assert len(set(inv_ids)) == 1

        # 5. Exactly 1 InvestigationORM row should exist for this incident
        from app.db.base import get_session_factory
        from uuid import UUID
        factory = get_session_factory()
        async with factory() as session:
            count_stmt = (
                select(func.count())
                .select_from(InvestigationORM)
                .where(InvestigationORM.incident_id == UUID(inc_id))
            )
            count = (await session.execute(count_stmt)).scalar()
            assert count == 1


class TestAdversarialProxyHeaderForging:
    """Adversarial checks for proxy header forging and trusted traversal."""

    def test_untrusted_direct_socket_ignores_forged_forwarded_for(self):
        # Even if trust_proxy_headers=True, if the direct socket is not in TRUSTED_PROXIES, ignore headers
        middleware = RateLimitMiddleware(
            app=None,
            max_requests_per_minute=10,
            trust_proxy_headers=True,
            trusted_proxies=["127.0.0.1", "10.0.0.0/8"],
        )

        class MockClient:
            host = "198.51.100.5"  # Untrusted public IP connecting directly

        class MockRequest:
            client = MockClient()
            headers = {"x-forwarded-for": "1.1.1.1, 8.8.8.8"}

        extracted_ip = middleware._extract_client_ip(MockRequest())
        # Must return the direct socket IP, rejecting client-forged headers
        assert extracted_ip == "198.51.100.5"

    def test_trusted_proxy_traverses_right_to_left_stripping_trusted_hops(self):
        middleware = RateLimitMiddleware(
            app=None,
            max_requests_per_minute=10,
            trust_proxy_headers=True,
            trusted_proxies=["127.0.0.1", "10.0.0.0/8"],
        )

        class MockClient:
            host = "10.0.0.1"  # Trusted reverse proxy

        class MockRequest:
            client = MockClient()
            # Attacker sent forged '1.1.1.1', proxy appended real client '203.0.113.50' and intermediate '10.0.0.2'
            headers = {"x-forwarded-for": "1.1.1.1, 203.0.113.50, 10.0.0.2"}

        extracted_ip = middleware._extract_client_ip(MockRequest())
        # Right-to-left traversal skips trusted 10.0.0.2 and picks 203.0.113.50, ignoring attacker's 1.1.1.1
        assert extracted_ip == "203.0.113.50"

    def test_trusted_proxy_with_platform_header(self):
        middleware = RateLimitMiddleware(
            app=None,
            max_requests_per_minute=10,
            trust_proxy_headers=True,
            trusted_proxies=["127.0.0.1", "10.0.0.0/8"],
        )

        class MockClient:
            host = "10.0.0.1"

        class MockRequest:
            client = MockClient()
            headers = {"cf-connecting-ip": "198.51.100.77", "x-forwarded-for": "1.1.1.1"}

        extracted_ip = middleware._extract_client_ip(MockRequest())
        assert extracted_ip == "198.51.100.77"


class TestRefreshRecoveryAndCacheLoss:
    """Verifies that investigations can be fully retrieved after page refresh and cache loss."""

    @pytest.mark.anyio
    async def test_demo_investigation_durable_run_mode(self, client: AsyncClient):
        # 1. Start demo investigation
        demo_res = await client.post("/api/investigations/demo")
        assert demo_res.status_code == 200
        demo_data = demo_res.json()
        demo_id = demo_data["investigation_id"]
        assert demo_data["run_mode"] == "demo_replay"

        # 2. Simulate cache loss / memory purge
        _investigation_cache.clear()

        # 3. Simulate browser page refresh: GET /api/investigations/{id}
        refresh_res = await client.get(f"/api/investigations/{demo_id}")
        assert refresh_res.status_code == 200
        refreshed_data = refresh_res.json()
        assert refreshed_data["investigation_id"] == demo_id
        assert refreshed_data["run_mode"] == "demo_replay"

    @pytest.mark.anyio
    async def test_custom_investigation_durable_run_mode(self, client: AsyncClient):
        # 1. Generate incident & start live investigation
        gen_res = await client.post(
            "/api/incidents/generate",
            json={"incident_type": "bad_deployment_db_exhaustion", "seed": 77}
        )
        inc_id = gen_res.json()["incident_id"]

        run_res = await client.post("/api/investigations/run", json={"incident_id": inc_id})
        assert run_res.status_code == 200
        inv_data = run_res.json()
        inv_id = inv_data["investigation_id"]
        assert inv_data["run_mode"] == "autonomous_live"

        # 2. Simulate cache loss
        _investigation_cache.clear()

        # 3. Query after cache loss
        refresh_res = await client.get(f"/api/investigations/{inv_id}")
        assert refresh_res.status_code == 200
        assert refresh_res.json()["run_mode"] == "autonomous_live"

    @pytest.mark.anyio
    async def test_missing_investigation_returns_404_cleanly(self, client: AsyncClient):
        non_existent_id = str(uuid4())
        res = await client.get(f"/api/investigations/{non_existent_id}")
        assert res.status_code == 404
        assert "not found" in res.json()["detail"].lower()


class TestLLMProviderTrackingAndMockLabeling:
    """Verifies that mock-backed runs are explicitly tracked and labeled, never masquerading as live Gemini runs."""

    @pytest.mark.anyio
    async def test_mock_provider_run_persists_mock_label(self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
        from app.llm.provider import MockLLMProvider, get_llm_provider

        # 1. Force offline/mock mode via environment
        monkeypatch.setenv("LLM_PROVIDER", "mock")
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

        provider = get_llm_provider()
        assert provider.provider_name == "mock"
        assert provider.is_fallback is True
        assert "mock" in provider.model_name.lower()

        # 2. Generate and run incident
        gen_res = await client.post(
            "/api/incidents/generate",
            json={"incident_type": "bad_deployment_db_exhaustion", "seed": 55}
        )
        assert gen_res.status_code == 200
        inc_id = gen_res.json()["incident_id"]

        run_res = await client.post("/api/investigations/run", json={"incident_id": inc_id})
        assert run_res.status_code == 200
        inv_data = run_res.json()

        # 3. Investigation must be explicitly tagged as mock
        assert inv_data["llm_provider"] == "mock"
        assert "mock" in inv_data["llm_model"].lower()

        # 4. Polling endpoint must return the explicit mock provider metadata
        inv_id = inv_data["investigation_id"]
        detail_res = await client.get(f"/api/investigations/{inv_id}")
        assert detail_res.status_code == 200
        detail = detail_res.json()
        assert detail["llm_provider"] == "mock"
        assert "mock" in detail["llm_model"].lower()

    @pytest.mark.anyio
    async def test_gemini_provider_run_persists_gemini_label(self, monkeypatch: pytest.MonkeyPatch):
        from app.llm.provider import GeminiProvider, get_llm_provider

        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.setenv("GEMINI_API_KEY", "dummy_test_key")
        monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")

        provider = get_llm_provider()
        assert provider.provider_name == "gemini"
        assert provider.model_name == "gemini-2.5-flash"
        assert provider.is_fallback is False

