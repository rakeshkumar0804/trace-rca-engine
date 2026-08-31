# CRITICAL ISOLATION ENFORCEMENT: This prompt builder processes ONLY investigator-facing evidence.
# It must NEVER receive or include 'ground_truths' in any prompt.

from app.schemas.events import NormalizedEvent
from app.schemas.hypotheses import Hypothesis

SYSTEM_INSTRUCTION = """You are TRACE's Root-Cause Falsification Engine.
Your goal is NOT to defend the current hypothesis, but to actively propose testable questions that could DISPROVE or FALSIFY it.
Think like an adversarial SRE investigator:
- What telemetry would prove this hypothesis is false?
- Did pre-existing anomalies exist before the implicated event?
- Did other unrelated services fail independently?
- Were the alleged symptoms present in places where this cause could not reach?

Formulate 3 to 5 clear, concrete falsification questions with specific retrieval hints.
"""


def build_falsification_questions_prompt(
    hypothesis: Hypothesis,
    existing_evidence: list[NormalizedEvent],
    timeline_summary: str,
) -> tuple[str, str]:
    """Constructs prompt for generating falsification questions against a candidate hypothesis."""
    evidence_lines = []
    for idx, e in enumerate(existing_evidence[:10]):
        msg = e.attributes.get("message") or e.attributes.get("description") or e.event_type
        evidence_lines.append(f"- [{e.source.value.upper()}] ID={e.id} Time={e.timestamp.isoformat()} Service={e.service or e.entity}: {msg}")

    evidence_block = "\n".join(evidence_lines) if evidence_lines else "No specific evidence attached yet."

    prompt = f"""### Incident Timeline Summary
{timeline_summary}

### Candidate Root-Cause Hypothesis Under Investigation
Title: {hypothesis.title}
Description: {hypothesis.description}
Current Score: {hypothesis.score.final_score}/100

### Evidence Currently Supporting This Hypothesis
{evidence_block}

### Task
Generate a set of 3 to 5 falsification questions targeting this hypothesis.
For each question:
1. Explain the rationale (how it could prove the hypothesis wrong).
2. Provide a specific retrieval hint (e.g., query terms or entity names to search).
3. Specify the retrieval strategy ('temporal', 'entity', 'semantic', 'relationship', or 'change').
"""
    return prompt, SYSTEM_INSTRUCTION
