# CRITICAL ISOLATION ENFORCEMENT: This prompt builder processes ONLY investigator-facing evidence.
# It must NEVER receive or include 'ground_truths' in any prompt.

from app.schemas.events import NormalizedEvent
from app.schemas.hypotheses import Hypothesis
from ..schemas import FalsificationQuestion

SYSTEM_INSTRUCTION = """You are TRACE's Evidence Interpretation & Contradiction Analyzer.
You evaluate retrieved system telemetry to determine whether the hypothesis under evaluation is supported or contradicted.

CRITICAL VERDICT DEFINITIONS:
- 'supports': The evidence confirms the hypothesis is the true root cause (e.g. confirms the deployment or degradation introduced the failure, confirms the service was healthy prior to release, or confirms that alternative causes did NOT happen).
- 'contradicts': The evidence DISPROVES or FALSIFIES the hypothesis (e.g. proves that errors occurred before the deployment, proves the service was completely healthy and had 0 errors during the outage, or proves another unrelated failure happened first).
- 'inconclusive': Retrieved evidence is empty, unrelated, or insufficient to prove or disprove.

IMPORTANT: Do NOT mark 'contradicts' simply because an alternative failure was absent. If an inquiry shows alternative causes did NOT occur, that SUPPORTS the hypothesis under evaluation!"""


def build_evidence_interpretation_prompt(
    hypothesis: Hypothesis,
    question: FalsificationQuestion,
    retrieved_evidence: list[NormalizedEvent],
) -> tuple[str, str]:
    """Constructs prompt for evaluating retrieved evidence against a falsification question."""
    evidence_lines = []
    for e in retrieved_evidence:
        sev = e.severity.value if e.severity is not None else "info"
        msg = (
            e.attributes.get("message")
            or e.attributes.get("description")
            or e.attributes.get("diff_summary")
            or f"{e.event_type} (severity={sev})"
        )
        evidence_lines.append(
            f"- Evidence ID: {e.id}\n"
            f"  Source: {e.source.value.upper()} | Time: {e.timestamp.isoformat()} | Entity: {e.entity}\n"
            f"  Content: {msg}\n"
        )

    evidence_block = "\n".join(evidence_lines) if evidence_lines else "No matching evidence was retrieved for this question."

    prompt = f"""### Hypothesis Under Evaluation
Title: {hypothesis.title}
Description: {hypothesis.description}

### Falsification Question
Question: {question.question}
Rationale: {question.rationale}

### Retrieved Telemetry Evidence (Available Evidence IDs for Citation)
{evidence_block}

### Task
Analyze the retrieved evidence and determine the verdict for this question ('supports', 'contradicts', or 'inconclusive').
Explain your reasoning clearly and cite the exact Evidence IDs from above that substantiate your verdict.
"""
    return prompt, SYSTEM_INSTRUCTION


def build_batch_evidence_interpretation_prompt(
    hypothesis: Hypothesis,
    question_evidence_pairs: list[tuple[FalsificationQuestion, list[NormalizedEvent]]],
) -> tuple[str, str]:
    """Constructs prompt for evaluating retrieved evidence across multiple questions in a single round trip."""
    sections = []
    for idx, (q, evts) in enumerate(question_evidence_pairs, start=1):
        ev_lines = []
        for e in evts:
            sev = e.severity.value if e.severity is not None else "info"
            msg = (
                e.attributes.get("message")
                or e.attributes.get("description")
                or e.attributes.get("diff_summary")
                or f"{e.event_type} (severity={sev})"
            )
            ev_lines.append(
                f"  - Evidence ID: {e.id}\n"
                f"    Source: {e.source.value.upper()} | Time: {e.timestamp.isoformat()} | Entity: {e.entity}\n"
                f"    Content: {msg}"
            )
        ev_block = "\n".join(ev_lines) if ev_lines else "  No matching evidence retrieved."
        sections.append(
            f"--- Question {idx} ---\n"
            f"Question: {q.question}\n"
            f"Rationale: {q.rationale}\n"
            f"Retrieved Evidence (cite ONLY from these IDs):\n{ev_block}\n"
        )

    all_sections = "\n".join(sections)
    prompt = f"""### Hypothesis Under Evaluation
Title: {hypothesis.title}
Description: {hypothesis.description}

### Falsification Questions and Retrieved Evidence
{all_sections}

### Task
For each question above, determine whether the retrieved telemetry supports or refutes the Hypothesis Under Evaluation being the root cause. Provide an EvidenceVerdict in the verdicts list:
- question: the exact question text
- evidence_ids_cited: list of cited Evidence IDs from that question's section
- verdict: 'supports' (corroborates that this hypothesis is the root cause), 'contradicts' (refutes this hypothesis), or 'inconclusive'
- reasoning: specific explanation based on the telemetry
"""
    return prompt, SYSTEM_INSTRUCTION
