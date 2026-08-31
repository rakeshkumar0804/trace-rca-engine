"""Update vector embedding dimension to 384 for FastEmbed BAAI/bge-small-en-v1.5

Revision ID: 0002_vector_dim_384
Revises: 0001_initial_schema
Create Date: 2026-08-30 19:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
from pgvector.sqlalchemy import Vector
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0002_vector_dim_384"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.alter_column(
            "logs",
            "embedding",
            type_=Vector(384),
            existing_type=Vector(128),
            existing_nullable=True,
        )
        op.alter_column(
            "commits",
            "embedding",
            type_=Vector(384),
            existing_type=Vector(128),
            existing_nullable=True,
        )
        op.alter_column(
            "alerts",
            "embedding",
            type_=Vector(384),
            existing_type=Vector(128),
            existing_nullable=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.alter_column(
            "logs",
            "embedding",
            type_=Vector(128),
            existing_type=Vector(384),
            existing_nullable=True,
        )
        op.alter_column(
            "commits",
            "embedding",
            type_=Vector(128),
            existing_type=Vector(384),
            existing_nullable=True,
        )
        op.alter_column(
            "alerts",
            "embedding",
            type_=Vector(128),
            existing_type=Vector(384),
            existing_nullable=True,
        )
