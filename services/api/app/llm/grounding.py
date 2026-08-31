# CRITICAL ISOLATION ENFORCEMENT: This grounding module operates ONLY on investigator-facing evidence.
# It must NEVER join or query the 'ground_truths' table.

from uuid import UUID
from app.schemas.hypotheses import HypothesisScore
from .schemas import EvidenceVerdict


def validate_evidence_citations(
    claimed_ids: list[UUID],
    available_ids: set[UUID],
) -> tuple[list[UUID], list[UUID]]:
    """Validates claimed evidence UUIDs against the set of evidence provided in context.
    
    Returns (valid_ids, invalid_ids).
    Enforces Rule 3: The LLM cannot invent evidence citations.
    """
    valid: list[UUID] = []
    invalid: list[UUID] = []

    for cid in claimed_ids:
        if cid in available_ids:
            if cid not in valid:
                valid.append(cid)
        else:
            if cid not in invalid:
                invalid.append(cid)

    return valid, invalid


def sanitize_verdicts_grounding(
    verdicts: list[EvidenceVerdict],
    available_ids: set[UUID],
) -> tuple[list[EvidenceVerdict], list[UUID]]:
    """Sanitizes evidence verdicts, removing ungrounded evidence IDs and returning rejected IDs.
    
    If a verdict cites an evidence ID that was not provided in context, that citation is rejected.
    """
    sanitized: list[EvidenceVerdict] = []
    all_invalid: list[UUID] = []

    for v in verdicts:
        valid_ids, invalid_ids = validate_evidence_citations(v.evidence_ids_cited, available_ids)
        all_invalid.extend(invalid_ids)
        
        # If verdict claimed evidence but ALL were invalid/hallucinated, mark inconclusive
        verdict_type = v.verdict
        if v.evidence_ids_cited and not valid_ids and verdict_type != "inconclusive":
            verdict_type = "inconclusive"
            reasoning = f"{v.reasoning} [NOTE: Cited evidence IDs were ungrounded and rejected]."
        else:
            reasoning = v.reasoning

        sanitized.append(
            EvidenceVerdict(
                question=v.question,
                evidence_ids_cited=valid_ids,
                verdict=verdict_type,
                reasoning=reasoning,
            )
        )

    return sanitized, all_invalid


def derive_deterministic_confidence(
    score: HypothesisScore,
    contradiction_count: int,
    unexplained_symptom_count: int,
    distinct_sources_count: int,
) -> float:
    """Derives confidence deterministically from score, evidence diversity, and penalties.
    
    Enforces Rule 4: Confidence is NEVER an LLM-generated number.
    Formula:
    confidence = score.final_score 
                 + (distinct_sources_count * 3.0) 
                 - (contradiction_count * 20.0) 
                 - (unexplained_symptom_count * 10.0)
    clamped to [0.0, 100.0].
    """
    base = score.final_score
    diversity_bonus = min(12.0, distinct_sources_count * 3.0)
    contra_deduction = contradiction_count * 20.0
    unexplained_deduction = unexplained_symptom_count * 10.0

    raw_confidence = base + diversity_bonus - contra_deduction - unexplained_deduction
    return max(0.0, min(100.0, round(raw_confidence, 2)))
