from typing import Literal
from pydantic import BaseModel, Field


class ServiceDependency(BaseModel):
    """Directed dependency link between two services defining communication protocol, type, and criticality."""
    from_service: str
    to_service: str
    protocol: str
    request_type: str
    expected_latency_ms: float
    dependency_strength: Literal["hard", "soft"]


class ServiceDefinition(BaseModel):
    """Service metadata, ownership attributes, and outgoing upstream/downstream dependency graph definitions."""
    name: str
    description: str
    owns_database: bool
    dependencies: list[ServiceDependency] = Field(default_factory=list)
