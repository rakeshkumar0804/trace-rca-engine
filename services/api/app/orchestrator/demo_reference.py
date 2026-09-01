"""Pre-computed golden reference investigation cache and progressive replay for the Demo Incident.

Guarantees 100% reliable, zero-quota demo evaluations on "Run Demo Incident" regardless
of external Gemini API rate limits or daily quotas.
"""

import asyncio
from datetime import datetime, timezone
import logging
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.conversions import investigation_step_to_orm, investigation_to_orm
from app.db.models import IncidentORM, InvestigationORM, InvestigationStepORM
from app.embeddings.ingest import ingest_incident_evidence
from app.embeddings.provider import get_embedding_provider
from app.evaluation.benchmark_incidents import BenchmarkIncidentSpec, instantiate_benchmark_incident
from app.generator.incidents.incident_types import IncidentType
from app.llm.provider import MockLLMProvider
from app.orchestrator.orchestrator import run_investigation
from app.schemas.investigations import Investigation, InvestigationState, InvestigationStep

logger = logging.getLogger("trace.orchestrator.demo_reference")

# Static reference incident specification
DEMO_SPEC = BenchmarkIncidentSpec(
    benchmark_id="demo-reference-golden",
    incident_type=IncidentType.BAD_DEPLOYMENT_DB_EXHAUSTION.value,
    seed=1,
    duration_minutes=15,
    description="TRACE Golden Demo Scenario: Bad deployment to checkout-service causing DB connection pool exhaustion",
)

_cached_reference_investigation: Investigation | None = None
_cached_reference_incident_id: UUID | None = None


async def ensure_demo_incident_and_evidence(session: AsyncSession) -> UUID:
    """Ensures that the demo scenario incident and all underlying telemetry records exist in DB."""
    global _cached_reference_incident_id

    # Check if existing demo incident is already in DB
    if _cached_reference_incident_id:
        stmt = select(IncidentORM).where(IncidentORM.incident_id == _cached_reference_incident_id)
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing:
            return _cached_reference_incident_id

    incident, bundle = instantiate_benchmark_incident(DEMO_SPEC)
    _cached_reference_incident_id = incident.incident_id

    # Check database
    stmt = select(IncidentORM).where(IncidentORM.incident_id == incident.incident_id)
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if not existing:
        embedder = get_embedding_provider()
        await ingest_incident_evidence(session, incident, bundle, provider=embedder)
        logger.info(f"Ingested golden demo evidence for incident {incident.incident_id}")

    return incident.incident_id


async def get_or_generate_demo_reference(
    session: AsyncSession,
    force_refresh: bool = False,
) -> tuple[UUID, Investigation]:
    """Retrieves the cached golden investigation result or generates it if missing."""
    global _cached_reference_investigation

    incident_id = await ensure_demo_incident_and_evidence(session)

    if _cached_reference_investigation and not force_refresh:
        return incident_id, _cached_reference_investigation

    # Check if a completed golden investigation already exists in the database
    inv_stmt = (
        select(InvestigationORM)
        .where(
            InvestigationORM.incident_id == incident_id,
            InvestigationORM.final_state == InvestigationState.RCA_GENERATED.value,
        )
        .order_by(InvestigationORM.completed_at.desc())
    )
    existing_inv = (await session.execute(inv_stmt)).scalars().first()

    if existing_inv and not force_refresh:
        steps_stmt = (
            select(InvestigationStepORM)
            .where(InvestigationStepORM.investigation_id == existing_inv.investigation_id)
            .order_by(InvestigationStepORM.step_number.asc())
        )
        steps_orm = (await session.execute(steps_stmt)).scalars().all()
        steps = [
            InvestigationStep(
                step_number=s.step_number,
                state=InvestigationState(s.state),
                summary=s.summary,
                details=s.details or {},
                timestamp=s.timestamp,
            )
            for s in steps_orm
        ]
        _cached_reference_investigation = Investigation(
            investigation_id=existing_inv.investigation_id,
            incident_id=existing_inv.incident_id,
            steps=steps,
            final_state=InvestigationState(existing_inv.final_state),
            leading_hypothesis_id=existing_inv.leading_hypothesis_id,
            confidence=existing_inv.confidence or 100.0,
            started_at=existing_inv.started_at,
            completed_at=existing_inv.completed_at,
            rca_narrative=existing_inv.rca_narrative,
        )
        return incident_id, _cached_reference_investigation

    # Generate fresh golden reference investigation using MockLLMProvider for deterministic 100% confidence
    logger.info("Generating reference demo investigation...")
    ref_inv = await run_investigation(
        incident_id=incident_id,
        session=session,
        llm_provider=MockLLMProvider(),
        max_hypotheses=3,
        min_confidence_threshold=70.0,
    )
    _cached_reference_investigation = ref_inv
    return incident_id, ref_inv


