"""add worker employment model

Revision ID: e8f0a1b2c3d4
Revises: e2f4a6b8c9d1
Create Date: 2026-04-17 23:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e8f0a1b2c3d4"
down_revision: Union[str, Sequence[str], None] = "e2f4a6b8c9d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


EMPLOYEE_FULL_TIME = "employee_full_time"
MINIJOB = "minijob"
SELF_EMPLOYED = "self_employed"
EXTERNAL_ACCOUNTANT = "external_accountant"
ACTIVE = "active"
INACTIVE = "inactive"


def _worker_columns() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns("workers")}


def _add_column_if_missing(columns: set[str], column: sa.Column) -> None:
    if column.name in columns:
        return
    with op.batch_alter_table("workers", schema=None) as batch_op:
        batch_op.add_column(column)
    columns.add(column.name)


def upgrade() -> None:
    columns = _worker_columns()

    _add_column_if_missing(
        columns,
        sa.Column(
            "employment_type",
            sa.String(length=32),
            nullable=True,
            server_default=EMPLOYEE_FULL_TIME,
        ),
    )
    _add_column_if_missing(
        columns,
        sa.Column(
            "employment_status",
            sa.String(length=32),
            nullable=True,
            server_default=ACTIVE,
        ),
    )
    _add_column_if_missing(
        columns,
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    _add_column_if_missing(
        columns,
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
    )
    _add_column_if_missing(
        columns,
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    _add_column_if_missing(
        columns,
        sa.Column("termination_reason", sa.String(), nullable=True),
    )

    op.execute(
        sa.text(
            """
            UPDATE workers
            SET employment_type = CASE
                WHEN access_role = 'accountant' AND time_tracking_enabled IS FALSE THEN :external_accountant
                WHEN worker_type = 'MINIJOB' THEN :minijob
                WHEN worker_type IN ('GEWERBE', 'SUBUNTERNEHMER') THEN :self_employed
                ELSE :employee_full_time
            END
            WHERE employment_type IS NULL OR employment_type = '' OR employment_type = :employee_full_time
            """
        ).bindparams(
            external_accountant=EXTERNAL_ACCOUNTANT,
            minijob=MINIJOB,
            self_employed=SELF_EMPLOYED,
            employee_full_time=EMPLOYEE_FULL_TIME,
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE workers
            SET employment_status = CASE
                WHEN is_active IS FALSE THEN :inactive
                ELSE :active
            END
            WHERE employment_status IS NULL OR employment_status = '' OR employment_status = :active
            """
        ).bindparams(inactive=INACTIVE, active=ACTIVE)
    )
    op.execute(
        sa.text(
            """
            UPDATE workers
            SET started_at = CURRENT_TIMESTAMP
            WHERE started_at IS NULL
            """
        )
    )

    with op.batch_alter_table("workers", schema=None) as batch_op:
        batch_op.alter_column(
            "employment_type",
            existing_type=sa.String(length=32),
            nullable=False,
            server_default=EMPLOYEE_FULL_TIME,
        )
        batch_op.alter_column(
            "employment_status",
            existing_type=sa.String(length=32),
            nullable=False,
            server_default=ACTIVE,
        )


def downgrade() -> None:
    columns = _worker_columns()
    for column_name in (
        "termination_reason",
        "ended_at",
        "trial_ends_at",
        "started_at",
        "employment_status",
        "employment_type",
    ):
        if column_name in columns:
            with op.batch_alter_table("workers", schema=None) as batch_op:
                batch_op.drop_column(column_name)
