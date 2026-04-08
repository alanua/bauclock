"""repair_schema_consistency

Revision ID: 7d4b2f6c9a10
Revises: 4f3316c4dc5b
Create Date: 2026-04-08 21:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7d4b2f6c9a10"
down_revision: Union[str, Sequence[str], None] = "4f3316c4dc5b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _get_columns(table_name: str) -> dict[str, dict[str, object]]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"]: column for column in inspector.get_columns(table_name)}


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    """Upgrade schema."""
    if not _has_table("daily_summaries"):
        op.create_table(
            "daily_summaries",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("worker_id", sa.Integer(), nullable=False),
            sa.Column("date", sa.Date(), nullable=False),
            sa.Column("total_minutes", sa.Integer(), nullable=True),
            sa.Column("break_minutes", sa.Integer(), nullable=True),
            sa.Column("contract_minutes", sa.Integer(), nullable=True),
            sa.Column("overtime_minutes", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(["worker_id"], ["workers.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_daily_summaries_id"),
            "daily_summaries",
            ["id"],
            unique=False,
        )
    else:
        daily_summary_columns = _get_columns("daily_summaries")
        with op.batch_alter_table("daily_summaries", schema=None) as batch_op:
            if "worked_minutes" in daily_summary_columns and "total_minutes" not in daily_summary_columns:
                batch_op.alter_column(
                    "worked_minutes",
                    existing_type=daily_summary_columns["worked_minutes"]["type"],
                    new_column_name="total_minutes",
                )
            if "pause_minutes" in daily_summary_columns and "break_minutes" not in daily_summary_columns:
                batch_op.alter_column(
                    "pause_minutes",
                    existing_type=daily_summary_columns["pause_minutes"]["type"],
                    new_column_name="break_minutes",
                )
            if "total_minutes" not in daily_summary_columns and "worked_minutes" not in daily_summary_columns:
                batch_op.add_column(sa.Column("total_minutes", sa.Integer(), nullable=True))
            if "break_minutes" not in daily_summary_columns and "pause_minutes" not in daily_summary_columns:
                batch_op.add_column(sa.Column("break_minutes", sa.Integer(), nullable=True))
            if "contract_minutes" not in daily_summary_columns:
                batch_op.add_column(sa.Column("contract_minutes", sa.Integer(), nullable=True))
            if "overtime_minutes" not in daily_summary_columns:
                batch_op.add_column(sa.Column("overtime_minutes", sa.Integer(), nullable=True))
            if "created_at" in daily_summary_columns:
                batch_op.drop_column("created_at")
            date_type = daily_summary_columns.get("date", {}).get("type")
            if isinstance(date_type, sa.DateTime):
                batch_op.alter_column(
                    "date",
                    existing_type=date_type,
                    type_=sa.Date(),
                )

    if not _has_table("monthly_adjustments"):
        op.create_table(
            "monthly_adjustments",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("worker_id", sa.Integer(), nullable=False),
            sa.Column("month", sa.Date(), nullable=False),
            sa.Column("adjustment_minutes", sa.Integer(), nullable=False),
            sa.Column("reason", sa.String(length=255), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=True,
            ),
            sa.ForeignKeyConstraint(["created_by"], ["workers.id"]),
            sa.ForeignKeyConstraint(["worker_id"], ["workers.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_monthly_adjustments_id"),
            "monthly_adjustments",
            ["id"],
            unique=False,
        )
    else:
        monthly_adjustment_columns = _get_columns("monthly_adjustments")
        month_type = monthly_adjustment_columns.get("month", {}).get("type")
        if isinstance(month_type, sa.DateTime):
            with op.batch_alter_table("monthly_adjustments", schema=None) as batch_op:
                batch_op.alter_column(
                    "month",
                    existing_type=month_type,
                    type_=sa.Date(),
                )

    payment_columns = _get_columns("payments")
    if "payment_type" not in payment_columns:
        with op.batch_alter_table("payments", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "payment_type",
                    sa.String(length=20),
                    nullable=True,
                    server_default="OVERTIME",
                )
            )

    op.execute(sa.text("UPDATE payments SET payment_type = 'OVERTIME' WHERE payment_type IS NULL"))
    with op.batch_alter_table("payments", schema=None) as batch_op:
        batch_op.alter_column(
            "payment_type",
            existing_type=sa.String(length=20),
            nullable=False,
            server_default="OVERTIME",
        )

    worker_columns = _get_columns("workers")
    if "contract_hours_week" not in worker_columns:
        with op.batch_alter_table("workers", schema=None) as batch_op:
            batch_op.add_column(sa.Column("contract_hours_week", sa.Integer(), nullable=True))
    else:
        contract_hours_week_type = worker_columns["contract_hours_week"]["type"]
        if isinstance(contract_hours_week_type, sa.Float):
            op.execute(sa.text("UPDATE workers SET contract_hours_week = ROUND(contract_hours_week) WHERE contract_hours_week IS NOT NULL"))
            with op.batch_alter_table("workers", schema=None) as batch_op:
                batch_op.alter_column(
                    "contract_hours_week",
                    existing_type=contract_hours_week_type,
                    type_=sa.Integer(),
                )

    worker_columns = _get_columns("workers")
    if "contract_hours_month" in worker_columns:
        with op.batch_alter_table("workers", schema=None) as batch_op:
            batch_op.drop_column("contract_hours_month")


def downgrade() -> None:
    """Downgrade is intentionally unsupported for this repair migration."""
    raise NotImplementedError(
        "Downgrade is intentionally unsupported for repair_schema_consistency"
    )
