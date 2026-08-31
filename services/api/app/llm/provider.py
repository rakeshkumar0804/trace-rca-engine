# CRITICAL ISOLATION ENFORCEMENT: This LLM provider module processes ONLY investigator-facing evidence.
# It must NEVER receive or include 'ground_truths' in any prompt.

from abc import ABC, abstractmethod
import json
import os
from typing import TypeVar
from uuid import UUID, uuid4

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

from .schemas import (
    ClaimCitation,
    EvidenceVerdict,
    FalsificationQuestion,
    FalsificationQuestionSet,
    HypothesisSummaryNarrative,
    InterpretationResponse,
)

T = TypeVar("T", bound=BaseModel)


class LLMProvider(ABC):
    """Abstract interface for structured LLM interactions across the investigation engine."""

    @abstractmethod
    async def generate_structured(
        self,
        prompt: str,
        response_schema: type[T],
        system_instruction: str | None = None,
        max_retries: int = 2,
    ) -> T:
        """Generates a structured Pydantic response conforming to the provided response_schema."""
        pass


class MockLLMProvider(LLMProvider):
    """Deterministic, rule-based mock provider for fast offline unit tests and CI.
    
    Produces grounded, schema-valid structured responses without network calls or external APIs.
    """

    def __init__(self, override_responses: dict[type[BaseModel], BaseModel] | None = None):
        self.override_responses = override_responses or {}
        self.recorded_prompts: list[str] = []

    async def generate_structured(
        self,
        prompt: str,
        response_schema: type[T],
        system_instruction: str | None = None,
        max_retries: int = 2,
    ) -> T:
        self.recorded_prompts.append(prompt)

        # Check explicit overrides
        if response_schema in self.override_responses:
            return self.override_responses[response_schema]  # type: ignore

        # 1. Falsification Questions Generation
        if issubclass(response_schema, FalsificationQuestionSet):
            # Extract hypothesis title specifically from prompt
            title_text = ""
            for line in prompt.splitlines():
                if line.startswith("Title:"):
                    title_text = line.lower()
                    break

            if "payment" in title_text or "payment_db" in title_text:
                questions = [
                    FalsificationQuestion(
                        question="Are payment-service logs showing active connection pool exhaustion or query timeouts?",
                        rationale="If payment-service DB metrics are healthy with 0 timeout errors, payment_db is not the root cause.",
                        retrieval_hint="Search payment-service database events and error logs",
                        retrieval_strategy="semantic",
                        query_or_filter="payment-service database connection timeout error",
                    ),
                    FalsificationQuestion(
                        question="Did payment gateway RPC latency spike prior to checkout errors?",
                        rationale="If payment latency remained baseline (85ms), payment-service was not degraded.",
                        retrieval_hint="Retrieve metrics for payment-service",
                        retrieval_strategy="entity",
                        query_or_filter="payment-service",
                    ),
                ]
            elif "checkout" in title_text or "deployment" in title_text:
                questions = [
                    FalsificationQuestion(
                        question="Were error rates in checkout-service normal immediately prior to the deployment?",
                        rationale="If checkout-service had identical high 5xx errors before v2.15.0 was deployed, the deployment is not the causal trigger.",
                        retrieval_hint="Check logs and metric rates in the 10 minutes before deployment",
                        retrieval_strategy="temporal",
                        query_or_filter="checkout-service",
                    ),
                    FalsificationQuestion(
                        question="Did database connection pool timeouts begin concurrently with or after the deployment?",
                        rationale="If connection exhaustion started before deployment, the release did not cause the DB saturation.",
                        retrieval_hint="Search for database connection pool timeout logs",
                        retrieval_strategy="semantic",
                        query_or_filter="database connection timeout pool exhausted",
                    ),
                    FalsificationQuestion(
                        question="Did other services with no database access experience independent upstream outages?",
                        rationale="If auth-service was completely down, the failure originated elsewhere in the gateway.",
                        retrieval_hint="Check alerts and logs for auth-service",
                        retrieval_strategy="entity",
                        query_or_filter="auth-service",
                    ),
                ]
            else:
                questions = [
                    FalsificationQuestion(
                        question="Did external request traffic exceed the 99th percentile baseline?",
                        rationale="If total request RPS remained steady, traffic surge is falsified.",
                        retrieval_hint="Retrieve api-gateway request_rate metrics",
                        retrieval_strategy="entity",
                        query_or_filter="api-gateway",
                    ),
                    FalsificationQuestion(
                        question="Were memory usage levels elevated across worker nodes?",
                        rationale="If memory stayed at baseline (<70%), memory leak is falsified.",
                        retrieval_hint="Retrieve system memory metric points",
                        retrieval_strategy="entity",
                        query_or_filter="checkout-service",
                    ),
                ]

            return FalsificationQuestionSet(  # type: ignore
                hypothesis_id=uuid4(),
                questions=questions,
            )

        # 2. Evidence Interpretation Verdicts
        if issubclass(response_schema, InterpretationResponse):
            import re
            uuid_regex = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
            found_uuids = [UUID(m) for m in re.findall(uuid_regex, prompt)]

            # Extract all Question lines
            q_lines = [line.replace("Question:", "").strip() for line in prompt.splitlines() if line.startswith("Question:")]
            if not q_lines:
                q_lines = ["General inquiry"]

            verdicts: list[EvidenceVerdict] = []
            for q_text in q_lines:
                q_lower = q_text.lower()
                if "payment" in q_lower:
                    verdicts.append(
                        EvidenceVerdict(
                            question=q_text,
                            evidence_ids_cited=found_uuids[:2],
                            verdict="contradicts",
                            reasoning="Retrieved payment telemetry shows 0 error logs and normal baseline latency (85ms), contradicting payment database failure.",
                        )
                    )
                elif "traffic" in q_lower or "memory" in q_lower:
                    verdicts.append(
                        EvidenceVerdict(
                            question=q_text,
                            evidence_ids_cited=found_uuids[:2],
                            verdict="contradicts",
                            reasoning="Telemetry shows metric values within expected nominal baseline; traffic and memory pressure are refuted.",
                        )
                    )
                elif "checkout" in q_lower or "database connection" in q_lower or "error rates" in q_lower or "pool timeout" in q_lower or "deployment" in q_lower:
                    verdicts.append(
                        EvidenceVerdict(
                            question=q_text,
                            evidence_ids_cited=found_uuids[:2],
                            verdict="supports",
                            reasoning="Telemetry confirms telemetry was healthy prior to release and experienced severe connection acquisition timeouts post-deployment.",
                        )
                    )
                else:
                    verdicts.append(
                        EvidenceVerdict(
                            question=q_text,
                            evidence_ids_cited=found_uuids[:1],
                            verdict="inconclusive",
                            reasoning="Retrieved evidence does not directly corroborate or refute the inquiry.",
                        )
                    )

            return InterpretationResponse(verdicts=verdicts)  # type: ignore

        # 3. Hypothesis Summary Narrative
        if issubclass(response_schema, HypothesisSummaryNarrative):
            import re
            uuid_regex = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
            found_uuids = [UUID(m) for m in re.findall(uuid_regex, prompt)]

            return HypothesisSummaryNarrative(  # type: ignore
                title="Bad Deployment to checkout-service (v2.15.0)",
                executive_summary="Deployment v2.15.0 to checkout-service introduced an N+1 query regression that saturated the checkout_db connection pool.",
                claims=[
                    ClaimCitation(
                        claim="Deployment v2.15.0 completed 3 minutes before symptom onset.",
                        evidence_ids=found_uuids[:1],
                    ),
                    ClaimCitation(
                        claim="checkout_db connection acquisition timed out repeatedly after 5000ms.",
                        evidence_ids=found_uuids[1:3] if len(found_uuids) >= 3 else found_uuids[:1],
                    ),
                ],
                falsification_summary="Hypothesis survived falsification search across deployment logs and database saturation events with zero contradictions found.",
            )

        # 4. Baseline Prediction
        if response_schema.__name__ == "BaselinePrediction":
            if "payment" in prompt.lower():
                return response_schema(
                    predicted_root_cause="Downstream dependency degradation and thread pool exhaustion in payment-service",
                    primary_affected_service="payment-service",
                    failure_mechanism="dependency_failure",
                    confidence=75.0,
                    reasoning="Payment service thread saturation and 504 timeouts cascaded to checkout.",
                )
            return response_schema(
                predicted_root_cause="Bad deployment of checkout-service version v2.15.0 caused database connection pool exhaustion",
                primary_affected_service="checkout-service",
                failure_mechanism="bad_deployment",
                confidence=80.0,
                reasoning="Deployment completed shortly before latency and 500 errors spiked.",
            )

        raise ValueError(f"MockLLMProvider does not have a default fixture for schema: {response_schema}")


