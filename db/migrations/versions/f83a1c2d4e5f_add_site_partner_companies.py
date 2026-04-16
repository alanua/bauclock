"""add site partner companies

Revision ID: f83a1c2d4e5f
Revises: b4a91c2d8e7f
Create Date: 2026-04-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f83a1c2d4e5f"
down_revision: Union[str, Sequence[str], None] = "b4a91c2d8e7f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "site_partner_companies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=32), server_default="subcontractor", nullable=False),
        sa.Column("invited_by_worker_id", sa.Integer(), nullable=True),
        sa.Column("accepted_by_worker_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["accepted_by_worker_id"], ["workers.id"]),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["invited_by_worker_id"], ["workers.id"]),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_id", "company_id", "role", name="uq_site_partner_company_role"),
    )
    op.create_index(op.f("ix_site_partner_companies_id"), "site_partner_companies", ["id"], unique=False)
    op.create_index(op.f("ix_site_partner_companies_site_id"), "site_partner_companies", ["site_id"], unique=False)
    op.create_index(op.f("ix_site_partner_companies_company_id"), "site_partner_companies", ["company_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_site_partner_companies_company_id"), table_name="site_partner_companies")
    op.drop_index(op.f("ix_site_partner_companies_site_id"), table_name="site_partner_companies")
    op.drop_index(op.f("ix_site_partner_companies_id"), table_name="site_partner_companies")
    op.drop_table("site_partner_companies")
