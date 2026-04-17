"""add company legal form

Revision ID: a71c2d3e4f5a
Revises: f83a1c2d4e5f
Create Date: 2026-04-17 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a71c2d3e4f5a"
down_revision: Union[str, Sequence[str], None] = "f83a1c2d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("legal_form", sa.String(length=32), nullable=True))
    op.execute(
        sa.text(
            """
            UPDATE companies
            SET legal_form = (
                SELECT CASE
                    WHEN lower(coalesce(company_public_profiles.subtitle, '') || ' ' || coalesce(company_public_profiles.about_text, '')) LIKE '%einzelunternehmen%' THEN 'einzelunternehmen'
                    WHEN lower(coalesce(company_public_profiles.subtitle, '') || ' ' || coalesce(company_public_profiles.about_text, '')) LIKE '%gmbh%' THEN 'gmbh'
                    WHEN lower(coalesce(company_public_profiles.subtitle, '') || ' ' || coalesce(company_public_profiles.about_text, '')) LIKE '%gbr%' THEN 'gbr'
                    WHEN lower(coalesce(company_public_profiles.subtitle, '') || ' ' || coalesce(company_public_profiles.about_text, '')) LIKE '%gewerbe%' THEN 'gewerbe'
                    WHEN lower(coalesce(company_public_profiles.subtitle, '') || ' ' || coalesce(company_public_profiles.about_text, '')) LIKE '%sonstiges%' THEN 'other'
                    WHEN lower(coalesce(company_public_profiles.subtitle, '') || ' ' || coalesce(company_public_profiles.about_text, '')) LIKE '%- ug%' THEN 'ug'
                    WHEN lower(coalesce(company_public_profiles.subtitle, '') || ' ' || coalesce(company_public_profiles.about_text, '')) LIKE '%(ug)%' THEN 'ug'
                    ELSE NULL
                END
                FROM company_public_profiles
                WHERE company_public_profiles.company_id = companies.id
                LIMIT 1
            )
            WHERE legal_form IS NULL
              AND EXISTS (
                SELECT 1
                FROM company_public_profiles
                WHERE company_public_profiles.company_id = companies.id
              )
            """
        )
    )


def downgrade() -> None:
    op.drop_column("companies", "legal_form")
