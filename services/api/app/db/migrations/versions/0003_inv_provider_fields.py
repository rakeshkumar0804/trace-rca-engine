"""Add investigations and investigation_steps tables with LLM provider metadata

Revision ID: 0003_inv_provider_fields
Revises: 0002_vector_dim_384
Create Date: 2026-09-25 20:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic (must be <= 32 chars for PostgreSQL alembic_version)
revision: str = "0003_inv_provider_fields"
down_revision: Union[str, None] = "0002_vector_dim_384"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = insp.get_table_names()

    # 1. Handle investigations table
    if "investigations" not in tables:
        op.create_table(
            "investigations",
            sa.Column("investigation_id", sa.Uuid(), nullable=False, primary_key=True),
            sa.Column("incident_id", sa.Uuid(), nullable=False, index=True),
            sa.Column("final_state", sa.String(length=50), nullable=False, index=True),
            sa.Column("leading_hypothesis_id", sa.Uuid(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, index=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rca_narrative", sa.Text(), nullable=True),
            sa.Column("llm_provider", sa.String(length=50), nullable=True),
            sa.Column("llm_model", sa.String(length=100), nullable=True),
            sa.Column("is_fallback", sa.Boolean(), nullable=True),
            sa.Column("fallback_reason", sa.Text(), nullable=True),
        )
        op.create_index(
            "idx_investigations_incident_time",
            "investigations",
            ["incident_id", "started_at"],
        )
    else:
        existing_cols = {col["name"] for col in insp.get_columns("investigations")}
        with op.batch_alter_table("investigations") as batch_op:
            if "llm_provider" not in existing_cols:
                batch_op.add_column(
                    sa.Column("llm_provider", sa.String(length=50), nullable=True)
                )
            if "llm_model" not in existing_cols:
                batch_op.add_column(
                    sa.Column("llm_model", sa.String(length=100), nullable=True)
                )
            if "is_fallback" not in existing_cols:
                batch_op.add_column(
                    sa.Column("is_fallback", sa.Boolean(), nullable=True)
                )
            if "fallback_reason" not in existing_cols:
                batch_op.add_column(
                    sa.Column("fallback_reason", sa.Text(), nullable=True)
                )

        # Backfill any existing historical rows that have NULL in provider fields
        op.execute(
            "UPDATE investigations SET llm_provider = 'unknown' WHERE llm_provider IS NULL"
        )
        op.execute(
            "UPDATE investigations SET llm_model = 'Unknown (historical run)' WHERE llm_model IS NULL"
        )
        op.execute(
            "UPDATE investigations SET is_fallback = false WHERE is_fallback IS NULL"
        )

    # 2. Handle investigation_steps table
    if "investigation_steps" not in tables:
        op.create_table(
            "investigation_steps",
            sa.Column("id", sa.Uuid(), nullable=False, primary_key=True),
            sa.Column("investigation_id", sa.Uuid(), nullable=False, index=True),
            sa.Column("step_number", sa.Integer(), nullable=False),
            sa.Column("state", sa.String(length=50), nullable=False, index=True),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("details", sa.JSON(), nullable=False),
        )
        op.create_index(
            "idx_inv_steps_inv_num",
            "investigation_steps",
            ["investigation_id", "step_number"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = insp.get_table_names()

    if "investigations" in tables:
        existing_cols = {col["name"] for col in insp.get_columns("investigations")}
        with op.batch_alter_table("investigations") as batch_op:
            if "fallback_reason" in existing_cols:
                batch_op.drop_column("fallback_reason")
            if "is_fallback" in existing_cols:
                batch_op.drop_column("is_fallback")
            if "llm_model" in existing_cols:
                batch_op.drop_column("llm_model")
            if "llm_provider" in existing_cols:
                batch_op.drop_column("llm_provider")
