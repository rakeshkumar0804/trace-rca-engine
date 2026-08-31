"""Benchmark incidents suite definition and instantiation.

Defines a balanced, reproducible 14-incident evaluation set across both supported
incident types (7x bad deployment DB exhaustion, 7x dependency failure cascade)
with fixed seeds [1, 2, 3, 4, 5, 6, 7].
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.generator import (
    generate_bad_deployment_db_exhaustion_incident,
    generate_dependency_failure_cascade_incident,
    generate_healthy_environment,
)
from app.generator.incidents.incident_types import IncidentType
from app.schemas.incidents import Incident


@dataclass(frozen=True)
class BenchmarkIncidentSpec:
    benchmark_id: str
    incident_type: str
    seed: int
    duration_minutes: int = 15
    description: str = ""


# 14 distinct benchmark specifications: 7 for each incident type with seeds 1..7
BENCHMARK_SUITE_SPECS: list[BenchmarkIncidentSpec] = [
    # 7x Bad Deployment -> DB connection pool exhaustion
    BenchmarkIncidentSpec(
        benchmark_id="bench-dep-01",
        incident_type=IncidentType.BAD_DEPLOYMENT_DB_EXHAUSTION.value,
        seed=1,
        description="Checkout service bad deployment (seed=1)",
    ),
    BenchmarkIncidentSpec(
        benchmark_id="bench-dep-02",
        incident_type=IncidentType.BAD_DEPLOYMENT_DB_EXHAUSTION.value,
        seed=2,
        description="Checkout service bad deployment (seed=2)",
    ),
    BenchmarkIncidentSpec(
        benchmark_id="bench-dep-03",
        incident_type=IncidentType.BAD_DEPLOYMENT_DB_EXHAUSTION.value,
        seed=3,
        description="Checkout service bad deployment (seed=3)",
    ),
    BenchmarkIncidentSpec(
        benchmark_id="bench-dep-04",
        incident_type=IncidentType.BAD_DEPLOYMENT_DB_EXHAUSTION.value,
        seed=4,
        description="Checkout service bad deployment (seed=4)",
    ),
    BenchmarkIncidentSpec(
        benchmark_id="bench-dep-05",
        incident_type=IncidentType.BAD_DEPLOYMENT_DB_EXHAUSTION.value,
        seed=5,
        description="Checkout service bad deployment (seed=5)",
    ),
    BenchmarkIncidentSpec(
        benchmark_id="bench-dep-06",
        incident_type=IncidentType.BAD_DEPLOYMENT_DB_EXHAUSTION.value,
        seed=6,
        description="Checkout service bad deployment (seed=6)",
    ),
    BenchmarkIncidentSpec(
        benchmark_id="bench-dep-07",
        incident_type=IncidentType.BAD_DEPLOYMENT_DB_EXHAUSTION.value,
        seed=7,
        description="Checkout service bad deployment (seed=7)",
    ),
    # 7x Dependency Failure Cascade
    BenchmarkIncidentSpec(
        benchmark_id="bench-casc-01",
        incident_type=IncidentType.DEPENDENCY_FAILURE_CASCADE.value,
        seed=11,
        description="Payment service thread saturation cascading to checkout (seed=11)",
    ),
    BenchmarkIncidentSpec(
        benchmark_id="bench-casc-02",
        incident_type=IncidentType.DEPENDENCY_FAILURE_CASCADE.value,
        seed=12,
        description="Payment service thread saturation cascading to checkout (seed=12)",
    ),
    BenchmarkIncidentSpec(
        benchmark_id="bench-casc-03",
        incident_type=IncidentType.DEPENDENCY_FAILURE_CASCADE.value,
        seed=13,
        description="Payment service thread saturation cascading to checkout (seed=13)",
    ),
    BenchmarkIncidentSpec(
        benchmark_id="bench-casc-04",
        incident_type=IncidentType.DEPENDENCY_FAILURE_CASCADE.value,
        seed=14,
        description="Payment service thread saturation cascading to checkout (seed=14)",
    ),
    BenchmarkIncidentSpec(
        benchmark_id="bench-casc-05",
        incident_type=IncidentType.DEPENDENCY_FAILURE_CASCADE.value,
        seed=15,
        description="Payment service thread saturation cascading to checkout (seed=15)",
    ),
    BenchmarkIncidentSpec(
        benchmark_id="bench-casc-06",
        incident_type=IncidentType.DEPENDENCY_FAILURE_CASCADE.value,
        seed=16,
        description="Payment service thread saturation cascading to checkout (seed=16)",
    ),
    BenchmarkIncidentSpec(
        benchmark_id="bench-casc-07",
        incident_type=IncidentType.DEPENDENCY_FAILURE_CASCADE.value,
        seed=17,
        description="Payment service thread saturation cascading to checkout (seed=17)",
    ),
    # 5x Memory Leak with Red-Herring Deployment (Hard/Falsification test)
    BenchmarkIncidentSpec(
        benchmark_id="bench-mem-01",
        incident_type=IncidentType.MEMORY_LEAK_MASKED_DEPLOYMENT.value,
        seed=21,
        duration_minutes=45,
        description="Checkout service memory leak masked by coincidental caching deployment (seed=21)",
    ),
    BenchmarkIncidentSpec(
        benchmark_id="bench-mem-02",
        incident_type=IncidentType.MEMORY_LEAK_MASKED_DEPLOYMENT.value,
        seed=22,
        duration_minutes=45,
        description="Checkout service memory leak masked by coincidental caching deployment (seed=22)",
    ),
    BenchmarkIncidentSpec(
        benchmark_id="bench-mem-03",
        incident_type=IncidentType.MEMORY_LEAK_MASKED_DEPLOYMENT.value,
        seed=23,
        duration_minutes=45,
        description="Checkout service memory leak masked by coincidental caching deployment (seed=23)",
    ),
    BenchmarkIncidentSpec(
        benchmark_id="bench-mem-04",
        incident_type=IncidentType.MEMORY_LEAK_MASKED_DEPLOYMENT.value,
        seed=24,
        duration_minutes=45,
        description="Checkout service memory leak masked by coincidental caching deployment (seed=24)",
    ),
    BenchmarkIncidentSpec(
        benchmark_id="bench-mem-05",
        incident_type=IncidentType.MEMORY_LEAK_MASKED_DEPLOYMENT.value,
        seed=25,
        duration_minutes=45,
        description="Checkout service memory leak masked by coincidental caching deployment (seed=25)",
    ),
]


def get_benchmark_spec_suite() -> list[BenchmarkIncidentSpec]:
    """Returns the immutable 19-spec benchmark suite."""
    return list(BENCHMARK_SUITE_SPECS)


def instantiate_benchmark_incident(
    spec: BenchmarkIncidentSpec,
    start_time: datetime | None = None,
) -> tuple[Incident, dict[str, list[Any]]]:
    """Deterministically instantiates a benchmark incident and its observable evidence bundle."""
    incident_start = start_time or datetime(2026, 8, 30, 14, 0, 0, tzinfo=timezone.utc)
    base_env = generate_healthy_environment(
        seed=spec.seed,
        start=incident_start,
        duration_minutes=spec.duration_minutes,
    )

    if spec.incident_type == IncidentType.BAD_DEPLOYMENT_DB_EXHAUSTION.value:
        return generate_bad_deployment_db_exhaustion_incident(
            seed=spec.seed,
            base_environment=base_env,
            incident_start=incident_start,
            duration_minutes=spec.duration_minutes,
        )
    elif spec.incident_type == IncidentType.DEPENDENCY_FAILURE_CASCADE.value:
        return generate_dependency_failure_cascade_incident(
            seed=spec.seed,
            base_environment=base_env,
            incident_start=incident_start,
            duration_minutes=spec.duration_minutes,
        )
    elif spec.incident_type == IncidentType.MEMORY_LEAK_MASKED_DEPLOYMENT.value:
        from app.generator.incidents.memory_leak_masked_deployment import (
            generate_memory_leak_masked_deployment_incident,
        )
        return generate_memory_leak_masked_deployment_incident(
            seed=spec.seed,
            base_environment=base_env,
            incident_start=incident_start,
            duration_minutes=spec.duration_minutes,
        )
    else:
        raise ValueError(f"Unsupported benchmark incident type: {spec.incident_type}")
