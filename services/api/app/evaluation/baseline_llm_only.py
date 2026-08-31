"""Naive one-shot LLM baseline for root cause analysis.

This baseline isolates what TRACE's architecture (retrieval, candidate generation,
deterministic 7-term scoring, and iterative self-critique falsification) actually adds.
It feeds a dump of the initial retrieved evidence directly to the LLM in a single call
and prompts for structured root cause prediction without multi-hypothesis scoring.
"""

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.provider import LLMProvider
from app.retrieval import (
    get_changes_before,
    get_events_for_dependencies,
    get_events_for_entity,
    get_events_in_window,
)
from app.schemas.deployments import Deployment, GitCommit
from app.schemas.events import NormalizedEvent


class BaselinePrediction(BaseModel):
    """Structured LLM output for naive one-shot root cause prediction."""
    predicted_root_cause: str = Field(..., description="Concise statement of root cause")
    primary_affected_service: str = Field(..., description="Service primarily causing or suffering failure")
    failure_mechanism: str = Field(..., description="Mechanism (e.g. deployment, dependency, database)")
    confidence: float = Field(..., ge=0.0, le=100.0, description="Confidence percentage from 0 to 100")
    reasoning: str = Field(..., description="Summary explanation of the reasoning")


class BaselineResult(BaseModel):
    """Full execution result for the baseline run."""
    incident_id: UUID
    prediction: BaselinePrediction
    evidence_events_count: int
    completed_at: datetime


BASELINE_PROMPT_TEMPLATE = """You are an SRE on-call engineer analyzing telemetry for a production incident.
Review the following observed telemetry events, alerts, and recent changes retrieved during the incident window:

EVIDENCE DUMP:
{evidence_text}

INSTRUCTIONS:
In ONE step, identify what the single most likely root cause of this incident is.
Provide your answer formatted strictly as a JSON object matching this schema:
{{
  "predicted_root_cause": "<concise summary of root cause>",
  "primary_affected_service": "<name of service responsible or failing>",
  "failure_mechanism": "<e.g. deployment, database_pool_exhaustion, downstream_dependency_timeout, traffic_spike>",
  "confidence": <float between 0.0 and 100.0>,
  "reasoning": "<brief explanation citing specific evidence observed>"
}}
"""


async def run_baseline(
    incident_id: UUID,
    session: AsyncSession,
    llm_provider: LLMProvider,
    incident_start: datetime | None = None,
) -> BaselineResult:
    """Executes the naive one-shot LLM baseline against the stored incident telemetry."""
    start = incident_start or datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
    
    # Retrieve evidence bundle using the standard retrieval functions (same information TRACE sees initially)
    events = await get_events_in_window(session, incident_id, start, start, limit=30)
    checkout_events = await get_events_for_entity(session, incident_id, "checkout-service", limit=15)
    payment_events = await get_events_for_entity(session, incident_id, "payment-service", limit=15)
    changes = await get_changes_before(session, incident_id, start, limit=10)

    all_events_map: dict[UUID, NormalizedEvent] = {}
    for ev in events + checkout_events + payment_events:
        all_events_map[ev.id] = ev

    lines: list[str] = []
    lines.append("=== RECENT CHANGES (DEPLOYMENTS / COMMITS) ===")
    for ch in changes:
        if isinstance(ch, Deployment):
            ts = ch.started_at.isoformat() if ch.started_at else "N/A"
            lines.append(f"[{ts}] Deployment on {ch.service}: version={ch.version}, status={ch.status.value}, commit={ch.commit_sha}")
        elif isinstance(ch, GitCommit):
            ts = ch.timestamp.isoformat() if ch.timestamp else "N/A"
            lines.append(f"[{ts}] Commit on {ch.repository}: sha={ch.commit_sha}, author={ch.author}, diff={ch.diff_summary}")

    lines.append("\n=== TELEMETRY EVENTS (LOGS / METRICS / SPANS / ALERTS) ===")
    for ev in sorted(all_events_map.values(), key=lambda e: e.timestamp or datetime.min):
        ts = ev.timestamp.isoformat() if ev.timestamp else "N/A"
        lines.append(f"[{ts}] [{ev.source.value.upper()}] [{ev.severity.value if ev.severity else 'INFO'}] {ev.service}: {ev.event_type} | {json.dumps(ev.attributes)}")

    evidence_text = "\n".join(lines)
    prompt = BASELINE_PROMPT_TEMPLATE.format(evidence_text=evidence_text)

    prediction = await llm_provider.generate_structured(
        prompt=prompt,
        response_schema=BaselinePrediction,
        system_instruction="You are an expert site reliability engineer. Return strictly valid JSON.",
    )

    return BaselineResult(
        incident_id=incident_id,
        prediction=prediction,
        evidence_events_count=len(all_events_map) + len(changes),
        completed_at=datetime.now(timezone.utc),
    )
