"""Investigations API Router."""

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_fastapi_session, get_session_factory
from app.db.models import IncidentORM, InvestigationORM, InvestigationStepORM
from app.llm.provider import get_llm_provider
from app.orchestrator.orchestrator import run_investigation
from app.orchestrator.state_machine import InvestigationState
from app.timeline.engine import build_timeline

from app.schemas.investigations import InvestigationStepDetailValue

router = APIRouter(prefix="/api/investigations", tags=["Investigations"])

# In-memory tracking of active tasks and investigation state cache for zero-lock polling
_running_tasks: dict[UUID, asyncio.Task] = {}
_investigation_cache: dict[UUID, InvestigationPublic] = {}
_hypotheses_cache: dict[UUID, list[dict[str, Any]]] = {}


class RunInvestigationRequest(BaseModel):
    incident_id: UUID


class InvestigationStepPublic(BaseModel):
    step_number: int
    state: str
    summary: str
    details: dict[str, InvestigationStepDetailValue]
    timestamp: datetime


class InvestigationPublic(BaseModel):
    investigation_id: UUID
    incident_id: UUID
    final_state: str
    confidence: float
    rca_narrative: str | None = None
    leading_hypothesis_id: UUID | None = None
    started_at: datetime
    completed_at: datetime | None = None
    steps: list[InvestigationStepPublic] = Field(default_factory=list)


async def _execute_investigation_worker(incident_id: UUID, investigation_id: UUID) -> None:
    """Background worker executing the full investigation pipeline with live DB step persistence."""
    provider = get_llm_provider()
    factory = get_session_factory()
    async with factory() as session:
        try:
            inv = await run_investigation(
                incident_id=incident_id,
                session=session,
                llm_provider=provider,
                investigation_id=investigation_id,
            )
            # Update in-memory cache with completed investigation record
            pub_steps = [
                InvestigationStepPublic(
                    step_number=s.step_number,
                    state=s.state.value if hasattr(s.state, "value") else str(s.state),
                    summary=s.summary,
                    details=s.details or {},
                    timestamp=s.timestamp,
                )
                for s in inv.steps
            ]
            completed_pub = InvestigationPublic(
                investigation_id=inv.investigation_id,
                incident_id=inv.incident_id,
                final_state=inv.final_state.value if hasattr(inv.final_state, "value") else str(inv.final_state),
                confidence=round(inv.confidence or 0.0, 2),
                rca_narrative=inv.rca_narrative,
                leading_hypothesis_id=inv.leading_hypothesis_id,
                started_at=inv.started_at,
                completed_at=inv.completed_at,
                steps=pub_steps,
            )
            _investigation_cache[investigation_id] = completed_pub

        except Exception as ex:
            print(f"Investigation execution error: {ex}")
            # Mark error in cache
            if investigation_id in _investigation_cache:
                cached = _investigation_cache[investigation_id]
                _investigation_cache[investigation_id] = InvestigationPublic(
                    investigation_id=cached.investigation_id,
                    incident_id=cached.incident_id,
                    final_state="inconclusive",
                    confidence=0.0,
                    rca_narrative=f"Investigation concluded: {ex}",
                    started_at=cached.started_at,
                    completed_at=datetime.now(timezone.utc),
                    steps=cached.steps,
                )
        finally:
            _running_tasks.pop(investigation_id, None)


