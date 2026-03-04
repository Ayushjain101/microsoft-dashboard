"""Add step_results JSON column to mailbox_jobs

Revision ID: 002
Revises: 001
Create Date: 2026-03-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "mailbox_jobs",
        sa.Column("step_results", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mailbox_jobs", "step_results")
