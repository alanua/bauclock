import asyncio
import importlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault(
    "ENCRYPTION_KEY",
    "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff",
)
os.environ.setdefault("HASH_PEPPER", "test_pepper")

from api.routers.public import (
    get_company_public_page,
    get_company_public_profile,
    get_company_public_profile_by_slug,
    get_default_company_public_page,
    get_site_public_page,
    get_site_public_profile,
)
from db.models import Base, Company, CompanyPublicProfile, Site


def run_db_test(test_coro):
    async def runner():
        with TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "public_company_profile.db"
            engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
            session_maker = async_sessionmaker(engine, expire_on_commit=False)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with session_maker() as session:
                await test_coro(session)

            await engine.dispose()

    asyncio.run(runner())


def response_html(response) -> str:
    if hasattr(response, "body"):
        return response.body.decode()
    return Path(response.path).read_text(encoding="utf-8")


def test_public_company_profile_endpoint_returns_active_sek_profile():
    async def run_test(session):
        company = Company(
            name="Generalbau S.E.K. GmbH",
            owner_telegram_id_enc="owner_enc",
            owner_telegram_id_hash="owner_hash",
        )
        session.add(company)
        await session.flush()
        session.add(
            CompanyPublicProfile(
                company_id=company.id,
                slug="sek",
                company_name="Generalbau S.E.K. GmbH",
                subtitle="Generalbau · Trockenbau · Putz & Maler · Dämmung",
                about_text="Wir bauen Zukunft - Stein auf Stein, Wand für Wand.",
                address="Am Industriegelände 3, 14772 Brandenburg an der Havel",
                email="kontakt@generalbau-sek.de",
                is_active=True,
            )
        )
        await session.commit()

        response = await get_company_public_profile(db=session)

        assert response == {
            "company_name": "Generalbau S.E.K. GmbH",
            "subtitle": "Generalbau · Trockenbau · Putz & Maler · Dämmung",
            "about_text": "Wir bauen Zukunft - Stein auf Stein, Wand für Wand.",
            "address": "Am Industriegelände 3, 14772 Brandenburg an der Havel",
            "email": "kontakt@generalbau-sek.de",
        }

    run_db_test(run_test)


def test_public_company_page_is_informational_only():
    async def run_test(session):
        company = Company(
            name="Generalbau S.E.K. GmbH",
            owner_telegram_id_enc="owner_enc",
            owner_telegram_id_hash="owner_hash",
        )
        session.add(company)
        await session.flush()
        session.add(
            CompanyPublicProfile(
                company_id=company.id,
                slug="sek",
                company_name="Generalbau S.E.K. GmbH",
                subtitle="Generalbau · Trockenbau · Putz & Maler · Daemmung",
                about_text="Wir bauen Zukunft - Stein auf Stein, Wand fuer Wand.",
                address="Am Industriegelaende 3, 14772 Brandenburg an der Havel",
                email="kontakt@generalbau-sek.de",
                is_active=True,
            )
        )
        await session.commit()

        response = await get_default_company_public_page(db=session)
        html = response_html(response)

        assert "Generalbau S.E.K. GmbH" in html or 'id="root"' in html
        assert "<button" not in html
        assert "<a " not in html
        assert "Dashboard" not in html
        assert "Zeiterfassung" not in html
        assert "Zugriff" not in html
        assert "Mitarbeiter" not in html

    run_db_test(run_test)


def test_public_site_page_is_informational_only():
    async def run_test(session):
        company = Company(
            name="Generalbau S.E.K. GmbH",
            owner_telegram_id_enc="owner_enc",
            owner_telegram_id_hash="owner_hash",
        )
        session.add(company)
        await session.flush()
        session.add(
            Site(
                company_id=company.id,
                name="Objekt Brandenburg",
                description="Zufahrt ueber Tor 2.",
                address="Am Industriegelaende 3",
                qr_token="site_public",
                is_active=True,
            )
        )
        await session.commit()

        profile = await get_site_public_profile("site_public", db=session)
        response = await get_site_public_page("site_public", db=session)
        html = response_html(response)

        assert profile == {
            "company_name": "Generalbau S.E.K. GmbH",
            "site_name": "Objekt Brandenburg",
            "address": "Am Industriegelaende 3",
            "note": "Zufahrt ueber Tor 2.",
        }
        assert "Objekt Brandenburg" in html or 'id="root"' in html
        assert "<button" not in html
        assert "<a " not in html
        assert "Dashboard" not in html
        assert "Zeiterfassung" not in html
        assert "Check-in" not in html
        assert "Zugriff" not in html
        assert "Mitarbeiter" not in html

    run_db_test(run_test)


def test_public_company_page_escapes_profile_content():
    async def run_test(session):
        company = Company(
            name="SEK",
            owner_telegram_id_enc="owner_enc",
            owner_telegram_id_hash="owner_hash",
        )
        session.add(company)
        await session.flush()
        session.add(
            CompanyPublicProfile(
                company_id=company.id,
                slug="sek",
                company_name="<SEK>",
                subtitle="<script>alert(1)</script>",
                about_text="Plain",
                address="Address",
                email=None,
                is_active=True,
            )
        )
        await session.commit()

        profile = await get_company_public_profile_by_slug("sek", db=session)
        response = await get_company_public_page("sek", db=session)
        html = response_html(response)

        assert profile["company_name"] == "<SEK>"
        assert "<script>" not in html

    run_db_test(run_test)


def test_dashboard_shell_contains_public_landing_fallback():
    html = Path("api/static/dashboard.html").read_text(encoding="utf-8")

    assert 'id="publicLandingState"' in html
    assert 'id="neutralTetrisState"' in html
    assert "neutral_tetris" in html
    assert "/api/public/company-profile" in html
    assert "loadPublicLanding" in html
    assert "bootstrapMiniApp" in html
    assert "await loadPublicLanding();" in html


def test_public_profile_migration_seeds_sek_profile():
    migration = importlib.import_module(
        "db.migrations.versions.d4e7f8a9b1c2_add_company_public_profiles"
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
        metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(
                sa.text("INSERT INTO companies (id, name) VALUES (1, 'Generalbau S.E.K. GmbH')")
            )
            original_op = migration.op
            try:
                migration.op = Operations(MigrationContext.configure(connection))
                migration.upgrade()
            finally:
                migration.op = original_op

            profile = connection.execute(
                sa.text(
                    """
                    SELECT company_id, slug, company_name, subtitle, address, email
                    FROM company_public_profiles
                    WHERE slug = 'sek'
                    """
                )
            ).mappings().one()

        assert profile["company_id"] == 1
        assert profile["company_name"] == "Generalbau S.E.K. GmbH"
        assert profile["subtitle"] == "Generalbau · Trockenbau · Putz & Maler · Dämmung"
        assert profile["address"] == "Am Industriegelände 3, 14772 Brandenburg an der Havel"
        assert profile["email"] == "kontakt@generalbau-sek.de"
    finally:
        engine.dispose()
