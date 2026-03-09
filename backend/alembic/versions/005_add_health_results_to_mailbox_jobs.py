"""Add health_results and last_health_check to mailbox_jobs

Revision ID: 005
Revises: 004
Create Date: 2026-03-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("mailbox_jobs", sa.Column("health_results", sa.JSON(), nullable=True))
    op.add_column("mailbox_jobs", sa.Column("last_health_check", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("mailbox_jobs", "last_health_check")
    op.drop_column("mailbox_jobs", "health_results")
