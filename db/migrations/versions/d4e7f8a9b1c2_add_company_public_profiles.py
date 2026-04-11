"""add company public profiles

Revision ID: d4e7f8a9b1c2
Revises: c3a12f4e5b6d
Create Date: 2026-04-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e7f8a9b1c2"
down_revision: Union[str, Sequence[str], None] = "c3a12f4e5b6d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEK_SLUG = "sek"
SEK_COMPANY_NAME = "Generalbau S.E.K. GmbH"
SEK_SUBTITLE = "Generalbau · Trockenbau · Putz & Maler · Dämmung"
SEK_ABOUT_TEXT = (
    "Wir bauen Zukunft - Stein auf Stein, Wand für Wand. "
    "Seit 2019 realisiert Generalbau S.E.K. Bauprojekte mit Präzision, "
    "Termintreue und Verbundenheit zum Standort Brandenburg an der Havel."
)
SEK_ADDRESS = "Am Industriegelände 3, 14772 Brandenburg an der Havel"
SEK_EMAIL = "kontakt@generalbau-sek.de"


def upgrade() -> None:
    op.create_table(
        "company_public_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=True),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("company_name", sa.String(), nullable=False),
        sa.Column("subtitle", sa.String(), nullable=False),
        sa.Column("about_text", sa.Text(), nullable=False),
        sa.Column("address", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
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
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index(op.f("ix_company_public_profiles_id"), "company_public_profiles", ["id"], unique=False)
    op.create_index(op.f("ix_company_public_profiles_slug"), "company_public_profiles", ["slug"], unique=False)

    op.execute(
        sa.text(
            """
            INSERT INTO company_public_profiles (
                company_id,
                slug,
                company_name,
                subtitle,
                about_text,
                address,
                email,
                is_active
            )
            SELECT
                (
                    SELECT id
                    FROM companies
                    WHERE lower(name) LIKE '%sek%'
                       OR lower(name) LIKE '%s.e.k%'
                    ORDER BY id
                    LIMIT 1
                ),
                :slug,
                :company_name,
                :subtitle,
                :about_text,
                :address,
                :email,
                TRUE
            WHERE NOT EXISTS (
                SELECT 1
                FROM company_public_profiles
                WHERE slug = :slug
            )
            """
        ).bindparams(
            slug=SEK_SLUG,
            company_name=SEK_COMPANY_NAME,
            subtitle=SEK_SUBTITLE,
            about_text=SEK_ABOUT_TEXT,
            address=SEK_ADDRESS,
            email=SEK_EMAIL,
        )
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_company_public_profiles_slug"), table_name="company_public_profiles")
    op.drop_index(op.f("ix_company_public_profiles_id"), table_name="company_public_profiles")
    op.drop_table("company_public_profiles")
