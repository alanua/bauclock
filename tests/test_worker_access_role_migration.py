import importlib

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def run_upgrade(connection) -> None:
    migration = importlib.import_module(
        "db.migrations.versions.9c4b7e1a2d3f_add_worker_access_role"
    )
    original_op = migration.op
    try:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
    finally:
        migration.op = original_op


def create_legacy_schema(connection) -> None:
    metadata = sa.MetaData()
    sa.Table(
        "companies",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("owner_telegram_id_hash", sa.String(), nullable=False),
    )
    sa.Table(
        "workers",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("telegram_id_hash", sa.String(), nullable=False),
        sa.Column("worker_type", sa.String(), nullable=False),
        sa.Column("can_view_dashboard", sa.Boolean(), nullable=True),
    )
    metadata.create_all(connection)


def test_worker_access_role_migration_backfills_legacy_roles():
    engine = sa.create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            create_legacy_schema(connection)
            connection.execute(
                sa.text(
                    """
                    INSERT INTO companies (id, name, owner_telegram_id_hash)
                    VALUES (1, 'SEK', 'owner_hash')
                    """
                )
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO workers (
                        id,
                        company_id,
                        telegram_id_hash,
                        worker_type,
                        can_view_dashboard
                    )
                    VALUES
                        (1, 1, 'owner_hash', 'FESTANGESTELLT', 0),
                        (2, 1, 'subcontractor_hash', 'SUBUNTERNEHMER', 0),
                        (3, 1, 'manager_hash', 'FESTANGESTELLT', 1),
                        (4, 1, 'worker_hash', 'FESTANGESTELLT', 0)
                    """
                )
            )

            run_upgrade(connection)

            roles = dict(
                connection.execute(
                    sa.text("SELECT id, access_role FROM workers ORDER BY id")
                ).all()
            )

        assert roles == {
            1: "company_owner",
            2: "subcontractor",
            3: "objektmanager",
            4: "worker",
        }
    finally:
        engine.dispose()
