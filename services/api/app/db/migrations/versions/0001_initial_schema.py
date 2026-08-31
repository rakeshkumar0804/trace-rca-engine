"""Initial database schema with pgvector support and isolated ground truth table

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-08-30 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Enable pgvector extension on PostgreSQL
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 2. Services table
    op.create_table(
        "services",
        sa.Column("name", sa.String(length=100), nullable=False, primary_key=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("owns_database", sa.Boolean(), nullable=False, default=False),
    )

    # 3. Service Dependencies table
    op.create_table(
        "service_dependencies",
        sa.Column("id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column("from_service", sa.String(length=100), nullable=False, index=True),
        sa.Column("to_service", sa.String(length=100), nullable=False, index=True),
        sa.Column("protocol", sa.String(length=50), nullable=False),
        sa.Column("request_type", sa.String(length=50), nullable=False),
        sa.Column("expected_latency_ms", sa.Float(), nullable=False),
        sa.Column("dependency_strength", sa.String(length=20), nullable=False),
    )

    # 4. Incidents table (investigator-facing)
    op.create_table(
        "incidents",
        sa.Column("incident_id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column("incident_type", sa.String(length=100), nullable=False, index=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("affected_services", sa.JSON(), nullable=False),
        sa.Column("expected_symptoms", sa.JSON(), nullable=False),
        sa.Column("distractor_event_ids", sa.JSON(), nullable=False),
        sa.Column("difficulty", sa.String(length=50), nullable=False),
        sa.Column("severity", sa.String(length=50), nullable=False),
    )

    # 5. Ground Truths table (CRITICAL ISOLATION - separate table)
    op.create_table(
        "ground_truths",
        sa.Column("incident_id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column("root_cause", sa.Text(), nullable=False),
        sa.Column("causal_chain", sa.JSON(), nullable=False),
        sa.Column("responsible_commit_sha", sa.String(length=100), nullable=True),
        sa.Column("responsible_deployment_id", sa.Uuid(), nullable=True),
    )

    # 6. Normalized Events table
    op.create_table(
        "normalized_events",
        sa.Column("id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column("incident_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("source", sa.String(length=50), nullable=False, index=True),
        sa.Column("entity", sa.String(length=100), nullable=False, index=True),
        sa.Column("event_type", sa.String(length=100), nullable=False, index=True),
        sa.Column("service", sa.String(length=100), nullable=True, index=True),
        sa.Column("severity", sa.String(length=50), nullable=True, index=True),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column("relationships", sa.JSON(), nullable=False),
    )
    op.create_index("idx_norm_inc_time", "normalized_events", ["incident_id", "timestamp"])
    op.create_index("idx_norm_inc_entity", "normalized_events", ["incident_id", "entity"])
    op.create_index("idx_norm_inc_service", "normalized_events", ["incident_id", "service"])

    # 7. Logs table (with vector embedding column)
    op.create_table(
        "logs",
        sa.Column("id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column("incident_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("service", sa.String(length=100), nullable=False, index=True),
        sa.Column("severity", sa.String(length=50), nullable=False, index=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("trace_id", sa.String(length=100), nullable=True, index=True),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("embedding", Vector(128) if bind.dialect.name == "postgresql" else sa.JSON(), nullable=True),
    )
    op.create_index("idx_logs_inc_time", "logs", ["incident_id", "timestamp"])
    op.create_index("idx_logs_inc_service", "logs", ["incident_id", "service"])

    # 8. Metrics table
    op.create_table(
        "metrics",
        sa.Column("id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column("incident_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("service", sa.String(length=100), nullable=False, index=True),
        sa.Column("metric_name", sa.String(length=100), nullable=False, index=True),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=False),
        sa.Column("labels", sa.JSON(), nullable=False),
    )
    op.create_index("idx_metrics_inc_service", "metrics", ["incident_id", "service"])
    op.create_index("idx_metrics_inc_time", "metrics", ["incident_id", "timestamp"])

    # 9. Traces table
    op.create_table(
        "traces",
        sa.Column("id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column("incident_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("trace_id", sa.String(length=100), nullable=False, index=True),
        sa.Column("span_id", sa.String(length=100), nullable=False, index=True),
        sa.Column("parent_span_id", sa.String(length=100), nullable=True, index=True),
        sa.Column("service", sa.String(length=100), nullable=False, index=True),
        sa.Column("operation", sa.String(length=200), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, index=True),
        sa.Column("attributes", sa.JSON(), nullable=False),
    )
    op.create_index("idx_traces_inc_trace", "traces", ["incident_id", "trace_id"])
    op.create_index("idx_traces_inc_time", "traces", ["incident_id", "start_time"])

    # 10. Deployments table
    op.create_table(
        "deployments",
        sa.Column("deployment_id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column("incident_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("service", sa.String(length=100), nullable=False, index=True),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("commit_sha", sa.String(length=100), nullable=False, index=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("environment", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
    )

    # 11. Commits table (with vector embedding column)
    op.create_table(
        "commits",
        sa.Column("commit_sha", sa.String(length=100), nullable=False, primary_key=True),
        sa.Column("incident_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("author", sa.String(length=100), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("repository", sa.String(length=100), nullable=False, index=True),
        sa.Column("files_changed", sa.JSON(), nullable=False),
        sa.Column("diff_summary", sa.Text(), nullable=False),
        sa.Column("symbols_changed", sa.JSON(), nullable=False),
        sa.Column("embedding", Vector(128) if bind.dialect.name == "postgresql" else sa.JSON(), nullable=True),
    )

    # 12. Database Events table
    op.create_table(
        "database_events",
        sa.Column("id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column("incident_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("database_name", sa.String(length=100), nullable=False, index=True),
        sa.Column("query_fingerprint", sa.Text(), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("connections_active", sa.Integer(), nullable=False),
        sa.Column("connections_max", sa.Integer(), nullable=False),
        sa.Column("locks_held", sa.Integer(), nullable=False),
        sa.Column("rows_affected", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, index=True),
    )
    op.create_index("idx_dbevents_inc_db", "database_events", ["incident_id", "database_name"])
    op.create_index("idx_dbevents_inc_time", "database_events", ["incident_id", "timestamp"])

    # 13. Alerts table (with vector embedding column)
    op.create_table(
        "alerts",
        sa.Column("id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column("incident_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("alert_type", sa.String(length=100), nullable=False, index=True),
        sa.Column("service", sa.String(length=100), nullable=False, index=True),
        sa.Column("severity", sa.String(length=50), nullable=False, index=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(128) if bind.dialect.name == "postgresql" else sa.JSON(), nullable=True),
    )
    op.create_index("idx_alerts_inc_service", "alerts", ["incident_id", "service"])
    op.create_index("idx_alerts_inc_time", "alerts", ["incident_id", "timestamp"])


def downgrade() -> None:
    op.drop_table("alerts")
    op.drop_table("database_events")
    op.drop_table("commits")
    op.drop_table("deployments")
    op.drop_table("traces")
    op.drop_table("metrics")
    op.drop_table("logs")
    op.drop_table("normalized_events")
    op.drop_table("ground_truths")
    op.drop_table("incidents")
    op.drop_table("service_dependencies")
    op.drop_table("services")
