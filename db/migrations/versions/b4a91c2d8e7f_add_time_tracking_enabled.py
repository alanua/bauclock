"""Add time tracking participation flag

Revision ID: b4a91c2d8e7f
Revises: d4e7f8a9b1c2
Create Date: 2026-04-11 20:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b4a91c2d8e7f"
down_revision: Union[str, Sequence[str], None] = "d4e7f8a9b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _worker_columns() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns("workers")}


def upgrade() -> None:
    """Upgrade schema."""
    if "time_tracking_enabled" in _worker_columns():
        return

    with op.batch_alter_table("workers", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "time_tracking_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    if "time_tracking_enabled" not in _worker_columns():
        return

    with op.batch_alter_table("workers", schema=None) as batch_op:
        batch_op.drop_column("time_tracking_enabled")
