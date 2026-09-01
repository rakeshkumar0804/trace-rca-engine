"""Error handling and user-facing message translation for TRACE investigations."""

import logging

logger = logging.getLogger("trace.orchestrator.error_handling")


def format_human_error_message(ex: Exception) -> str:
    """Translates raw technical / API exceptions into clean, helpful, user-facing explanations.
    
    Ensures raw JSON payloads, Python tracebacks, and API key details are NEVER shown in the UI.
    """
    err_str = str(ex).lower()

    if (
        "429" in err_str
        or "resource_exhausted" in err_str
        or "quota" in err_str
        or "rate limit" in err_str
        or "too many requests" in err_str
    ):
        return (
            "The live investigation could not complete because the AI provider's request quota "
            "was reached. Please run the pre-cached Demo Incident for a full verified "
            "investigation without API limits, or try again later."
        )

    if (
        "timeout" in err_str
        or "deadline" in err_str
        or "timed out" in err_str
        or "504" in err_str
        or "connection reset" in err_str
        or "connection error" in err_str
    ):
        return (
            "The investigation timed out while communicating with the telemetry analysis service. "
            "Please try running the pre-cached Demo Incident or try again."
        )

    if (
        "validation" in err_str
        or "json" in err_str
        or "schema" in err_str
        or "parse" in err_str
    ):
        return (
            "The model response could not be validated against the strict RCA schema. "
            "Please run the pre-cached Demo Incident to see a verified investigation."
        )

    return (
        "The investigation was paused due to a temporary service interruption. "
        "Please try running the pre-cached Demo Incident."
    )