async def replay_demo_investigation(
    target_investigation_id: UUID,
    incident_id: UUID,
    ref_investigation: Investigation,
    session_factory: Any,
    investigation_cache: dict[UUID, Any],
    step_delay_seconds: float = 0.75,
) -> None:
    """Progressively replays the golden investigation steps to simulate real-time autonomous analysis."""
    from app.api.investigations import InvestigationPublic, InvestigationStepPublic

    try:
        accumulated_steps: list[InvestigationStepPublic] = []
        target_started_at = (
            investigation_cache[target_investigation_id].started_at
            if target_investigation_id in investigation_cache
            else datetime.now(timezone.utc)
        )

        for step in ref_investigation.steps:
            await asyncio.sleep(step_delay_seconds)

            pub_step = InvestigationStepPublic(
                step_number=step.step_number,
                state=step.state.value if hasattr(step.state, "value") else str(step.state),
                summary=step.summary,
                details=step.details or {},
                timestamp=datetime.now(timezone.utc),
            )
            accumulated_steps.append(pub_step)

            # Persist step to database
            async with session_factory() as session:
                step_orm = investigation_step_to_orm(step, target_investigation_id)
                step_orm.timestamp = pub_step.timestamp
                session.add(step_orm)
                await session.commit()

            # Update live in-memory polling cache
            investigation_cache[target_investigation_id] = InvestigationPublic(
                investigation_id=target_investigation_id,
                incident_id=incident_id,
                final_state="running" if step.step_number < len(ref_investigation.steps) else ref_investigation.final_state.value,
                confidence=round(ref_investigation.confidence, 2) if step.step_number == len(ref_investigation.steps) else 0.0,
                rca_narrative=ref_investigation.rca_narrative if step.step_number == len(ref_investigation.steps) else None,
                leading_hypothesis_id=ref_investigation.leading_hypothesis_id if step.step_number == len(ref_investigation.steps) else None,
                started_at=target_started_at,
                completed_at=datetime.now(timezone.utc) if step.step_number == len(ref_investigation.steps) else None,
                steps=list(accumulated_steps),
            )

        # Finalize investigation record in DB
        async with session_factory() as session:
            inv_stmt = select(InvestigationORM).where(InvestigationORM.investigation_id == target_investigation_id)
            inv_orm = (await session.execute(inv_stmt)).scalar_one_or_none()
            if inv_orm:
                inv_orm.final_state = ref_investigation.final_state.value
                inv_orm.leading_hypothesis_id = ref_investigation.leading_hypothesis_id
                inv_orm.confidence = ref_investigation.confidence
                inv_orm.completed_at = datetime.now(timezone.utc)
                inv_orm.rca_narrative = ref_investigation.rca_narrative
                await session.commit()

        logger.info(f"Replay completed successfully for demo investigation {target_investigation_id}")

    except Exception as ex:
        logger.exception(f"Error during demo investigation replay: {ex}")
        if target_investigation_id in investigation_cache:
            cached = investigation_cache[target_investigation_id]
            investigation_cache[target_investigation_id] = InvestigationPublic(
                investigation_id=target_investigation_id,
                incident_id=incident_id,
                final_state="inconclusive",
                confidence=0.0,
                rca_narrative=f"Demo replay encountered an error: {ex}",
                started_at=cached.started_at,
                completed_at=datetime.now(timezone.utc),
                steps=cached.steps,
            )
