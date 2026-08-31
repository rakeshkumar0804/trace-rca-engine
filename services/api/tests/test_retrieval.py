import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from uuid import uuid4

import pytest

# Ensure app package is importable regardless of working directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.base import Base, get_db_session, reset_engine
from app.embeddings.ingest import ingest_incident_evidence
from app.generator import (
    generate_bad_deployment_db_exhaustion_incident,
    generate_healthy_environment,
)
from app.retrieval import (
    get_changes_before,
    get_events_for_dependencies,
    get_events_for_entity,
    get_events_in_window,
    search_similar,
)
from app.schemas.events import NormalizedEvent


from app.embeddings.provider import DeterministicEmbeddingProvider

@pytest.fixture(scope="module", autouse=True)
def setup_ingested_incident():
    """Initializes test database and ingests two independent incident scenarios for isolation testing."""
    test_db_url = "sqlite+aiosqlite:///:memory:"
    engine = asyncio.run(reset_engine(test_db_url))
    embedder = DeterministicEmbeddingProvider(dim=384)

    async def init_data():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        start = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
        
        # Incident A
        base_env_a = generate_healthy_environment(seed=42, start=start, duration_minutes=15)
        inc_a, bundle_a = generate_bad_deployment_db_exhaustion_incident(
            seed=42, base_environment=base_env_a, incident_start=start, duration_minutes=15
        )

        # Incident B (cross-incident isolation test)
        base_env_b = generate_healthy_environment(seed=999, start=start, duration_minutes=15)
        inc_b, bundle_b = generate_bad_deployment_db_exhaustion_incident(
            seed=999, base_environment=base_env_b, incident_start=start, duration_minutes=15
        )

        async with get_db_session() as session:
            await ingest_incident_evidence(session, inc_a, bundle_a, provider=embedder)
            await ingest_incident_evidence(session, inc_b, bundle_b, provider=embedder)

        return inc_a, inc_b

    inc_a, inc_b = asyncio.run(init_data())
    yield inc_a, inc_b
    asyncio.run(reset_engine())


class TestRetrievalSubsystem:
    """End-to-end tests for all 5 retrieval functions against ingested database evidence."""

    def test_get_events_in_window(self, setup_ingested_incident):
        inc_a, _ = setup_ingested_incident

        async def run():
            async with get_db_session() as session:
                start_win = inc_a.start_time
                end_win = inc_a.start_time + timedelta(minutes=5)
                events = await get_events_in_window(session, inc_a.incident_id, start_win, end_win, limit=25)
                
                assert len(events) > 0
                assert len(events) <= 25
                for evt in events:
                    assert isinstance(evt, NormalizedEvent)
                    assert start_win <= evt.timestamp <= end_win

        asyncio.run(run())

    def test_get_events_for_entity(self, setup_ingested_incident):
        inc_a, _ = setup_ingested_incident

        async def run():
            async with get_db_session() as session:
                events = await get_events_for_entity(session, inc_a.incident_id, "checkout-service", limit=50)
                
                assert len(events) > 0
                for evt in events:
                    assert evt.entity == "checkout-service" or evt.service == "checkout-service"

        asyncio.run(run())

    def test_search_similar_semantic_relevance(self, setup_ingested_incident):
        """Semantic search for 'database connection timeout' must return timeout events at the top."""
        inc_a, _ = setup_ingested_incident

        async def run():
            async with get_db_session() as session:
                results = await search_similar(
                    session,
                    inc_a.incident_id,
                    query_text="database connection timeout after 5000ms",
                    limit=10,
                    provider=DeterministicEmbeddingProvider(dim=384),
                )

                assert len(results) > 0
                top_event = results[0]

                # Confirm the top ranked event is a relevant timeout log/error event
                msg_text = str(top_event.attributes.get("message", "")).lower()
                desc_text = str(top_event.attributes.get("description", "")).lower()
                combined = f"{msg_text} {desc_text}"

                assert any(kw in combined for kw in ["database", "timeout", "connection", "pool"]), (
                    f"Top semantic result lacked relevance keywords: {top_event.attributes}"
                )
                assert top_event.attributes.get("semantic_score", 0.0) > 0.40

        asyncio.run(run())

    def test_get_events_for_dependencies(self, setup_ingested_incident):
        inc_a, _ = setup_ingested_incident

        async def run():
            async with get_db_session() as session:
                # checkout-service connects to api-gateway, order-service, payment-service, inventory-service
                dep_events = await get_events_for_dependencies(
                    session, inc_a.incident_id, "checkout-service", limit=50
                )
                
                assert len(dep_events) > 0
                connected_entities = {"api-gateway", "order-service", "payment-service", "inventory-service"}
                for evt in dep_events:
                    entity_match = evt.entity in connected_entities or evt.service in connected_entities
                    assert entity_match, f"Event entity '{evt.entity}' not in connected dependencies"

        asyncio.run(run())

    def test_get_changes_before(self, setup_ingested_incident):
        inc_a, _ = setup_ingested_incident

        async def run():
            async with get_db_session() as session:
                changes = await get_changes_before(
                    session,
                    inc_a.incident_id,
                    timestamp=inc_a.start_time + timedelta(minutes=2),
                    lookback_minutes=30,
                    limit=10,
                )
                
                assert len(changes) > 0
                # Must find the causal deployment for checkout-service
                checkout_deps = [c for c in changes if hasattr(c, "service") and c.service == "checkout-service"]
                assert len(checkout_deps) >= 1
                assert checkout_deps[0].version == "v2.15.0"

        asyncio.run(run())

    def test_cross_incident_isolation(self, setup_ingested_incident):
        inc_a, inc_b = setup_ingested_incident

        async def run():
            async with get_db_session() as session:
                # Query using incident A's ID
                events_a = await get_events_for_entity(session, inc_a.incident_id, "checkout-service", limit=100)
                
                # Query using incident B's ID
                events_b = await get_events_for_entity(session, inc_b.incident_id, "checkout-service", limit=100)

                # Query using a completely non-existent incident ID
                non_existent_id = uuid4()
                events_none = await get_events_for_entity(session, non_existent_id, "checkout-service", limit=100)

                assert len(events_a) > 0
                assert len(events_b) > 0
                assert len(events_none) == 0

                # Ensure IDs from A and B do not overlap
                ids_a = {e.id for e in events_a}
                ids_b = {e.id for e in events_b}
                assert ids_a.isdisjoint(ids_b)

        asyncio.run(run())

    def test_limit_enforcement(self, setup_ingested_incident):
        inc_a, _ = setup_ingested_incident

        async def run():
            async with get_db_session() as session:
                # Limit = 3
                events_3 = await get_events_in_window(
                    session, inc_a.incident_id, inc_a.start_time - timedelta(minutes=10), inc_a.start_time + timedelta(minutes=10), limit=3
                )
                assert len(events_3) == 3

                # Limit = 5
                events_5 = await get_events_in_window(
                    session, inc_a.incident_id, inc_a.start_time - timedelta(minutes=10), inc_a.start_time + timedelta(minutes=10), limit=5
                )
                assert len(events_5) == 5

        asyncio.run(run())
