from collections.abc import Callable
from enum import Enum
from typing import Any

from app.schemas.incidents import Incident


class IncidentType(str, Enum):
    """Available incident scenario types in TRACE benchmark engine."""
    BAD_DEPLOYMENT_DB_EXHAUSTION = "bad_deployment_db_exhaustion"
    DEPENDENCY_FAILURE_CASCADE = "dependency_failure_cascade"
    MEMORY_LEAK_MASKED_DEPLOYMENT = "memory_leak_masked_deployment"


IncidentGeneratorFn = Callable[[int, dict[str, list[Any]], Any], tuple[Incident, dict[str, list[Any]]]]

_REGISTRY: dict[str, IncidentGeneratorFn] = {}


def register_incident_type(name: str, generator_fn: IncidentGeneratorFn) -> None:
    """Registers an incident scenario generator function in the global registry."""
    _REGISTRY[name] = generator_fn


def get_incident_generator(name: str) -> IncidentGeneratorFn:
    """Retrieves an incident scenario generator function by name."""
    if name not in _REGISTRY:
        raise KeyError(f"Incident type '{name}' is not registered. Available: {list(_REGISTRY.keys())}")
    return _REGISTRY[name]


def list_incident_types() -> list[str]:
    """Returns a list of all registered incident scenario names."""
    return list(_REGISTRY.keys())
