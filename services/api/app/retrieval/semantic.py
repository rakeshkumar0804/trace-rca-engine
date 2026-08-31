# CRITICAL ISOLATION ENFORCEMENT: This retrieval module queries ONLY investigator-facing tables.
# It must NEVER join or query the 'ground_truths' table.

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.conversions import orm_to_normalized_event
from app.db.models import AlertORM, GitCommitORM, LogORM, NormalizedEventORM
from app.embeddings.provider import (
    EmbeddingProvider,
    cosine_similarity,
    get_embedding_provider,
)
from app.schemas.events import NormalizedEvent

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


async def search_similar(
    session: AsyncSession,
    incident_id: UUID,
    query_text: str,
    limit: int = DEFAULT_LIMIT,
    provider: EmbeddingProvider | None = None,
) -> list[NormalizedEvent]:
    """Performs semantic similarity search across embedded text fields (logs, commits, alerts) for an incident.
    
    Computes query vector embedding and ranks candidate events by cosine similarity.
    """
    safe_limit = max(1, min(limit, MAX_LIMIT))
    embedder = provider or get_embedding_provider()
    query_vector = embedder.embed_text(query_text)

    # 1. Retrieve all embedded candidate items for this incident
    candidates: list[tuple[UUID | str, float]] = []

    # Logs
    log_stmt = select(LogORM.id, LogORM.embedding).where(
        LogORM.incident_id == incident_id,
        LogORM.embedding.isnot(None),
    )
    log_rows = (await session.execute(log_stmt)).all()
    for log_id, emb in log_rows:
        if emb:
            sim = cosine_similarity(query_vector, emb)
            candidates.append((log_id, sim))

    # Commits
    commit_stmt = select(GitCommitORM.commit_sha, GitCommitORM.embedding).where(
        GitCommitORM.incident_id == incident_id,
        GitCommitORM.embedding.isnot(None),
    )
    commit_rows = (await session.execute(commit_stmt)).all()
    for sha, emb in commit_rows:
        if emb:
            sim = cosine_similarity(query_vector, emb)
            candidates.append((sha, sim))

    # Alerts
    alert_stmt = select(AlertORM.id, AlertORM.embedding).where(
        AlertORM.incident_id == incident_id,
        AlertORM.embedding.isnot(None),
    )
    alert_rows = (await session.execute(alert_stmt)).all()
    for alert_id, emb in alert_rows:
        if emb:
            sim = cosine_similarity(query_vector, emb)
            candidates.append((alert_id, sim))

    if not candidates:
        return []

    # 2. Sort candidate event IDs by similarity descending
    candidates.sort(key=lambda x: x[1], reverse=True)
    top_candidates = candidates[:safe_limit]

    # Map candidate IDs (UUIDs and commit SHAs) to NormalizedEventORM objects
    target_uuids = [c[0] for c in top_candidates if isinstance(c[0], UUID)]
    target_shas = [str(c[0]) for c in top_candidates if isinstance(c[0], str)]

    # Fetch corresponding normalized events
    norm_stmt = select(NormalizedEventORM).where(
        NormalizedEventORM.incident_id == incident_id,
    )
    norm_rows = (await session.execute(norm_stmt)).scalars().all()
    
    # Index normalized events by ID and by commit_sha relationship/attribute
    norm_by_id: dict[UUID, NormalizedEventORM] = {r.id: r for r in norm_rows}
    norm_by_sha: dict[str, NormalizedEventORM] = {}
    for r in norm_rows:
        sha = r.attributes.get("commit_sha") if isinstance(r.attributes, dict) else None
        if sha:
            norm_by_sha[str(sha)] = r

    results: list[NormalizedEvent] = []
    seen_ids: set[UUID] = set()

    for cand_id, score in top_candidates:
        matched_norm: NormalizedEventORM | None = None
        if isinstance(cand_id, UUID) and cand_id in norm_by_id:
            matched_norm = norm_by_id[cand_id]
        elif isinstance(cand_id, str) and cand_id in norm_by_sha:
            matched_norm = norm_by_sha[cand_id]

        if matched_norm and matched_norm.id not in seen_ids:
            seen_ids.add(matched_norm.id)
            evt = orm_to_normalized_event(matched_norm)
            # Annotate similarity score in attributes for caller visibility
            evt.attributes["semantic_score"] = round(score, 4)
            results.append(evt)

    return results[:safe_limit]
