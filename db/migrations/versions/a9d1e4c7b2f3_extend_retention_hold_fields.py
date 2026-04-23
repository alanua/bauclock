"""extend retention hold fields

Revision ID: a9d1e4c7b2f3
Revises: f1c4e7a9b2d3
Create Date: 2026-04-21 21:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a9d1e4c7b2f3"
down_revision: Union[str, Sequence[str], None] = "f1c4e7a9b2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def _tables() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def upgrade() -> None:
    if "retention_holds" not in _tables():
        return

    retention_hold_columns = _columns("retention_holds")
    with op.batch_alter_table("retention_holds", schema=None) as batch_op:
        if "hold_reason" not in retention_hold_columns:
            batch_op.add_column(sa.Column("hold_reason", sa.String(length=255), nullable=True))
        if "held_by_worker_id" not in retention_hold_columns:
            batch_op.add_column(sa.Column("held_by_worker_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                "fk_retention_holds_held_by_worker_id_workers",
                "workers",
                ["held_by_worker_id"],
                ["id"],
            )
        if "hold_until" not in retention_hold_columns:
            batch_op.add_column(sa.Column("hold_until", sa.DateTime(timezone=True), nullable=True))

    current_columns = _columns("retention_holds")
    if "hold_reason" in current_columns and "reason" in current_columns:
        op.execute(
            sa.text(
                "UPDATE retention_holds "
                "SET hold_reason = reason "
                "WHERE hold_reason IS NULL AND reason IS NOT NULL"
            )
        )
    if "hold_until" in current_columns and "expires_at" in current_columns:
        op.execute(
            sa.text(
                "UPDATE retention_holds "
                "SET hold_until = expires_at "
                "WHERE hold_until IS NULL AND expires_at IS NOT NULL"
            )
        )


def downgrade() -> None:
    if "retention_holds" not in _tables():
        return

    retention_hold_columns = _columns("retention_holds")
    with op.batch_alter_table("retention_holds", schema=None) as batch_op:
        if "hold_until" in retention_hold_columns:
            batch_op.drop_column("hold_until")
        if "held_by_worker_id" in retention_hold_columns:
            batch_op.drop_constraint("fk_retention_holds_held_by_worker_id_workers", type_="foreignkey")
            batch_op.drop_column("held_by_worker_id")
        if "hold_reason" in retention_hold_columns:
            batch_op.drop_column("hold_reason")
