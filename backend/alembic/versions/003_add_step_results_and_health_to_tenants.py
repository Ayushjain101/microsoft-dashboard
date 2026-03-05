"""Add step_results, health_results, last_health_check to tenants

Revision ID: 003
Revises: 002
Create Date: 2026-03-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("step_results", sa.JSON(), nullable=True))
    op.add_column("tenants", sa.Column("health_results", sa.JSON(), nullable=True))
    op.add_column("tenants", sa.Column("last_health_check", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("tenants", "last_health_check")
    op.drop_column("tenants", "health_results")
    op.drop_column("tenants", "step_results")
