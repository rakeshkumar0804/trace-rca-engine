from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB

from .base import Base

EMBEDDING_DIM = 384


class VectorType(TypeDecorator):
    """Custom SQLAlchemy type that uses pgvector.Vector on PostgreSQL and JSON on SQLite/others."""
    impl = JSON
    cache_ok = True

    def __init__(self, dim: int = EMBEDDING_DIM, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dim = dim

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, (list, tuple)):
            return [float(x) for x in value]
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, (list, tuple)):
            return [float(x) for x in value]
        return value


class ServiceORM(Base):
    """Registered microservice definition in the system topology."""
    __tablename__ = "services"

    name = Column(String(100), primary_key=True)
    description = Column(Text, nullable=False)
    owns_database = Column(Boolean, nullable=False, default=False)


class ServiceDependencyORM(Base):
    """Directed dependency link between two microservices."""
    __tablename__ = "service_dependencies"

    id = Column(Uuid, primary_key=True, default=uuid4)
    from_service = Column(String(100), nullable=False, index=True)
    to_service = Column(String(100), nullable=False, index=True)
    protocol = Column(String(50), nullable=False)
    request_type = Column(String(50), nullable=False)
    expected_latency_ms = Column(Float, nullable=False)
    dependency_strength = Column(String(20), nullable=False)


class IncidentORM(Base):
    """Investigator-facing incident record (contains NO ground truth)."""
    __tablename__ = "incidents"

    incident_id = Column(Uuid, primary_key=True)
    incident_type = Column(String(100), nullable=False, index=True)
    start_time = Column(DateTime(timezone=True), nullable=False, index=True)
    end_time = Column(DateTime(timezone=True), nullable=True)
    affected_services = Column(JSON, nullable=False)
    expected_symptoms = Column(JSON, nullable=False)
    distractor_event_ids = Column(JSON, nullable=False, default=list)
    difficulty = Column(String(50), nullable=False)
    severity = Column(String(50), nullable=False)


class GroundTruthORM(Base):
    """CRITICAL ISOLATION: Benchmark evaluation ground truth stored in a genuinely separate table.
    
    This table must NEVER be queried, joined, or foreign-keyed by investigator-facing retrieval code.
    """
    __tablename__ = "ground_truths"

    incident_id = Column(Uuid, primary_key=True)
    root_cause = Column(Text, nullable=False)
    causal_chain = Column(JSON, nullable=False)
    responsible_commit_sha = Column(String(100), nullable=True)
    responsible_deployment_id = Column(Uuid, nullable=True)


