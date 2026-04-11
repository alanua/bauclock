"""add requests table

Revision ID: b2f6c9a10d4e
Revises: 9c4b7e1a2d3f
Create Date: 2026-04-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b2f6c9a10d4e"
down_revision: Union[str, Sequence[str], None] = "9c4b7e1a2d3f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


REQUEST_STATUS_OPEN = "open"


def upgrade() -> None:
    op.create_table(
        "requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("created_by_worker_id", sa.Integer(), nullable=True),
        sa.Column("target_worker_id", sa.Integer(), nullable=True),
        sa.Column("related_date", sa.Date(), nullable=True),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=REQUEST_STATUS_OPEN,
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["created_by_worker_id"], ["workers.id"]),
        sa.ForeignKeyConstraint(["target_worker_id"], ["workers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_requests_id"), "requests", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_requests_id"), table_name="requests")
    op.drop_table("requests")
