# CRITICAL ISOLATION ENFORCEMENT: This prompt builder processes ONLY investigator-facing evidence.
# It must NEVER receive or include 'ground_truths' in any prompt.

from app.schemas.events import NormalizedEvent
from app.schemas.hypotheses import Hypothesis

SYSTEM_INSTRUCTION = """You are TRACE's Incident Narrative Generator.
You generate executive root-cause analysis summaries grounded in proven evidence.
Rules:
1. Every claim MUST cite one or more exact Evidence IDs from the provided context.
2. Never invent evidence IDs or assertions not substantiated by telemetry.
"""


def build_hypothesis_summary_prompt(
    hypothesis: Hypothesis,
    supporting_evidence: list[NormalizedEvent],
    falsification_summary: str,
) -> tuple[str, str]:
    """Constructs prompt for generating a source-linked natural language RCA summary."""
    evidence_lines = []
    for e in supporting_evidence:
        msg = e.attributes.get("message") or e.attributes.get("description") or e.event_type
        evidence_lines.append(f"- ID={e.id} [{e.source.value.upper()}] Time={e.timestamp.isoformat()} Entity={e.entity}: {msg}")

    evidence_block = "\n".join(evidence_lines) if evidence_lines else "No specific evidence attached."

    prompt = f"""### Confirmed Root-Cause Hypothesis
Title: {hypothesis.title}
Description: {hypothesis.description}
Deterministic Score: {hypothesis.score.final_score}/100

### Falsification Investigation Summary
{falsification_summary}

### Grounded Evidence Citations Available
{evidence_block}

### Task
Generate a structured RCA summary containing:
1. Title
2. Executive Summary
3. List of atomic Claims, each citing the exact Evidence IDs from the available list above.
4. Falsification summary paragraph.
"""
    return prompt, SYSTEM_INSTRUCTION
