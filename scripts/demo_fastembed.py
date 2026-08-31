import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "services" / "api"))

from app.db.base import Base, get_db_session, reset_engine
from app.embeddings.ingest import ingest_incident_evidence
from app.embeddings.provider import FastEmbedProvider
from app.generator import (
    generate_bad_deployment_db_exhaustion_incident,
    generate_healthy_environment,
)
from app.retrieval.semantic import search_similar


async def main():
    test_db_url = "sqlite+aiosqlite:///:memory:"
    engine = await reset_engine(test_db_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    provider = FastEmbedProvider(model_name="BAAI/bge-small-en-v1.5")
    start = datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
    base_env = generate_healthy_environment(seed=42, start=start, duration_minutes=5)
    incident, bundle = generate_bad_deployment_db_exhaustion_incident(
        seed=42, base_environment=base_env, incident_start=start, duration_minutes=5
    )

    async with get_db_session() as session:
        await ingest_incident_evidence(session, incident, bundle, provider=provider)
        query = "database connection timeout"
        results = await search_similar(
            session,
            incident.incident_id,
            query_text=query,
            limit=5,
            provider=provider,
        )

        output = [
            {
                "rank": idx + 1,
                "event_id": str(r.id),
                "timestamp": r.timestamp.isoformat(),
                "source": r.source.value,
                "entity": r.entity,
                "event_type": r.event_type,
                "semantic_score": r.attributes.get("semantic_score"),
                "message_or_desc": (
                    r.attributes.get("message")
                    or r.attributes.get("description")
                    or r.attributes.get("diff_summary")
                ),
            }
            for idx, r in enumerate(results)
        ]
        print(json.dumps(output, indent=2), flush=True)

    await reset_engine()


if __name__ == "__main__":
    asyncio.run(main())
