import asyncio
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
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
from api.services.dashboard_access import (
    DashboardAccessError,
    get_company_present_worker_ids,
    get_dashboard_worker,
)
from bot.handlers.dashboard import cmd_dashboard
from db.dashboard_tokens import dashboard_token_key
from db.models import Base, BillingType, Company, EventType, Site, TimeEvent, Worker, WorkerType


class FakeRedis:
    def __init__(self, values: dict[str, str | None]):
        self.values = values

    async def get(self, key: str) -> str | None:
        return self.values.get(key)


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
) -> Worker:
    worker = Worker(
        company_id=company_id,
        telegram_id_enc=f"telegram_enc_{suffix}",
        telegram_id_hash=f"telegram_hash_{suffix}",
        full_name_enc=f"name_enc_{suffix}",
        worker_type=WorkerType.FESTANGESTELLT,
        billing_type=BillingType.HOURLY,
        can_view_dashboard=can_view_dashboard,
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


def test_dashboard_route_returns_404_for_missing_token():
    async def run_test(session):
        with pytest.raises(HTTPException) as exc_info:
            await dashboard_router.serve_dashboard(token=None, db=session)

        assert exc_info.value.status_code == 404

    run_db_test(run_test)


def test_dashboard_data_route_returns_404_for_invalid_token(monkeypatch):
    async def run_test(session):
        monkeypatch.setattr(dashboard_router, "redis_client", FakeRedis({}))

        with pytest.raises(HTTPException) as exc_info:
            await dashboard_router.dashboard_data(token="invalid-token", db=session)

        assert exc_info.value.status_code == 404

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