@router.post("/run", response_model=InvestigationPublic)
async def start_investigation(
    req: RunInvestigationRequest,
    session: AsyncSession = Depends(get_fastapi_session),
) -> InvestigationPublic:
    """Triggers the full investigation orchestrator in the background and returns initial state."""
    # Check if incident exists
    inc_stmt = select(IncidentORM).where(IncidentORM.incident_id == req.incident_id)
    inc = (await session.execute(inc_stmt)).scalar_one_or_none()
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    # Check if already running or completed
    inv_stmt = (
        select(InvestigationORM)
        .where(InvestigationORM.incident_id == req.incident_id)
        .order_by(InvestigationORM.started_at.desc())
    )
    existing_inv = (await session.execute(inv_stmt)).scalars().first()

    if existing_inv and existing_inv.final_state == InvestigationState.RCA_GENERATED.value:
        # Return existing completed investigation
        return await get_investigation_detail(existing_inv.investigation_id, session)

    inv_id = uuid4()
    started_at = datetime.now(timezone.utc)

    # Create initial investigation record
    initial_inv = InvestigationORM(
        investigation_id=inv_id,
        incident_id=req.incident_id,
        final_state="running",
        confidence=0.0,
        started_at=started_at,
    )
    session.add(initial_inv)
    await session.commit()

    initial_pub = InvestigationPublic(
        investigation_id=inv_id,
        incident_id=req.incident_id,
        final_state="running",
        confidence=0.0,
        started_at=started_at,
        steps=[],
    )
    _investigation_cache[inv_id] = initial_pub

    # Launch background task
    task = asyncio.create_task(_execute_investigation_worker(req.incident_id, inv_id))
    _running_tasks[inv_id] = task

    return initial_pub


@router.get("/{investigation_id}", response_model=InvestigationPublic)
async def get_investigation_detail(
    investigation_id: UUID,
    session: AsyncSession = Depends(get_fastapi_session),
) -> InvestigationPublic:
    """Fetches full investigation status and steps so far for polling."""
    # Check cache first for completed investigations
    if investigation_id in _investigation_cache:
        cached = _investigation_cache[investigation_id]
        if cached.final_state in ("rca_generated", "inconclusive"):
            return cached

    inv_stmt = select(InvestigationORM).where(InvestigationORM.investigation_id == investigation_id)
    inv = (await session.execute(inv_stmt)).scalar_one_or_none()
    if not inv:
        if investigation_id in _investigation_cache:
            return _investigation_cache[investigation_id]
        raise HTTPException(status_code=404, detail="Investigation not found")

    steps_stmt = (
        select(InvestigationStepORM)
        .where(InvestigationStepORM.investigation_id == investigation_id)
        .order_by(InvestigationStepORM.step_number.asc())
    )
    steps = (await session.execute(steps_stmt)).scalars().all()

    inv_pub = InvestigationPublic(
        investigation_id=inv.investigation_id,
        incident_id=inv.incident_id,
        final_state=inv.final_state,
        confidence=round(inv.confidence or 0.0, 2),
        rca_narrative=inv.rca_narrative,
        leading_hypothesis_id=inv.leading_hypothesis_id,
        started_at=inv.started_at,
        completed_at=inv.completed_at,
        steps=[
            InvestigationStepPublic(
                step_number=s.step_number,
                state=s.state,
                summary=s.summary,
                details=s.details or {},
                timestamp=s.timestamp,
            )
            for s in steps
        ],
    )
    _investigation_cache[investigation_id] = inv_pub
    return inv_pub


@router.get("/{investigation_id}/timeline")
async def get_investigation_timeline(
    investigation_id: UUID,
    session: AsyncSession = Depends(get_fastapi_session),
) -> dict[str, Any]:
    """Fetches the timeline analysis for the incident associated with an investigation."""
    inv_stmt = select(InvestigationORM).where(InvestigationORM.investigation_id == investigation_id)
    inv = (await session.execute(inv_stmt)).scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Investigation not found")

    tl = await build_timeline(session, inv.incident_id)
    return {
        "incident_id": str(tl.incident_id),
        "start_time": tl.start_time.isoformat(),
        "end_time": tl.end_time.isoformat() if tl.end_time else None,
        "total_events": len(tl.events),
        "clusters": [
            {
                "cluster_id": c.cluster_id,
                "start_time": c.start_time.isoformat(),
                "end_time": c.end_time.isoformat(),
                "event_count": len(c.event_ids),
                "involved_sources": [s.value if hasattr(s, 'value') else str(s) for s in c.involved_sources],
                "summary": c.summary,
            }
            for c in tl.clusters
        ],
    }


