import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

# Ensure app package is importable regardless of working directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.base import Base, get_db_session, reset_engine
from app.embeddings.ingest import ingest_incident_evidence
from app.generator import (
    generate_bad_deployment_db_exhaustion_incident,
    generate_healthy_environment,
)
from app.schemas.events import EventSource
from app.schemas.timeline import Timeline
from app.timeline.engine import build_timeline


from app.embeddings.provider import DeterministicEmbeddingProvider

@pytest.fixture(scope="module", autouse=True)
def setup_timeline_incident():
    """Initializes test database and ingests a sample incident for timeline testing."""
    test_db_url = "sqlite+aiosqlite:///:memory:"
    engine = asyncio.run(reset_engine(test_db_url))
    embedder = DeterministicEmbeddingProvider(dim=384)

    async def init_data():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        start = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
        base_env = generate_healthy_environment(seed=42, start=start, duration_minutes=15)
        incident, bundle = generate_bad_deployment_db_exhaustion_incident(
            seed=42, base_environment=base_env, incident_start=start, duration_minutes=15
        )

        async with get_db_session() as session:
            await ingest_incident_evidence(session, incident, bundle, provider=embedder)

        return incident

    incident = asyncio.run(init_data())
    yield incident
    asyncio.run(reset_engine())


class TestTimelineEngine:
    """Tests for timeline generation, phase partitioning, and multi-source cluster detection."""

    def test_build_timeline_strict_chronological_ordering(self, setup_timeline_incident):
        incident = setup_timeline_incident

        async def run():
            async with get_db_session() as session:
                timeline = await build_timeline(session, incident.incident_id)

                assert isinstance(timeline, Timeline)
                assert len(timeline.events) > 0

                # Verify strict chronological monotonic ordering
                for idx in range(len(timeline.events) - 1):
                    assert timeline.events[idx].timestamp <= timeline.events[idx + 1].timestamp

        asyncio.run(run())

    def test_timeline_phase_partitioning(self, setup_timeline_incident):
        incident = setup_timeline_incident

        async def run():
            async with get_db_session() as session:
                timeline = await build_timeline(session, incident.incident_id)

                # Pre-incident
                for evt in timeline.pre_incident_events:
                    assert evt.timestamp < incident.start_time

                # During-incident
                for evt in timeline.during_incident_events:
                    if incident.end_time is not None:
                        assert incident.start_time <= evt.timestamp <= incident.end_time
                    else:
                        assert evt.timestamp >= incident.start_time

                # Total count check
                assert len(timeline.events) == (
                    len(timeline.pre_incident_events)
                    + len(timeline.during_incident_events)
                    + len(timeline.post_incident_events)
                )

        asyncio.run(run())

    def test_timeline_cluster_detection(self, setup_timeline_incident):
        """Verify cluster detection identifies multi-source correlation during incident escalation."""
        incident = setup_timeline_incident

        async def run():
            async with get_db_session() as session:
                timeline = await build_timeline(session, incident.incident_id, cluster_window_seconds=90.0)

                assert len(timeline.clusters) > 0
                
                # Check for clusters involving key telemetry sources
                cluster_sources = [set(c.involved_sources) for c in timeline.clusters]
                
                # At least one cluster must involve database / metric / log / alert correlation
                multi_source_found = any(len(sources) >= 2 for sources in cluster_sources)
                assert multi_source_found, "Failed to detect multi-source event clusters"

                for cluster in timeline.clusters:
                    assert cluster.start_time <= cluster.end_time
                    assert len(cluster.event_ids) >= 3
                    assert len(cluster.involved_sources) >= 2

        asyncio.run(run())
