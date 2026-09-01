"""Incidents API Router."""

from datetime import datetime, timezone
import random
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_fastapi_session
from app.db.models import IncidentORM
from app.embeddings.ingest import ingest_incident_evidence
from app.embeddings.provider import DeterministicEmbeddingProvider
from app.evaluation.benchmark_incidents import BenchmarkIncidentSpec, instantiate_benchmark_incident
from app.generator.incidents.incident_types import IncidentType

router = APIRouter(prefix="/api/incidents", tags=["Incidents"])


class GenerateIncidentRequest(BaseModel):
    incident_type: Literal[
        "bad_deployment_db_exhaustion",
        "dependency_failure_cascade",
        "memory_leak_masked_deployment",
        "memory_leak_red_herring_deployment",
        "random",
    ] = "bad_deployment_db_exhaustion"
    seed: int | None = None
    duration_minutes: int | None = None


class IncidentPublicSummary(BaseModel):
    incident_id: UUID
    incident_type: str
    severity: str
    started_at: datetime
    duration_minutes: int
    affected_services: list[str]
    expected_symptoms: list[str]


@router.post("/generate", response_model=IncidentPublicSummary)
async def generate_incident(
    req: GenerateIncidentRequest,
    session: AsyncSession = Depends(get_fastapi_session),
) -> IncidentPublicSummary:
    """Generates a new deterministic or random incident and ingests telemetry into the database."""
    # Resolve incident type with alias normalization
    if req.incident_type == "random":
        chosen_type = random.choice([
            IncidentType.BAD_DEPLOYMENT_DB_EXHAUSTION.value,
            IncidentType.DEPENDENCY_FAILURE_CASCADE.value,
            IncidentType.MEMORY_LEAK_MASKED_DEPLOYMENT.value,
        ])
    elif req.incident_type in ("memory_leak_red_herring_deployment", "memory_leak_masked_deployment"):
        chosen_type = IncidentType.MEMORY_LEAK_MASKED_DEPLOYMENT.value
    else:
        chosen_type = req.incident_type

    # Resolve seed & duration (default 15 minutes for rapid sub-2s cloud ingestion)
    seed_val = req.seed if req.seed is not None else random.randint(100, 99999)
    duration = req.duration_minutes or 15

    spec = BenchmarkIncidentSpec(
        benchmark_id=f"gen-{seed_val}",
        incident_type=chosen_type,
        seed=seed_val,
        duration_minutes=duration,
        description=f"Generated {chosen_type} incident (seed={seed_val})",
    )

    incident, bundle = instantiate_benchmark_incident(spec)
    embedder = DeterministicEmbeddingProvider(dim=384)

    # Ingest into DB
    await ingest_incident_evidence(session, incident, bundle, provider=embedder)

    # Return public summary - GROUND TRUTH IS STRIPPED
    return IncidentPublicSummary(
        incident_id=incident.incident_id,
        incident_type=incident.incident_type,
        severity=incident.severity.value,
        started_at=incident.start_time,
        duration_minutes=duration,
        affected_services=incident.affected_services,
        expected_symptoms=incident.expected_symptoms,
    )


@router.get("", response_model=list[IncidentPublicSummary])
async def list_incidents(
    session: AsyncSession = Depends(get_fastapi_session),
) -> list[IncidentPublicSummary]:
    """Lists all previously generated incidents (ground truth strictly stripped)."""
    stmt = select(IncidentORM).order_by(IncidentORM.start_time.desc()).limit(50)
    rows = (await session.execute(stmt)).scalars().all()

    return [
        IncidentPublicSummary(
            incident_id=r.incident_id,
            incident_type=r.incident_type,
            severity=r.severity,
            started_at=r.start_time,
            duration_minutes=int((r.end_time - r.start_time).total_seconds() / 60) if r.end_time else 30,
            affected_services=list(r.affected_services or []),
            expected_symptoms=list(r.expected_symptoms or []),
        )
        for r in rows
    ]