class GeminiProvider(LLMProvider):
    """Production LLM provider using Google Gemini API with native JSON schema enforcement."""

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "gemini-3.5-flash-lite",
    ):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.model_name = os.getenv("GEMINI_MODEL", model_name)
        self._client = None

        if self.api_key:
            try:
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
            except Exception as e:
                pass

    async def generate_structured(
        self,
        prompt: str,
        response_schema: type[T],
        system_instruction: str | None = None,
        max_retries: int = 4,
    ) -> T:
        if not self._client:
            raise RuntimeError(
                "GeminiProvider requires GEMINI_API_KEY or GOOGLE_API_KEY environment variable. "
                "For local testing and offline CI, use MockLLMProvider."
            )

        import asyncio
        from google.genai import types

        last_error = None
        current_prompt = prompt

        for attempt in range(max_retries + 1):
            try:
                response = self._client.models.generate_content(
                    model=self.model_name,
                    contents=current_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        response_mime_type="application/json",
                        response_schema=response_schema,
                        temperature=0.1,
                    ),
                )

                response_text = response.text
                if not response_text:
                    raise ValueError("Empty response received from Gemini API")

                # Parse and validate with Pydantic
                parsed_json = json.loads(response_text)
                return response_schema.model_validate(parsed_json)

            except Exception as e:
                last_error = e
                err_str = str(e).lower()

                # If rate limited (HTTP 429 / RESOURCE_EXHAUSTED) or transient 503/unavailable/timeout
                is_transient = (
                    "429" in err_str
                    or "resource_exhausted" in err_str
                    or "quota" in err_str
                    or "503" in err_str
                    or "unavailable" in err_str
                    or "timeout" in err_str
                    or "deadline" in err_str
                )
                if is_transient and attempt < max_retries:
                    import random
                    base_wait = 2.0 * (2 ** attempt)  # 2s, 4s, 8s, 16s
                    jitter = random.uniform(0.5, 1.5)
                    wait_time = base_wait * jitter
                    await asyncio.sleep(wait_time)
                    continue

                # Schema or validation error retry
                current_prompt = (
                    f"{prompt}\n\n[CORRECTION REQUIRED]: Your previous output failed schema validation with error: {e}. "
                    f"Please output valid JSON matching the exact schema."
                )

        raise RuntimeError(f"GeminiProvider failed structured generation after {max_retries} retries: {last_error}")


def get_llm_provider() -> LLMProvider:
    """Factory returning GeminiProvider if API key is configured, otherwise MockLLMProvider."""
    provider_name = os.getenv("LLM_PROVIDER", "").lower()
    if provider_name == "mock":
        return MockLLMProvider()

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if api_key:
        return GeminiProvider(api_key=api_key)

    return MockLLMProvider()
