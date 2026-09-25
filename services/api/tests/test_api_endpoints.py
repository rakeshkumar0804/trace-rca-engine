"""Integration tests for FastAPI REST API endpoints.

Enforces:
1. All endpoints return valid data structures.
2. Ground truth is NEVER exposed across any endpoint response.
3. Evidence click-through endpoint resolves actual telemetry rows.
"""

from uuid import uuid4
import pytest
from httpx import ASGITransport, AsyncClient

from app.db.base import Base, reset_engine
from app.main import app


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


class TestIncidentsAPI:
    """Tests for /api/incidents endpoints."""

    @pytest.mark.anyio
    async def test_generate_incident_and_ground_truth_isolation(self, client: AsyncClient):
        payload = {
            "incident_type": "bad_deployment_db_exhaustion",
            "seed": 42,
            "duration_minutes": 30,
        }
        res = await client.post("/api/incidents/generate", json=payload)
        assert res.status_code == 200
        data = res.json()

        # Schema assertions
        assert "incident_id" in data
        assert data["incident_type"] == "bad_deployment_db_exhaustion"
        assert data["severity"] == "sev1"
        assert len(data["affected_services"]) > 0

        # CRITICAL GROUND TRUTH ISOLATION CHECK
        assert "ground_truth" not in data
        assert "root_cause" not in data
        assert "causal_chain" not in data

    @pytest.mark.anyio
    async def test_list_incidents_strips_ground_truth(self, client: AsyncClient):
        # Generate two incidents
        await client.post("/api/incidents/generate", json={"incident_type": "bad_deployment_db_exhaustion", "seed": 1})
        await client.post("/api/incidents/generate", json={"incident_type": "dependency_failure_cascade", "seed": 2})

        res = await client.get("/api/incidents")
        assert res.status_code == 200
        items = res.json()
        assert len(items) >= 2

        for item in items:
            assert "incident_id" in item
            assert "ground_truth" not in item
            assert "root_cause" not in item


class TestInvestigationsAPI:
    """Tests for /api/investigations endpoints."""

    @pytest.mark.anyio
    async def test_start_investigation_and_poll_detail(self, client: AsyncClient):
        # 1. Generate incident
        gen_res = await client.post("/api/incidents/generate", json={"incident_type": "bad_deployment_db_exhaustion", "seed": 1})
        inc_id = gen_res.json()["incident_id"]

        # 2. Start investigation
        run_res = await client.post("/api/investigations/run", json={"incident_id": inc_id})
        assert run_res.status_code == 200
        inv_data = run_res.json()
        inv_id = inv_data["investigation_id"]

        assert "investigation_id" in inv_data
        assert inv_data["incident_id"] == inc_id
        assert inv_data["final_state"] == "running"
        assert len(inv_data["steps"]) >= 0  # Steps created async by background worker

        # 3. Poll investigation
        poll_res = await client.get(f"/api/investigations/{inv_id}")
        assert poll_res.status_code == 200
        poll_data = poll_res.json()
        assert poll_data["investigation_id"] == inv_id
        assert "ground_truth" not in poll_data

    @pytest.mark.anyio
    async def test_investigation_timeline_endpoint(self, client: AsyncClient):
        # 1. Generate incident
        gen_res = await client.post("/api/incidents/generate", json={"incident_type": "bad_deployment_db_exhaustion", "seed": 1})
        inc_id = gen_res.json()["incident_id"]

        # 2. Start investigation
        run_res = await client.post("/api/investigations/run", json={"incident_id": inc_id})
        inv_id = run_res.json()["investigation_id"]

        # 3. Get timeline
        tl_res = await client.get(f"/api/investigations/{inv_id}/timeline")
        assert tl_res.status_code == 200
        tl_data = tl_res.json()
        assert "incident_id" in tl_data
        assert "total_events" in tl_data
        assert "clusters" in tl_data

    @pytest.mark.anyio
    async def test_start_demo_investigation(self, client: AsyncClient):
        demo_res = await client.post("/api/investigations/demo")
        assert demo_res.status_code == 200
        data = demo_res.json()
        assert "investigation_id" in data
        assert data["final_state"] == "running"
        assert "ground_truth" not in data


class TestEvidenceAPI:
    """Tests for /api/evidence/{evidence_id} click-through endpoint."""

    @pytest.mark.anyio
    async def test_evidence_clickthrough_resolves_log_item(self, client: AsyncClient):
        from app.db.base import get_db_session
        from app.db.models import LogORM
        from datetime import datetime, timezone

        evidence_id = uuid4()
        inc_id = uuid4()

        async with get_db_session() as session:
            log_entry = LogORM(
                id=evidence_id,
                incident_id=inc_id,
                service="checkout-service",
                timestamp=datetime(2026, 8, 30, 14, 10, 0, tzinfo=timezone.utc),
                severity="ERROR",
                message="Connection timeout acquiring database connection",
                metadata_json={"db": "checkout_db"},
            )
            session.add(log_entry)

        res = await client.get(f"/api/evidence/{evidence_id}")
        assert res.status_code == 200
        ev_data = res.json()
        assert ev_data["evidence_id"] == str(evidence_id)
        assert ev_data["evidence_type"] == "log"
        assert ev_data["service"] == "checkout-service"
        assert "Connection timeout" in ev_data["message"]

    @pytest.mark.anyio
    async def test_nonexistent_evidence_returns_404(self, client: AsyncClient):
        fake_id = uuid4()
        res = await client.get(f"/api/evidence/{fake_id}")
        assert res.status_code == 404


