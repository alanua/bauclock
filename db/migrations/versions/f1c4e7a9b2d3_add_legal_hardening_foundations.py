"""add legal hardening foundations

Revision ID: f1c4e7a9b2d3
Revises: e8f0a1b2c3d4
Create Date: 2026-04-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1c4e7a9b2d3"
down_revision: Union[str, Sequence[str], None] = "e8f0a1b2c3d4"
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


def _create_table_if_missing(table_name: str, *columns, indexes: list[tuple[str, list[str], bool]] | None = None) -> None:
    if table_name in _tables():
        return
    op.create_table(table_name, *columns)
    for index_name, index_columns, unique in indexes or []:
        op.create_index(index_name, table_name, index_columns, unique=unique)


def upgrade() -> None:
    time_event_columns = _columns("time_events")
    with op.batch_alter_table("time_events", schema=None) as batch_op:
        if "is_manual" not in time_event_columns:
            batch_op.add_column(sa.Column("is_manual", sa.Boolean(), nullable=False, server_default="0"))
        if "corrected_by_worker_id" not in time_event_columns:
            batch_op.add_column(sa.Column("corrected_by_worker_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                "fk_time_events_corrected_by_worker_id_workers",
                "workers",
                ["corrected_by_worker_id"],
                ["id"],
            )
        if "correction_reason" not in time_event_columns:
            batch_op.add_column(sa.Column("correction_reason", sa.String(length=255), nullable=True))
        if "corrected_at" not in time_event_columns:
            batch_op.add_column(sa.Column("corrected_at", sa.DateTime(timezone=True), nullable=True))

    _create_table_if_missing(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("old_value", sa.JSON(), nullable=True),
        sa.Column("new_value", sa.JSON(), nullable=True),
        sa.Column("performed_by_worker_id", sa.Integer(), nullable=True),
        sa.Column("company_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["performed_by_worker_id"], ["workers.id"]),
        sa.PrimaryKeyConstraint("id"),
        indexes=[
            (op.f("ix_audit_logs_id"), ["id"], False),
            (op.f("ix_audit_logs_entity_type"), ["entity_type"], False),
            (op.f("ix_audit_logs_entity_id"), ["entity_id"], False),
            (op.f("ix_audit_logs_company_id"), ["company_id"], False),
        ],
    )

    _create_table_if_missing(
        "legal_acceptance_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=True),
        sa.Column("document_type", sa.String(length=64), nullable=False),
        sa.Column("document_version", sa.String(length=32), nullable=False),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.PrimaryKeyConstraint("id"),
        indexes=[
            (op.f("ix_legal_acceptance_logs_id"), ["id"], False),
            (op.f("ix_legal_acceptance_logs_actor_type"), ["actor_type"], False),
            (op.f("ix_legal_acceptance_logs_actor_id"), ["actor_id"], False),
            (op.f("ix_legal_acceptance_logs_company_id"), ["company_id"], False),
            (op.f("ix_legal_acceptance_logs_document_type"), ["document_type"], False),
        ],
    )

    _create_table_if_missing(
        "retention_holds",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("hold_type", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("company_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.PrimaryKeyConstraint("id"),
        indexes=[
            (op.f("ix_retention_holds_id"), ["id"], False),
            (op.f("ix_retention_holds_entity_type"), ["entity_type"], False),
            (op.f("ix_retention_holds_entity_id"), ["entity_id"], False),
            (op.f("ix_retention_holds_company_id"), ["company_id"], False),
        ],
    )


def downgrade() -> None:
    if "retention_holds" in _tables():
        op.drop_index(op.f("ix_retention_holds_company_id"), table_name="retention_holds")
        op.drop_index(op.f("ix_retention_holds_entity_id"), table_name="retention_holds")
        op.drop_index(op.f("ix_retention_holds_entity_type"), table_name="retention_holds")
        op.drop_index(op.f("ix_retention_holds_id"), table_name="retention_holds")
        op.drop_table("retention_holds")

    if "legal_acceptance_logs" in _tables():
        op.drop_index(op.f("ix_legal_acceptance_logs_document_type"), table_name="legal_acceptance_logs")
        op.drop_index(op.f("ix_legal_acceptance_logs_company_id"), table_name="legal_acceptance_logs")
        op.drop_index(op.f("ix_legal_acceptance_logs_actor_id"), table_name="legal_acceptance_logs")
        op.drop_index(op.f("ix_legal_acceptance_logs_actor_type"), table_name="legal_acceptance_logs")
        op.drop_index(op.f("ix_legal_acceptance_logs_id"), table_name="legal_acceptance_logs")
        op.drop_table("legal_acceptance_logs")

    if "audit_logs" in _tables():
        op.drop_index(op.f("ix_audit_logs_company_id"), table_name="audit_logs")
        op.drop_index(op.f("ix_audit_logs_entity_id"), table_name="audit_logs")
        op.drop_index(op.f("ix_audit_logs_entity_type"), table_name="audit_logs")
        op.drop_index(op.f("ix_audit_logs_id"), table_name="audit_logs")
        op.drop_table("audit_logs")

    time_event_columns = _columns("time_events")
    with op.batch_alter_table("time_events", schema=None) as batch_op:
        if "corrected_at" in time_event_columns:
            batch_op.drop_column("corrected_at")
        if "correction_reason" in time_event_columns:
            batch_op.drop_column("correction_reason")
        if "corrected_by_worker_id" in time_event_columns:
            batch_op.drop_constraint("fk_time_events_corrected_by_worker_id_workers", type_="foreignkey")
            batch_op.drop_column("corrected_by_worker_id")
        if "is_manual" in time_event_columns:
            batch_op.drop_column("is_manual")
