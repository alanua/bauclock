import importlib

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_company_legal_form_migration_backfills_from_public_profile():
    migration = importlib.import_module(
        "db.migrations.versions.a71c2d3e4f5a_add_company_legal_form"
    )
    engine = sa.create_engine("sqlite:///:memory:")
    try:
        metadata = sa.MetaData()
        sa.Table(
            "companies",
            metadata,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(), nullable=False),
        )
        sa.Table(
            "company_public_profiles",
            metadata,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer()),
            sa.Column("subtitle", sa.String(), nullable=False),
            sa.Column("about_text", sa.Text(), nullable=False),
        )
        metadata.create_all(engine)

        with engine.begin() as connection:
            connection.execute(
                sa.text("INSERT INTO companies (id, name) VALUES (1, 'Alpha Bau')")
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO company_public_profiles (id, company_id, subtitle, about_text)
                    VALUES (1, 1, 'Bauunternehmen - GmbH', 'Alpha Bau (GmbH) nutzt BauClock')
                    """
                )
            )

            original_op = migration.op
            try:
                migration.op = Operations(MigrationContext.configure(connection))
                migration.upgrade()
            finally:
                migration.op = original_op

            legal_form = connection.execute(
                sa.text("SELECT legal_form FROM companies WHERE id = 1")
            ).scalar_one()

        assert legal_form == "gmbh"
    finally:
        engine.dispose()


def test_company_legal_form_migration_uses_canonical_other_value():
    migration = importlib.import_module(
        "db.migrations.versions.a71c2d3e4f5a_add_company_legal_form"
    )
    engine = sa.create_engine("sqlite:///:memory:")
    try:
        metadata = sa.MetaData()
        sa.Table(
            "companies",
            metadata,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(), nullable=False),
        )
        sa.Table(
            "company_public_profiles",
            metadata,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer()),
            sa.Column("subtitle", sa.String(), nullable=False),
            sa.Column("about_text", sa.Text(), nullable=False),
        )
        metadata.create_all(engine)

        with engine.begin() as connection:
            connection.execute(
                sa.text("INSERT INTO companies (id, name) VALUES (1, 'Andere Bau')")
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO company_public_profiles (id, company_id, subtitle, about_text)
                    VALUES (1, 1, 'Bauunternehmen - Sonstiges', 'Andere Bau (Sonstiges)')
                    """
                )
            )

            original_op = migration.op
            try:
                migration.op = Operations(MigrationContext.configure(connection))
                migration.upgrade()
            finally:
                migration.op = original_op

            legal_form = connection.execute(
                sa.text("SELECT legal_form FROM companies WHERE id = 1")
            ).scalar_one()

        assert legal_form == "other"
    finally:
        engine.dispose()


def test_company_legal_form_normalization_migration_updates_legacy_sonstiges():
    migration = importlib.import_module(
        "db.migrations.versions.e2f4a6b8c9d1_normalize_company_legal_form_other"
    )
    engine = sa.create_engine("sqlite:///:memory:")
    try:
        metadata = sa.MetaData()
        sa.Table(
            "companies",
            metadata,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("legal_form", sa.String(length=32), nullable=True),
        )
        metadata.create_all(engine)

        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    "INSERT INTO companies (id, legal_form) VALUES "
                    "(1, 'sonstiges'), (2, 'gmbh')"
                )
            )

            original_op = migration.op
            try:
                migration.op = Operations(MigrationContext.configure(connection))
                migration.upgrade()
            finally:
                migration.op = original_op

            rows = dict(connection.execute(sa.text("SELECT id, legal_form FROM companies")).all())

        assert rows == {1: "other", 2: "gmbh"}
    finally:
        engine.dispose()
