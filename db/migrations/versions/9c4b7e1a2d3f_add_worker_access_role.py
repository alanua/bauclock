"""add worker access role

Revision ID: 9c4b7e1a2d3f
Revises: 7d4b2f6c9a10
Create Date: 2026-04-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9c4b7e1a2d3f"
down_revision: Union[str, Sequence[str], None] = "7d4b2f6c9a10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ACCESS_ROLE_COLUMN = "access_role"
COMPANY_OWNER = "company_owner"
OBJEKTMANAGER = "objektmanager"
WORKER = "worker"
SUBCONTRACTOR = "subcontractor"


def _get_columns(table_name: str) -> dict[str, dict[str, object]]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"]: column for column in inspector.get_columns(table_name)}


def _backfill_access_roles(where_clause: str = "") -> None:
    op.execute(
        sa.text(
            f"""
            UPDATE workers
            SET access_role = CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM companies
                    WHERE companies.id = workers.company_id
                    AND companies.owner_telegram_id_hash = workers.telegram_id_hash
                ) THEN :company_owner
                WHEN worker_type = 'SUBUNTERNEHMER' THEN :subcontractor
                WHEN can_view_dashboard IS TRUE THEN :objektmanager
                ELSE :worker
            END
            {where_clause}
            """
        ).bindparams(
            company_owner=COMPANY_OWNER,
            subcontractor=SUBCONTRACTOR,
            objektmanager=OBJEKTMANAGER,
            worker=WORKER,
        )
    )


def upgrade() -> None:
    worker_columns = _get_columns("workers")
    column_added = ACCESS_ROLE_COLUMN not in worker_columns

    if column_added:
        with op.batch_alter_table("workers", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    ACCESS_ROLE_COLUMN,
                    sa.String(length=32),
                    nullable=True,
                    server_default=WORKER,
                )
            )
        _backfill_access_roles()
    else:
        _backfill_access_roles(f"WHERE {ACCESS_ROLE_COLUMN} IS NULL")

    with op.batch_alter_table("workers", schema=None) as batch_op:
        batch_op.alter_column(
            ACCESS_ROLE_COLUMN,
            existing_type=sa.String(length=32),
            nullable=False,
            server_default=WORKER,
        )


def downgrade() -> None:
    worker_columns = _get_columns("workers")
    if ACCESS_ROLE_COLUMN in worker_columns:
        with op.batch_alter_table("workers", schema=None) as batch_op:
            batch_op.drop_column(ACCESS_ROLE_COLUMN)
