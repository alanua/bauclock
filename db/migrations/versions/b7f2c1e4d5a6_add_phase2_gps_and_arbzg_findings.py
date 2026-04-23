"""add phase 2 gps policy flags and arbzg findings

Revision ID: b7f2c1e4d5a6
Revises: a9d1e4c7b2f3
Create Date: 2026-04-23 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7f2c1e4d5a6"
down_revision: Union[str, Sequence[str], None] = "a9d1e4c7b2f3"
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


def _create_table_if_missing(
    table_name: str,
    *columns,
    indexes: list[tuple[str, list[str], bool]] | None = None,
) -> None:
    if table_name in _tables():
        return
    op.create_table(table_name, *columns)
    for index_name, index_columns, unique in indexes or []:
        op.create_index(index_name, table_name, index_columns, unique=unique)


def upgrade() -> None:
    company_columns = _columns("companies")
    with op.batch_alter_table("companies", schema=None) as batch_op:
        if "gps_site_presence_required" not in company_columns:
            batch_op.add_column(sa.Column("gps_site_presence_required", sa.Boolean(), nullable=True))

    site_columns = _columns("sites")
    with op.batch_alter_table("sites", schema=None) as batch_op:
        if "gps_site_presence_required" not in site_columns:
            batch_op.add_column(sa.Column("gps_site_presence_required", sa.Boolean(), nullable=True))

    worker_columns = _columns("workers")
    with op.batch_alter_table("workers", schema=None) as batch_op:
        if "gps_site_presence_required_override" not in worker_columns:
            batch_op.add_column(sa.Column("gps_site_presence_required_override", sa.Boolean(), nullable=True))

    _create_table_if_missing(
        "arbzg_findings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.Integer(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("finding_code", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("state_reason", sa.String(length=255), nullable=True),
        sa.Column("created_by_worker_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_worker_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["worker_id"], ["workers.id"]),
        sa.ForeignKeyConstraint(["created_by_worker_id"], ["workers.id"]),
        sa.ForeignKeyConstraint(["updated_by_worker_id"], ["workers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id",
            "worker_id",
            "target_date",
            "finding_code",
            name="uq_arbzg_findings_company_worker_date_code",
        ),
        indexes=[
            (op.f("ix_arbzg_findings_id"), ["id"], False),
            (op.f("ix_arbzg_findings_company_id"), ["company_id"], False),
            (op.f("ix_arbzg_findings_worker_id"), ["worker_id"], False),
            (op.f("ix_arbzg_findings_target_date"), ["target_date"], False),
            (op.f("ix_arbzg_findings_finding_code"), ["finding_code"], False),
        ],
    )


def downgrade() -> None:
    if "arbzg_findings" in _tables():
        op.drop_index(op.f("ix_arbzg_findings_finding_code"), table_name="arbzg_findings")
        op.drop_index(op.f("ix_arbzg_findings_target_date"), table_name="arbzg_findings")
        op.drop_index(op.f("ix_arbzg_findings_worker_id"), table_name="arbzg_findings")
        op.drop_index(op.f("ix_arbzg_findings_company_id"), table_name="arbzg_findings")
        op.drop_index(op.f("ix_arbzg_findings_id"), table_name="arbzg_findings")
        op.drop_table("arbzg_findings")

    worker_columns = _columns("workers")
    with op.batch_alter_table("workers", schema=None) as batch_op:
        if "gps_site_presence_required_override" in worker_columns:
            batch_op.drop_column("gps_site_presence_required_override")

    site_columns = _columns("sites")
    with op.batch_alter_table("sites", schema=None) as batch_op:
        if "gps_site_presence_required" in site_columns:
            batch_op.drop_column("gps_site_presence_required")

    company_columns = _columns("companies")
    with op.batch_alter_table("companies", schema=None) as batch_op:
        if "gps_site_presence_required" in company_columns:
            batch_op.drop_column("gps_site_presence_required")
