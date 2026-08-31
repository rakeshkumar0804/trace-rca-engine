from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field

from app.schemas.hypotheses import Hypothesis, HypothesisScore, HypothesisStatus


class FalsificationQuestion(BaseModel):
    """A specific testable question designed to falsify a root-cause hypothesis."""
    question: str
    rationale: str
    retrieval_hint: str
    retrieval_strategy: Literal["temporal", "entity", "semantic", "relationship", "change"] = "semantic"
    query_or_filter: str


class FalsificationQuestionSet(BaseModel):
    """Set of 3-5 falsification questions targeting a specific hypothesis."""
    hypothesis_id: UUID
    questions: list[FalsificationQuestion] = Field(..., min_length=1, max_length=5)


class EvidenceVerdict(BaseModel):
    """LLM or deterministic assessment of retrieved evidence against a specific falsification question."""
    question: str
    evidence_ids_cited: list[UUID] = Field(default_factory=list)
    verdict: Literal["supports", "contradicts", "inconclusive"]
    reasoning: str
    verdict_source: Literal["llm_generated", "deterministic_trend_check"] = "llm_generated"


class InterpretationResponse(BaseModel):
    """Container of evidence evaluation verdicts across falsification queries."""
    verdicts: list[EvidenceVerdict]


class ClaimCitation(BaseModel):
    """An individual factual claim linked to validated evidence IDs."""
    claim: str
    evidence_ids: list[UUID] = Field(default_factory=list)


class HypothesisSummaryNarrative(BaseModel):
    """Structured root-cause analysis narrative where every claim cites validated evidence."""
    title: str
    executive_summary: str
    claims: list[ClaimCitation]
    falsification_summary: str


class SelfCritiqueStep(BaseModel):
    """Audit record of a single iteration of hypothesis falsification search and re-scoring."""
    step_number: int
    hypothesis_id: UUID
    hypothesis_title: str
    questions_asked: list[FalsificationQuestion]
    retrieved_evidence_ids: list[UUID]
    verdicts: list[EvidenceVerdict]
    score_before: HypothesisScore
    score_after: HypothesisScore
    status_before: HypothesisStatus
    status_after: HypothesisStatus
    confidence_score: float
    confidence_rationale: str


class SelfCritiqueResult(BaseModel):
    """Complete trace of the self-critique / falsification loop across hypotheses."""
    incident_id: UUID
    initial_top_hypothesis_id: UUID
    final_leading_hypothesis_id: UUID
    iterations_run: int
    steps: list[SelfCritiqueStep]
    final_ranked_hypotheses: list[Hypothesis]