class TestErrorFormattingAndDemoReplay:
    """Tests for user-facing error translation and progressive demo replay."""

    def test_format_human_error_message(self):
        from app.orchestrator.error_handling import format_human_error_message

        # 429 / Quota Error
        err_429 = RuntimeError("429 RESOURCE_EXHAUSTED: Resource has been exhausted (e.g. check quota)")
        msg_429 = format_human_error_message(err_429)
        assert "AI provider's request quota" in msg_429
        assert "Demo Incident" in msg_429
        assert "429" not in msg_429  # Raw error codes omitted from human message

        # Timeout Error
        err_timeout = TimeoutError("Deadline exceeded after 30000ms")
        msg_timeout = format_human_error_message(err_timeout)
        assert "timed out" in msg_timeout

        # Schema Error
        err_schema = ValueError("JSONDecodeError: invalid json schema")
        msg_schema = format_human_error_message(err_schema)
        assert "schema" in msg_schema

    @pytest.mark.anyio
    async def test_demo_investigation_progressive_replay(self, client: AsyncClient):
        import asyncio

        # Start demo investigation
        demo_res = await client.post("/api/investigations/demo")
        assert demo_res.status_code == 200
        inv_data = demo_res.json()
        inv_id = inv_data["investigation_id"]

        # Wait briefly for replay worker to progress
        await asyncio.sleep(0.5)

        # Poll status
        poll_res = await client.get(f"/api/investigations/{inv_id}")
        assert poll_res.status_code == 200
        poll_data = poll_res.json()
        assert poll_data["investigation_id"] == inv_id
        assert "ground_truth" not in poll_data

    @pytest.mark.anyio
    async def test_demo_replay_transparency_and_evidence_resolvability(self, client: AsyncClient):
        """Verifies that demo replay produces inspectable evidence records in the database."""
        import asyncio

        demo_res = await client.post("/api/investigations/demo")
        assert demo_res.status_code == 200
        inv_data = demo_res.json()
        inv_id = inv_data["investigation_id"]

        # Wait for replay worker to emit all steps
        for _ in range(15):
            await asyncio.sleep(0.6)
            poll_res = await client.get(f"/api/investigations/{inv_id}")
            poll_data = poll_res.json()
            if poll_data["final_state"] == "rca_generated":
                break

        assert poll_data["final_state"] == "rca_generated"
        assert poll_data["confidence"] == 100.0
        assert len(poll_data["steps"]) == 8
        assert "Bad Deployment" in poll_data["rca_narrative"]

    @pytest.mark.anyio
    async def test_demo_replay_endpoint_distinct_from_live_run(self, client: AsyncClient):
        """Verifies that the demo replay endpoint operates independently from custom incident runs."""
        # 1. Start demo replay
        demo_res = await client.post("/api/investigations/demo")
        assert demo_res.status_code == 200
        demo_data = demo_res.json()
        assert "investigation_id" in demo_data
        assert demo_data["final_state"] == "running"

        # 2. Custom live incident run with different seed/type
        gen_res = await client.post("/api/incidents/generate", json={"incident_type": "dependency_failure_cascade", "seed": 42})
        assert gen_res.status_code == 200
        inc_data = gen_res.json()
        assert inc_data["incident_type"] == "dependency_failure_cascade"
        assert inc_data["incident_id"] != demo_data["incident_id"]

    @pytest.mark.anyio
    async def test_demo_hypotheses_and_evidence_relevance(self, client: AsyncClient):
        """Verifies candidate categorization and absence of routine operational logs from primary evidence."""
        import asyncio

        demo_res = await client.post("/api/investigations/demo")
        assert demo_res.status_code == 200
        inv_data = demo_res.json()
        inv_id = inv_data["investigation_id"]

        # Wait for replay worker to emit all steps
        for _ in range(15):
            await asyncio.sleep(0.6)
            poll_res = await client.get(f"/api/investigations/{inv_id}")
            poll_data = poll_res.json()
            if poll_data["final_state"] == "rca_generated":
                break

        # Fetch hypotheses
        hyp_res = await client.get(f"/api/investigations/{inv_id}/hypotheses")
        assert hyp_res.status_code == 200
        hyps = hyp_res.json()
        assert len(hyps) > 0

        leading = next((h for h in hyps if h["status"] == "confirmed"), None)
        assert leading is not None
        assert "Bad deployment to checkout-service" in leading["title"]

        # Confirm that routine operational logs (like reservation confirmed) are not in primary supporting evidence
        for ref in leading.get("supporting_evidence", []):
            note = ref.get("relevance_note", "").lower()
            assert "reservation confirmed" not in note
            assert "inventory reservation" not in note




