"""TRACE Evaluation and Benchmark Framework."""

from .baseline_llm_only import BaselineResult, run_baseline
from .benchmark_incidents import BenchmarkIncidentSpec, get_benchmark_spec_suite, instantiate_benchmark_incident
from .metrics import (
    confidence_calibration,
    evidence_precision,
    hallucination_rate,
    root_cause_accuracy,
    top_k_accuracy,
)
from .runner import BenchmarkReport, run_full_benchmark

__all__ = [
    "BaselineResult",
    "BenchmarkIncidentSpec",
    "BenchmarkReport",
    "confidence_calibration",
    "evidence_precision",
    "get_benchmark_spec_suite",
    "hallucination_rate",
    "instantiate_benchmark_incident",
    "root_cause_accuracy",
    "run_baseline",
    "run_full_benchmark",
    "top_k_accuracy",
]
