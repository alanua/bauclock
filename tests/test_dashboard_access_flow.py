import asyncio
import hashlib
import hmac
import json
import os
import sys
import time
from urllib.parse import urlencode
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault(
    "ENCRYPTION_KEY",
    "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff",
)
os.environ.setdefault("HASH_PEPPER", "test_pepper")


def install_import_stubs() -> None:
    if "aiogram" not in sys.modules:
        aiogram_module = ModuleType("aiogram")

        class Router:
            def message(self, *args, **kwargs):
                def decorator(func):
                    return func

                return decorator

        aiogram_module.Router = Router
        sys.modules["aiogram"] = aiogram_module

    if "aiogram.filters" not in sys.modules:
        filters_module = ModuleType("aiogram.filters")

        class Command:
            def __init__(self, *args, **kwargs):
                pass

        filters_module.Command = Command
        sys.modules["aiogram.filters"] = filters_module

    if "aiogram.types" not in sys.modules:
        types_module = ModuleType("aiogram.types")
        types_module.Message = type("Message", (), {})
        sys.modules["aiogram.types"] = types_module

    if "api.redis_client" not in sys.modules:
        api_redis_module = ModuleType("api.redis_client")
        api_redis_module.redis_client = SimpleNamespace()
        api_redis_module.redis = api_redis_module.redis_client
        sys.modules["api.redis_client"] = api_redis_module

    if "bot.redis_cache" not in sys.modules:
        bot_redis_module = ModuleType("bot.redis_cache")
        bot_redis_module.redis_client = SimpleNamespace()
        sys.modules["bot.redis_cache"] = bot_redis_module


install_import_stubs()

import api.routers.dashboard as dashboard_router
from api.config import settings
from api.services.dashboard_access import (
    DashboardAccessError,
    get_company_present_worker_ids,
    get_dashboard_worker,
)
from bot.handlers.dashboard import cmd_dashboard
from db.calendar_service import create_calendar_event
from db.dashboard_tokens import dashboard_token_key
from db.models import (
    Base,
    BillingType,
    CalendarEventType,
    Company,
    CompanyPublicProfile,
    EventType,
    Site,
    TimeEvent,
    Worker,
    WorkerAccessRole,
    WorkerType,
)
from db.request_service import create_request
from db.security import hash_string


class FakeRedis:
    def __init__(self, values: dict[str, str | None]):
        self.values = values

    async def get(self, key: str) -> str | None:
        return self.values.get(key)


