import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

# Ensure app package is importable regardless of working directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.base import Base, get_db_session, reset_engine
from app.embeddings.ingest import ingest_incident_evidence
from app.embeddings.provider import FastEmbedProvider, get_embedding_provider
from app.generator import (
    generate_bad_deployment_db_exhaustion_incident,
    generate_healthy_environment,
)
from app.retrieval.semantic import search_similar
from app.schemas.events import NormalizedEvent


@pytest.mark.integration
class TestRealEmbeddingsRetrieval:
    """Integration test verifying real neural embeddings (FastEmbed / BAAI/bge-small-en-v1.5).
    
    Tests that a real local ONNX neural model produces dense semantic representations
    that rank the ground-truth causal timeout event in the top 3 results for natural queries.
    """

    def test_real_fastembed_semantic_search_ranks_timeout_in_top_3(self):
        async def run_integration_test():
            # 1. Setup isolated in-memory test database
            test_db_url = "sqlite+aiosqlite:///:memory:"
            engine = await reset_engine(test_db_url)
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            # 2. Instantiate real FastEmbed neural provider
            real_provider = FastEmbedProvider(model_name="BAAI/bge-small-en-v1.5")
            assert real_provider.dimension == 384

            # 3. Generate sample incident and ingest using real embeddings
            start = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
            base_env = generate_healthy_environment(seed=42, start=start, duration_minutes=5)
            incident, bundle = generate_bad_deployment_db_exhaustion_incident(
                seed=42, base_environment=base_env, incident_start=start, duration_minutes=5
            )

            async with get_db_session() as session:
                await ingest_incident_evidence(session, incident, bundle, provider=real_provider)

                # 4. Perform real semantic search query
                query = "database connection timeout"
                results = await search_similar(
                    session,
                    incident.incident_id,
                    query_text=query,
                    limit=5,
                    provider=real_provider,
                )

                assert len(results) >= 3, f"Expected at least 3 results, got {len(results)}"

                # 5. Verify the top 3 results contain the causal database timeout error log
                top_3 = results[:3]
                found_timeout_in_top_3 = False

                for rank, evt in enumerate(top_3, 1):
                    assert isinstance(evt, NormalizedEvent)
                    msg = str(evt.attributes.get("message", "")).lower()
                    desc = str(evt.attributes.get("description", "")).lower()
                    combined = f"{msg} {desc}"

                    if "database connection timeout" in combined or "timed out" in combined or "connection pool" in combined:
                        found_timeout_in_top_3 = True
                        break

                assert found_timeout_in_top_3, (
                    f"Expected database connection timeout error in top 3 results. Top 3 results: "
                    f"{[r.attributes.get('message') or r.attributes.get('description') for r in top_3]}"
                )

                # Score check: real neural similarity for relevant text should be strong (> 0.50)
                assert top_3[0].attributes.get("semantic_score", 0.0) > 0.50

            await reset_engine()

        asyncio.run(run_integration_test())
