"""normalize company legal form other value

Revision ID: e2f4a6b8c9d1
Revises: a71c2d3e4f5a
Create Date: 2026-04-17 21:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e2f4a6b8c9d1"
down_revision: Union[str, Sequence[str], None] = "a71c2d3e4f5a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE companies
            SET legal_form = 'other'
            WHERE lower(coalesce(legal_form, '')) IN ('sonstiges', 'sonstige')
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE companies
            SET legal_form = 'sonstiges'
            WHERE legal_form = 'other'
            """
        )
    )