def signed_init_data(
    user_id: int,
    *,
    auth_date: int | None = None,
    username: str | None = None,
) -> str:
    user = {"id": user_id, "first_name": "Mini", "last_name": "App"}
    if username:
        user["username"] = username
    params = {
        "auth_date": str(auth_date or int(time.time())),
        "query_id": "dashboard-miniapp-test",
        "user": json.dumps(user, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(params.items()))
    secret_key = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(), hashlib.sha256).digest()
    params["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(params)


def run_db_test(test_coro):
    async def runner():
        with TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "dashboard_access.db"
            engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
            session_maker = async_sessionmaker(engine, expire_on_commit=False)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with session_maker() as session:
                await test_coro(session)

            await engine.dispose()

    asyncio.run(runner())


async def seed_company(session, suffix: str) -> Company:
    company = Company(
        name=f"Company {suffix}",
        owner_telegram_id_enc=f"owner_enc_{suffix}",
        owner_telegram_id_hash=f"owner_hash_{suffix}",
    )
    session.add(company)
    await session.flush()
    return company


async def seed_sek_public_profile(session, company: Company) -> CompanyPublicProfile:
    profile = CompanyPublicProfile(
        company_id=company.id,
        slug="sek",
        company_name="Generalbau S.E.K. GmbH",
        subtitle="Generalbau",
        about_text="SEK",
        address="Brandenburg",
        email=None,
        is_active=True,
    )
    session.add(profile)
    await session.flush()
    return profile


async def seed_site(session, company_id: int, suffix: str) -> Site:
    site = Site(
        company_id=company_id,
        name=f"Site {suffix}",
        qr_token=f"site_{suffix}",
        is_active=True,
    )
    session.add(site)
    await session.flush()
    return site


async def seed_worker(
    session,
    company_id: int,
    suffix: str,
    *,
    is_active: bool = True,
    can_view_dashboard: bool = True,
    time_tracking_enabled: bool = True,
    telegram_id: int | None = None,
) -> Worker:
    worker = Worker(
        company_id=company_id,
        telegram_id_enc=f"telegram_enc_{suffix}",
        telegram_id_hash=hash_string(str(telegram_id)) if telegram_id else f"telegram_hash_{suffix}",
        full_name_enc=f"name_enc_{suffix}",
        worker_type=WorkerType.FESTANGESTELLT,
        billing_type=BillingType.HOURLY,
        can_view_dashboard=can_view_dashboard,
        time_tracking_enabled=time_tracking_enabled,
        is_active=is_active,
    )
    session.add(worker)
    await session.flush()
    return worker


def test_get_dashboard_worker_valid_token():
    async def run_test(session):
        company = await seed_company(session, "valid")
        worker = await seed_worker(session, company.id, "valid")
        await session.commit()

        token = "valid-token"
        redis_client = FakeRedis({dashboard_token_key(token): str(worker.id)})

        result = await get_dashboard_worker(token, session, redis_client)

        assert result.id == worker.id

    run_db_test(run_test)


def test_get_dashboard_worker_missing_token():
    async def run_test(session):
        with pytest.raises(DashboardAccessError, match="missing_dashboard_token"):
            await get_dashboard_worker(None, session, FakeRedis({}))

    run_db_test(run_test)


def test_get_dashboard_worker_invalid_token():
    async def run_test(session):
        with pytest.raises(DashboardAccessError, match="invalid_dashboard_token"):
            await get_dashboard_worker("invalid-token", session, FakeRedis({}))

    run_db_test(run_test)


def test_get_dashboard_worker_inactive_worker():
    async def run_test(session):
        company = await seed_company(session, "inactive")
        worker = await seed_worker(session, company.id, "inactive", is_active=False)
        await session.commit()

        token = "inactive-token"
        redis_client = FakeRedis({dashboard_token_key(token): str(worker.id)})

        with pytest.raises(DashboardAccessError, match="dashboard_access_denied"):
            await get_dashboard_worker(token, session, redis_client)

    run_db_test(run_test)


def test_get_dashboard_worker_dashboard_disabled():
    async def run_test(session):
        company = await seed_company(session, "disabled")
        worker = await seed_worker(
            session,
            company.id,
            "disabled",
            can_view_dashboard=False,
        )
        await session.commit()

        token = "disabled-token"
        redis_client = FakeRedis({dashboard_token_key(token): str(worker.id)})

        with pytest.raises(DashboardAccessError, match="dashboard_access_denied"):
            await get_dashboard_worker(token, session, redis_client)

    run_db_test(run_test)


def test_get_dashboard_worker_allows_time_tracking_disabled_admin():
    async def run_test(session):
        company = await seed_company(session, "tracking-disabled-admin")
        worker = await seed_worker(
            session,
            company.id,
            "tracking-disabled-admin",
            can_view_dashboard=True,
            time_tracking_enabled=False,
        )
        await session.commit()

        token = "tracking-disabled-admin-token"
        redis_client = FakeRedis({dashboard_token_key(token): str(worker.id)})

        result = await get_dashboard_worker(token, session, redis_client)

        assert result.id == worker.id
        assert result.time_tracking_enabled is False

    run_db_test(run_test)


def test_dashboard_miniapp_bootstrap_allows_dashboard_user(monkeypatch):
    async def run_test(session):
        company = await seed_company(session, "miniapp")
        worker = await seed_worker(
            session,
            company.id,
            "miniapp",
            can_view_dashboard=True,
            telegram_id=123456,
        )
        await session.commit()

        monkeypatch.setattr(dashboard_router, "decrypt_string", lambda value: value)
        payload = dashboard_router.MiniAppBootstrapRequest(
            init_data=signed_init_data(123456),
        )

        bootstrap = await dashboard_router.dashboard_miniapp_bootstrap(
            payload=payload,
            db=session,
        )
        data = await dashboard_router.dashboard_data(
            token=None,
            telegram_init_data=payload.init_data,
            db=session,
        )

        assert bootstrap == {
            "auth_mode": "miniapp",
            "user": {
                "name": "name_enc_miniapp",
                "role": "OWNER",
            },
        }
        assert data["user"]["name"] == "name_enc_miniapp"
        assert data["workers"][0]["id"] == worker.id

    run_db_test(run_test)


def test_dashboard_miniapp_bootstrap_denies_non_dashboard_user():
    async def run_test(session):
        company = await seed_company(session, "miniapp-denied")
        await seed_worker(
            session,
            company.id,
            "miniapp-denied",
            can_view_dashboard=False,
            telegram_id=234567,
        )
        await session.commit()

        payload = dashboard_router.MiniAppBootstrapRequest(
            init_data=signed_init_data(234567),
        )

        with pytest.raises(HTTPException) as exc_info:
            await dashboard_router.dashboard_miniapp_bootstrap(payload=payload, db=session)

        assert exc_info.value.status_code == 404

    run_db_test(run_test)


def test_worker_home_miniapp_allows_regular_worker_own_data(monkeypatch):
    async def run_test(session):
        company = await seed_company(session, "worker-home")
        site = await seed_site(session, company.id, "worker-home")
        manager = await seed_worker(
            session,
            company.id,
            "worker-home-manager",
            can_view_dashboard=True,
        )
        worker = await seed_worker(
            session,
            company.id,
            "worker-home",
            can_view_dashboard=False,
            telegram_id=765432,
        )
        other_worker = await seed_worker(
            session,
            company.id,
            "worker-home-other",
            can_view_dashboard=False,
            telegram_id=876543,
        )
        worker.site_id = site.id
        worker.hourly_rate = 20
        worker.contract_hours_week = 38
        today = date.today()
        timestamp = datetime(today.year, today.month, today.day, 8, 0, tzinfo=timezone.utc)
        session.add_all(
            [
                worker,
                TimeEvent(
                    worker_id=worker.id,
                    site_id=site.id,
                    event_type=EventType.CHECKIN,
                    timestamp=timestamp,
                ),
                TimeEvent(
                    worker_id=other_worker.id,
                    site_id=site.id,
                    event_type=EventType.CHECKIN,
                    timestamp=timestamp,
                ),
            ]
        )
        await session.commit()
        await create_calendar_event(
            session,
            manager_worker=manager,
            worker_id=worker.id,
            event_type=CalendarEventType.VACATION,
            date_from=today,
            date_to=today,
            comment="Approved",
        )
        await create_request(
            session,
            creator_worker=worker,
            text="Forgot checkout",
        )

        monkeypatch.setattr(dashboard_router, "decrypt_string", lambda value: value)
        response = await dashboard_router.dashboard_worker_home(
            token=None,
            telegram_init_data=signed_init_data(765432),
            db=session,
        )

        assert response["user"] == {
            "id": worker.id,
            "name": "name_enc_worker-home",
            "role": "WORKER",
        }
        assert "workers" not in response
        assert response["site"]["name"] == "Site worker-home"
        assert response["status"]["last_event_type"] == EventType.CHECKIN.value
        assert response["hours"]["contract_hours_week"] == 38
        assert response["money"]["hourly_rate"] == 20
        assert response["calendar"]["items"][0]["label"] == "Urlaub"
        assert response["requests"]["open_count"] == 1
        assert response["requests"]["items"][0]["text"] == "Forgot checkout"

    run_db_test(run_test)


def test_dashboard_miniapp_bootstrap_denies_invalid_init_data():
    async def run_test(session):
        payload = dashboard_router.MiniAppBootstrapRequest(
            init_data="auth_date=1&user={}&hash=invalid",
        )

        with pytest.raises(HTTPException) as exc_info:
            await dashboard_router.dashboard_miniapp_bootstrap(payload=payload, db=session)

        assert exc_info.value.status_code == 404

    run_db_test(run_test)


def test_dashboard_miniapp_bootstrap_allows_platform_superadmin_without_worker_mapping(
    monkeypatch,
):
    async def run_test(session):
        company = await seed_company(session, "platform-superadmin")
        await seed_sek_public_profile(session, company)
        tracked_worker = await seed_worker(
            session,
            company.id,
            "platform-superadmin-worker",
            can_view_dashboard=False,
            telegram_id=456789,
        )
        await session.commit()

        monkeypatch.setattr(dashboard_router, "decrypt_string", lambda value: value)
        payload = dashboard_router.MiniAppBootstrapRequest(
            init_data=signed_init_data(345678, username="AnOleksii"),
        )

        bootstrap = await dashboard_router.dashboard_miniapp_bootstrap(
            payload=payload,
            db=session,
        )
        data = await dashboard_router.dashboard_data(
            token=None,
            telegram_init_data=payload.init_data,
            db=session,
        )

        mapped_worker = (
            await session.execute(
                select(Worker).where(Worker.telegram_id_hash == hash_string("345678"))
            )
        ).scalar_one_or_none()

        assert bootstrap["auth_mode"] == "miniapp"
        assert bootstrap["user"]["role"] == "PLATFORM_SUPERADMIN"
        assert data["user"]["role"] == "PLATFORM_SUPERADMIN"
        assert data["workers"][0]["id"] == tracked_worker.id
        assert mapped_worker is None

    run_db_test(run_test)


def test_dashboard_miniapp_bootstrap_links_configured_sek_admin(monkeypatch):
    async def run_test(session):
        monkeypatch.setattr(settings, "ADMIN_USERNAMES", ["sekmanager"])
        monkeypatch.setattr(settings, "PLATFORM_SUPERADMIN_USERNAMES", ["anoleksii"])

        company = await seed_company(session, "sek-admin")
        await seed_sek_public_profile(session, company)
        owner = await seed_worker(
            session,
            company.id,
            "sek-owner",
            can_view_dashboard=True,
            telegram_id=456789,
        )
        company.owner_telegram_id_hash = owner.telegram_id_hash
        await session.commit()

        monkeypatch.setattr(dashboard_router, "decrypt_string", lambda value: value)
        payload = dashboard_router.MiniAppBootstrapRequest(
            init_data=signed_init_data(345678, username="SEKManager"),
        )

        bootstrap = await dashboard_router.dashboard_miniapp_bootstrap(
            payload=payload,
            db=session,
        )

        created_worker = (
            await session.execute(
                select(Worker).where(Worker.telegram_id_hash == hash_string("345678"))
            )
        ).scalar_one()

        assert bootstrap["auth_mode"] == "miniapp"
        assert created_worker.company_id == company.id
        assert created_worker.can_view_dashboard is True
        assert created_worker.is_active is True
        assert created_worker.time_tracking_enabled is False
        assert created_worker.access_role == WorkerAccessRole.OBJEKTMANAGER.value
        assert created_worker.created_by == owner.id

    run_db_test(run_test)


def test_dashboard_miniapp_bootstrap_denies_unconfigured_sek_admin():
    async def run_test(session):
        company = await seed_company(session, "sek-admin-denied")
        await seed_sek_public_profile(session, company)
        await session.commit()

        payload = dashboard_router.MiniAppBootstrapRequest(
            init_data=signed_init_data(456789, username="not-configured"),
        )

        with pytest.raises(HTTPException) as exc_info:
            await dashboard_router.dashboard_miniapp_bootstrap(payload=payload, db=session)

        assert exc_info.value.status_code == 404

    run_db_test(run_test)


def test_get_company_present_worker_ids_scopes_to_company():
    async def run_test(session):
        target_day = date(2026, 4, 8)
        timestamp = datetime(2026, 4, 8, 8, 30, tzinfo=timezone.utc)

        company_a = await seed_company(session, "a")
        company_b = await seed_company(session, "b")
        site_a = await seed_site(session, company_a.id, "a")
        site_b = await seed_site(session, company_b.id, "b")
        worker_a = await seed_worker(session, company_a.id, "a")
        worker_b = await seed_worker(session, company_b.id, "b")

        session.add_all(
            [
                TimeEvent(
                    worker_id=worker_a.id,
                    site_id=site_a.id,
                    event_type=EventType.CHECKIN,
                    timestamp=timestamp,
                ),
                TimeEvent(
                    worker_id=worker_b.id,
                    site_id=site_b.id,
                    event_type=EventType.CHECKIN,
                    timestamp=timestamp,
                ),
            ]
        )
        await session.commit()

        result = await get_company_present_worker_ids(session, company_a.id, target_day)

        assert result == {worker_a.id}

    run_db_test(run_test)


def test_get_company_present_worker_ids_excludes_tracking_disabled_workers():
    async def run_test(session):
        target_day = date(2026, 4, 8)
        timestamp = datetime(2026, 4, 8, 8, 30, tzinfo=timezone.utc)

        company = await seed_company(session, "tracking-participants")
        site = await seed_site(session, company.id, "tracking-participants")
        enabled_worker = await seed_worker(session, company.id, "tracking-enabled")
        disabled_worker = await seed_worker(
            session,
            company.id,
            "tracking-disabled",
            time_tracking_enabled=False,
        )

        session.add_all(
            [
                TimeEvent(
                    worker_id=enabled_worker.id,
                    site_id=site.id,
                    event_type=EventType.CHECKIN,
                    timestamp=timestamp,
                ),
                TimeEvent(
                    worker_id=disabled_worker.id,
                    site_id=site.id,
                    event_type=EventType.CHECKIN,
                    timestamp=timestamp,
                ),
            ]
        )
        await session.commit()

        result = await get_company_present_worker_ids(session, company.id, target_day)

        assert result == {enabled_worker.id}

    run_db_test(run_test)


def test_dashboard_route_returns_shell_for_missing_token():
    request = SimpleNamespace(url=SimpleNamespace(path="/dashboard"), query_params={})
    response = asyncio.run(
        dashboard_router.serve_dashboard(
            request=request,
            token=None,
            version=dashboard_router.DASHBOARD_SHELL_VERSION,
        )
    )
    assert isinstance(response, FileResponse)
    assert response.path.endswith("api/static/dashboard.html")


def test_dashboard_route_redirects_unversioned_shell():
    request = SimpleNamespace(url=SimpleNamespace(path="/dashboard"), query_params={})
    response = asyncio.run(
        dashboard_router.serve_dashboard(request=request, token=None, version=None)
    )

    assert isinstance(response, RedirectResponse)
    assert response.headers["location"] == f"/dashboard?v={dashboard_router.DASHBOARD_SHELL_VERSION}"


def test_dashboard_route_preserves_legacy_token_on_version_redirect():
    request = SimpleNamespace(
        url=SimpleNamespace(path="/dashboard"),
        query_params={"token": "legacy-token"},
    )
    response = asyncio.run(
        dashboard_router.serve_dashboard(
            request=request,
            token="legacy-token",
            version=None,
        )
    )

    assert isinstance(response, RedirectResponse)
    assert response.headers["location"] == (
        f"/dashboard?token=legacy-token&v={dashboard_router.DASHBOARD_SHELL_VERSION}"
    )


def test_dashboard_data_route_returns_404_for_invalid_token(monkeypatch):
    async def run_test(session):
        monkeypatch.setattr(dashboard_router, "redis_client", FakeRedis({}))

        with pytest.raises(HTTPException) as exc_info:
            await dashboard_router.dashboard_data(token="invalid-token", db=session)

        assert exc_info.value.status_code == 404

    run_db_test(run_test)


def test_dashboard_data_excludes_tracking_disabled_workers(monkeypatch):
    async def run_test(session):
        company = await seed_company(session, "dashboard-filter")
        admin = await seed_worker(
            session,
            company.id,
            "dashboard-filter-admin",
            can_view_dashboard=True,
            time_tracking_enabled=False,
        )
        tracked_worker = await seed_worker(
            session,
            company.id,
            "dashboard-filter-worker",
            can_view_dashboard=False,
            time_tracking_enabled=True,
        )
        await session.commit()

        token = "dashboard-filter-token"
        monkeypatch.setattr(
            dashboard_router,
            "redis_client",
            FakeRedis({dashboard_token_key(token): str(admin.id)}),
        )
        monkeypatch.setattr(dashboard_router, "decrypt_string", lambda value: value)

        result = await dashboard_router.dashboard_data(token=token, db=session)

        assert result["today"]["total_workers"] == 1
        assert [worker["id"] for worker in result["workers"]] == [tracked_worker.id]

    run_db_test(run_test)


def test_dashboard_command_is_silent_for_unauthorized_worker():
    async def run_test():
        message = SimpleNamespace(answer=AsyncMock())
        current_worker = SimpleNamespace(
            is_active=True,
            can_view_dashboard=False,
        )

        await cmd_dashboard(message=message, current_worker=current_worker, locale="de")

        message.answer.assert_not_called()

    asyncio.run(run_test())
