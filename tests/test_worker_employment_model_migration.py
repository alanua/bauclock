import importlib

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_worker_employment_model_migration_backfills_memberships():
    migration = importlib.import_module(
        "db.migrations.versions.e8f0a1b2c3d4_add_worker_employment_model"
    )
    engine = sa.create_engine("sqlite:///:memory:")
    try:
        metadata = sa.MetaData()
        sa.Table(
            "workers",
            metadata,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("worker_type", sa.String(), nullable=False),
            sa.Column("access_role", sa.String(length=32), nullable=False),
            sa.Column("time_tracking_enabled", sa.Boolean(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
        )
        metadata.create_all(engine)

        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO workers
                        (id, worker_type, access_role, time_tracking_enabled, is_active)
                    VALUES
                        (1, 'FESTANGESTELLT', 'worker', 1, 1),
                        (2, 'MINIJOB', 'worker', 1, 1),
                        (3, 'GEWERBE', 'worker', 1, 1),
                        (4, 'FESTANGESTELLT', 'accountant', 0, 1),
                        (5, 'FESTANGESTELLT', 'worker', 1, 0)
                    """
                )
            )

            original_op = migration.op
            try:
                migration.op = Operations(MigrationContext.configure(connection))
                migration.upgrade()
            finally:
                migration.op = original_op

            rows = {
                row.id: row
                for row in connection.execute(
                    sa.text(
                        """
                        SELECT
                            id,
                            employment_type,
                            employment_status,
                            started_at,
                            trial_ends_at,
                            ended_at,
                            termination_reason
                        FROM workers
                        ORDER BY id
                        """
                    )
                ).all()
            }

        assert rows[1].employment_type == "employee_full_time"
        assert rows[2].employment_type == "minijob"
        assert rows[3].employment_type == "self_employed"
        assert rows[4].employment_type == "external_accountant"
        assert rows[5].employment_status == "inactive"
        assert all(row.started_at is not None for row in rows.values())
        assert all(row.trial_ends_at is None for row in rows.values())
        assert all(row.ended_at is None for row in rows.values())
        assert all(row.termination_reason is None for row in rows.values())
    finally:
        engine.dispose()