class NormalizedEventORM(Base):
    """Normalized unified event schema representation."""
    __tablename__ = "normalized_events"

    id = Column(Uuid, primary_key=True, default=uuid4)
    incident_id = Column(Uuid, nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    source = Column(String(50), nullable=False, index=True)
    entity = Column(String(100), nullable=False, index=True)
    event_type = Column(String(100), nullable=False, index=True)
    service = Column(String(100), nullable=True, index=True)
    severity = Column(String(50), nullable=True, index=True)
    attributes = Column(JSON, nullable=False, default=dict)
    relationships = Column(JSON, nullable=False, default=list)

    __table_args__ = (
        Index("idx_norm_inc_time", "incident_id", "timestamp"),
        Index("idx_norm_inc_entity", "incident_id", "entity"),
        Index("idx_norm_inc_service", "incident_id", "service"),
    )


class LogORM(Base):
    """Raw application log telemetry."""
    __tablename__ = "logs"

    id = Column(Uuid, primary_key=True, default=uuid4)
    incident_id = Column(Uuid, nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    service = Column(String(100), nullable=False, index=True)
    severity = Column(String(50), nullable=False, index=True)
    message = Column(Text, nullable=False)
    trace_id = Column(String(100), nullable=True, index=True)
    request_id = Column(String(100), nullable=True)
    metadata_json = Column(JSON, nullable=False, default=dict)
    embedding = Column(VectorType(EMBEDDING_DIM), nullable=True)

    __table_args__ = (
        Index("idx_logs_inc_time", "incident_id", "timestamp"),
        Index("idx_logs_inc_service", "incident_id", "service"),
    )


class MetricORM(Base):
    """Point-in-time quantitative service telemetry."""
    __tablename__ = "metrics"

    id = Column(Uuid, primary_key=True, default=uuid4)
    incident_id = Column(Uuid, nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    service = Column(String(100), nullable=False, index=True)
    metric_name = Column(String(100), nullable=False, index=True)
    value = Column(Float, nullable=False)
    unit = Column(String(50), nullable=False)
    labels = Column(JSON, nullable=False, default=dict)

    __table_args__ = (
        Index("idx_metrics_inc_service", "incident_id", "service"),
        Index("idx_metrics_inc_time", "incident_id", "timestamp"),
    )


class TraceSpanORM(Base):
    """Distributed tracing span record."""
    __tablename__ = "traces"

    id = Column(Uuid, primary_key=True, default=uuid4)
    incident_id = Column(Uuid, nullable=False, index=True)
    trace_id = Column(String(100), nullable=False, index=True)
    span_id = Column(String(100), nullable=False, index=True)
    parent_span_id = Column(String(100), nullable=True, index=True)
    service = Column(String(100), nullable=False, index=True)
    operation = Column(String(200), nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=False, index=True)
    duration_ms = Column(Float, nullable=False)
    status = Column(String(50), nullable=False, index=True)
    attributes = Column(JSON, nullable=False, default=dict)

    __table_args__ = (
        Index("idx_traces_inc_trace", "incident_id", "trace_id"),
        Index("idx_traces_inc_time", "incident_id", "start_time"),
    )


class DeploymentORM(Base):
    """Service release deployment rollout."""
    __tablename__ = "deployments"

    deployment_id = Column(Uuid, primary_key=True)
    incident_id = Column(Uuid, nullable=False, index=True)
    service = Column(String(100), nullable=False, index=True)
    version = Column(String(50), nullable=False)
    commit_sha = Column(String(100), nullable=False, index=True)
    started_at = Column(DateTime(timezone=True), nullable=False, index=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    environment = Column(String(50), nullable=False)
    status = Column(String(50), nullable=False)


class GitCommitORM(Base):
    """Version control change commit."""
    __tablename__ = "commits"

    commit_sha = Column(String(100), primary_key=True)
    incident_id = Column(Uuid, nullable=False, index=True)
    author = Column(String(100), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    repository = Column(String(100), nullable=False, index=True)
    files_changed = Column(JSON, nullable=False, default=list)
    diff_summary = Column(Text, nullable=False)
    symbols_changed = Column(JSON, nullable=False, default=list)
    embedding = Column(VectorType(EMBEDDING_DIM), nullable=True)


class DatabaseEventORM(Base):
    """Database query execution, lock, and connection pool state."""
    __tablename__ = "database_events"

    id = Column(Uuid, primary_key=True, default=uuid4)
    incident_id = Column(Uuid, nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    database_name = Column(String(100), nullable=False, index=True)
    query_fingerprint = Column(Text, nullable=False)
    duration_ms = Column(Float, nullable=False)
    connections_active = Column(Integer, nullable=False)
    connections_max = Column(Integer, nullable=False)
    locks_held = Column(Integer, nullable=False)
    rows_affected = Column(Integer, nullable=False)
    status = Column(String(50), nullable=False, index=True)

    __table_args__ = (
        Index("idx_dbevents_inc_db", "incident_id", "database_name"),
        Index("idx_dbevents_inc_time", "incident_id", "timestamp"),
    )


class AlertORM(Base):
    """Triggered monitoring alert notification."""
    __tablename__ = "alerts"

    id = Column(Uuid, primary_key=True, default=uuid4)
    incident_id = Column(Uuid, nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    alert_type = Column(String(100), nullable=False, index=True)
    service = Column(String(100), nullable=False, index=True)
    severity = Column(String(50), nullable=False, index=True)
    description = Column(Text, nullable=False)
    embedding = Column(VectorType(EMBEDDING_DIM), nullable=True)

    __table_args__ = (
        Index("idx_alerts_inc_service", "incident_id", "service"),
        Index("idx_alerts_inc_time", "incident_id", "timestamp"),
    )


class InvestigationORM(Base):
    """Orchestrated investigation session."""
    __tablename__ = "investigations"

    investigation_id = Column(Uuid, primary_key=True, default=uuid4)
    incident_id = Column(Uuid, nullable=False, index=True)
    final_state = Column(String(50), nullable=False, index=True)
    leading_hypothesis_id = Column(Uuid, nullable=True)
    confidence = Column(Float, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False, index=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    rca_narrative = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_investigations_incident_time", "incident_id", "started_at"),
    )


class InvestigationStepORM(Base):
    """Incremental state transition step within an investigation."""
    __tablename__ = "investigation_steps"

    id = Column(Uuid, primary_key=True, default=uuid4)
    investigation_id = Column(Uuid, nullable=False, index=True)
    step_number = Column(Integer, nullable=False)
    state = Column(String(50), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    summary = Column(Text, nullable=False)
    details = Column(JSON, nullable=False, default=dict)

    __table_args__ = (
        Index("idx_inv_steps_inv_num", "investigation_id", "step_number"),
    )

