"""Server startup recovery for interrupted investigations."""

from datetime import datetime, timezone
import logging
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import InvestigationORM, InvestigationStepORM
from app.schemas.investigations import InvestigationState

logger = logging.getLogger("trace.orchestrator.recovery")


async def recover_interrupted_investigations(session: AsyncSession) -> int:
    """Detects and transitions orphaned 'running' investigations to 'interrupted' on startup.
    
    Prevents background tasks lost during process restarts from indefinitely remaining 'running'.
    """
    stmt = (
        select(InvestigationORM)
        .where(InvestigationORM.final_state == "running")
    )
    orphaned = (await session.execute(stmt)).scalars().all()

    if not orphaned:
        return 0

    now = datetime.now(timezone.utc)
    logger.warning(f"Found {len(orphaned)} orphaned 'running' investigations on startup. Transitioning to interrupted state.")

    for inv in orphaned:
        inv.final_state = InvestigationState.INTERRUPTED.value
        inv.completed_at = now
        inv.rca_narrative = (
            "Investigation was interrupted due to a server process restart. "
            "Please return to the launcher and retry the investigation."
        )

        # Determine next step number
        step_cnt_stmt = (
            select(func.count())
            .select_from(InvestigationStepORM)
            .where(InvestigationStepORM.investigation_id == inv.investigation_id)
        )
        cnt = (await session.execute(step_cnt_stmt)).scalar() or 0

        interrupted_step = InvestigationStepORM(
            investigation_id=inv.investigation_id,
            step_number=cnt + 1,
            state=InvestigationState.INTERRUPTED.value,
            timestamp=now,
            summary="Investigation interrupted by server process restart.",
            details={
                "error": "server_process_restart",
                "recoverable": True,
                "interrupted_at": now.isoformat(),
            },
        )
        session.add(interrupted_step)

    await session.commit()
    logger.info(f"Successfully recovered {len(orphaned)} interrupted investigations.")
    return len(orphaned)