@router.get("/{investigation_id}/hypotheses")
async def get_investigation_hypotheses(
    investigation_id: UUID,
    session: AsyncSession = Depends(get_fastapi_session),
) -> list[dict[str, Any]]:
    """Extracts evaluated hypotheses history and score trajectories from investigation steps."""
    steps_stmt = (
        select(InvestigationStepORM)
        .where(InvestigationStepORM.investigation_id == investigation_id)
        .order_by(InvestigationStepORM.step_number.asc())
    )
    steps = (await session.execute(steps_stmt)).scalars().all()

    hypotheses_map: dict[str, dict[str, Any]] = {}

    # Step 1: Find ranked candidates
    for step in steps:
        if step.state == "hypotheses_ranked":
            for h in step.details.get("candidate_hypotheses", []):
                h_id = h.get("hypothesis_id") or h.get("title")
                hypotheses_map[h_id] = {
                    "hypothesis_id": h.get("hypothesis_id"),
                    "title": h.get("title"),
                    "description": h.get("description", ""),
                    "category": h.get("category", ""),
                    "status": h.get("status", "candidate"),
                    "initial_score": round(h.get("final_score", 0.0), 1),
                    "final_score": round(h.get("final_score", 0.0), 1),
                    "confidence": round(h.get("confidence", 0.0), 1),
                    "score_before": None,
                    "score_after": None,
                    "verdicts": [],
                    "supporting_evidence": h.get("supporting_evidence", []),
                    "contradictions_count": 0,
                    "supporting_count": 0,
                    "investigated": False,
                }

    # Step 2: Update with self-critique investigation steps
    for step in steps:
        if step.state == "investigating_hypothesis":
            title = step.details.get("hypothesis_title")
            h_id = step.details.get("hypothesis_id") or title
            if h_id in hypotheses_map or title in hypotheses_map:
                target = hypotheses_map.get(h_id) or hypotheses_map.get(title)
                target["status"] = step.details.get("status_after", target["status"])
                target["score_before"] = step.details.get("score_before")
                target["score_after"] = step.details.get("score_after")
                target["final_score"] = step.details.get("score_after", target["final_score"])
                target["confidence"] = step.details.get("confidence_score", target["confidence"])
                target["verdicts"] = step.details.get("verdicts", [])
                target["investigated"] = True
                if step.details.get("supporting_evidence"):
                    target["supporting_evidence"] = step.details.get("supporting_evidence")

                target["contradictions_count"] = len([v for v in target["verdicts"] if v.get("verdict") == "contradicts"])
                target["supporting_count"] = len([v for v in target["verdicts"] if v.get("verdict") == "supports"])

    # Step 3: Check RCA step for any additional supporting evidence on the leading hypothesis
    for step in steps:
        if step.state == "rca_generated":
            lead_id = step.details.get("leading_hypothesis_id")
            if lead_id and lead_id in hypotheses_map:
                if step.details.get("supporting_evidence"):
                    hypotheses_map[lead_id]["supporting_evidence"] = step.details.get("supporting_evidence")

    return list(hypotheses_map.values())


@router.post("/demo", response_model=InvestigationPublic)
async def start_demo_investigation(
    session: AsyncSession = Depends(get_fastapi_session),
) -> InvestigationPublic:
    """Generates the verified demo incident (bad deployment seed=1) and kicks off investigation."""
    from app.embeddings.ingest import ingest_incident_evidence
    from app.embeddings.provider import get_embedding_provider
    from app.evaluation.benchmark_incidents import BenchmarkIncidentSpec, instantiate_benchmark_incident
    from app.generator.incidents.incident_types import IncidentType
    import random

    # Use seed 1 (or 2) for deterministic high-accuracy root-cause scenario with fresh benchmark_id
    run_uuid = uuid4()
    spec = BenchmarkIncidentSpec(
        benchmark_id=f"demo-{run_uuid}",
        incident_type=IncidentType.BAD_DEPLOYMENT_DB_EXHAUSTION.value,
        seed=1,
        duration_minutes=15,
        description="Demo Incident: Bad deployment causing DB pool exhaustion",
    )
    incident, bundle = instantiate_benchmark_incident(spec)
    embedder = get_embedding_provider()
    await ingest_incident_evidence(session, incident, bundle, provider=embedder)

    return await start_investigation(RunInvestigationRequest(incident_id=incident.incident_id), session)
