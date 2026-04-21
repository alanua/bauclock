import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
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
    if "api.redis_client" not in sys.modules:
        api_redis_module = ModuleType("api.redis_client")
        api_redis_module.redis_client = SimpleNamespace()
        api_redis_module.redis = api_redis_module.redis_client
        sys.modules["api.redis_client"] = api_redis_module


install_import_stubs()

import api.routers.dashboard as dashboard_views
import api.routers.dashboard_router as secure_dashboard_router
from db.dashboard_tokens import DASHBOARD_TOKEN_TTL_SECONDS, build_dashboard_token_payload, dashboard_token_key
from db.models import Base, BillingType, Company, Worker, WorkerAccessRole, WorkerType


class FakeRedis:
    def __init__(self, values: dict[str, str | None]):
        self.values = values

    async def get(self, key: str) -> str | None:
        return self.values.get(key)


def run_db_test(test_coro):
    async def runner():
        with TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "dashboard_router_security.db"
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


async def seed_worker(
    session,
    company_id: int,
    suffix: str,
    *,
    is_active: bool = True,
    can_view_dashboard: bool = True,
    access_role: WorkerAccessRole = WorkerAccessRole.COMPANY_OWNER,
) -> Worker:
    worker = Worker(
        company_id=company_id,
        telegram_id_enc=f"telegram_enc_{suffix}",
        telegram_id_hash=f"telegram_hash_{suffix}",
        full_name_enc=f"name_enc_{suffix}",
        worker_type=WorkerType.FESTANGESTELLT,
        billing_type=BillingType.HOURLY,
        can_view_dashboard=can_view_dashboard,
        access_role=access_role.value,
        time_tracking_enabled=False,
        is_active=is_active,
    )
    session.add(worker)
    await session.flush()
    return worker


def _dashboard_request(token: str | None):
    return SimpleNamespace(
        url=SimpleNamespace(path="/dashboard"),
        query_params={"token": token} if token else {},
    )


async def _assert_shell_denied(monkeypatch, session, *, token: str | None, redis_values: dict[str, str | None]) -> None:
    delegate = AsyncMock(return_value="ok")
    monkeypatch.setattr(secure_dashboard_router, "redis_client", FakeRedis(redis_values))
    monkeypatch.setattr(dashboard_views, "serve_dashboard", delegate)

    with pytest.raises(HTTPException) as exc_info:
        await secure_dashboard_router.serve_dashboard(
            request=_dashboard_request(token),
            token=token,
            version=dashboard_views.DASHBOARD_SHELL_VERSION,
            db=session,
        )

    assert exc_info.value.status_code == 403
    delegate.assert_not_awaited()


async def _assert_data_denied(monkeypatch, session, *, token: str | None, redis_values: dict[str, str | None]) -> None:
    delegate = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(secure_dashboard_router, "redis_client", FakeRedis(redis_values))
    monkeypatch.setattr(dashboard_views, "dashboard_data", delegate)

    with pytest.raises(HTTPException) as exc_info:
        await secure_dashboard_router.dashboard_data(token=token, db=session)

    assert exc_info.value.status_code == 403
    delegate.assert_not_awaited()


def test_dashboard_shell_route_accepts_valid_token(monkeypatch):
    async def run_test(session):
        company = await seed_company(session, "shell-valid")
        worker = await seed_worker(session, company.id, "shell-valid")
        await session.commit()

        token = "shell-valid-token"
        monkeypatch.setattr(
            secure_dashboard_router,
            "redis_client",
            FakeRedis(
                {
                    dashboard_token_key(token): build_dashboard_token_payload(
                        worker_id=worker.id,
                        company_id=worker.company_id,
                    )
                }
            ),
        )
        delegate = AsyncMock(return_value="shell-ok")
        monkeypatch.setattr(dashboard_views, "serve_dashboard", delegate)

        response = await secure_dashboard_router.serve_dashboard(
            request=_dashboard_request(token),
            token=token,
            version=dashboard_views.DASHBOARD_SHELL_VERSION,
            db=session,
        )

        assert response == "shell-ok"
        delegate.assert_awaited_once()

    run_db_test(run_test)


def test_dashboard_data_route_accepts_valid_token(monkeypatch):
    async def run_test(session):
        company = await seed_company(session, "data-valid")
        worker = await seed_worker(session, company.id, "data-valid")
        await session.commit()

        token = "data-valid-token"
        monkeypatch.setattr(
            secure_dashboard_router,
            "redis_client",
            FakeRedis(
                {
                    dashboard_token_key(token): build_dashboard_token_payload(
                        worker_id=worker.id,
                        company_id=worker.company_id,
                    )
                }
            ),
        )
        delegate = AsyncMock(return_value={"ok": True})
        monkeypatch.setattr(dashboard_views, "dashboard_data", delegate)

        response = await secure_dashboard_router.dashboard_data(token=token, db=session)

        assert response == {"ok": True}
        delegate.assert_awaited_once_with(token=token, telegram_init_data=None, db=session)

    run_db_test(run_test)


@pytest.mark.parametrize("route_name", ["shell", "data"])
def test_dashboard_routes_reject_missing_token(monkeypatch, route_name):
    async def run_test(session):
        if route_name == "shell":
            await _assert_shell_denied(monkeypatch, session, token=None, redis_values={})
        else:
            await _assert_data_denied(monkeypatch, session, token=None, redis_values={})

    run_db_test(run_test)


@pytest.mark.parametrize("route_name", ["shell", "data"])
def test_dashboard_routes_reject_invalid_token(monkeypatch, route_name):
    async def run_test(session):
        if route_name == "shell":
            await _assert_shell_denied(monkeypatch, session, token="invalid", redis_values={})
        else:
            await _assert_data_denied(monkeypatch, session, token="invalid", redis_values={})

    run_db_test(run_test)


@pytest.mark.parametrize("route_name", ["shell", "data"])
def test_dashboard_routes_reject_expired_token(monkeypatch, route_name):
    async def run_test(session):
        company = await seed_company(session, f"{route_name}-expired")
        worker = await seed_worker(session, company.id, f"{route_name}-expired")
        await session.commit()

        token = f"{route_name}-expired-token"
        expired_payload = build_dashboard_token_payload(
            worker_id=worker.id,
            company_id=worker.company_id,
            issued_at=datetime.now(timezone.utc) - timedelta(seconds=DASHBOARD_TOKEN_TTL_SECONDS + 5),
        )
        redis_values = {dashboard_token_key(token): expired_payload}

        if route_name == "shell":
            await _assert_shell_denied(monkeypatch, session, token=token, redis_values=redis_values)
        else:
            await _assert_data_denied(monkeypatch, session, token=token, redis_values=redis_values)

    run_db_test(run_test)


@pytest.mark.parametrize("route_name", ["shell", "data"])
def test_dashboard_routes_reject_worker_without_dashboard_rights(monkeypatch, route_name):
    async def run_test(session):
        company = await seed_company(session, f"{route_name}-no-dashboard")
        worker = await seed_worker(
            session,
            company.id,
            f"{route_name}-no-dashboard",
            can_view_dashboard=False,
            access_role=WorkerAccessRole.WORKER,
        )
        await session.commit()

        token = f"{route_name}-no-dashboard-token"
        redis_values = {
            dashboard_token_key(token): build_dashboard_token_payload(
                worker_id=worker.id,
                company_id=worker.company_id,
            )
        }

        if route_name == "shell":
            await _assert_shell_denied(monkeypatch, session, token=token, redis_values=redis_values)
        else:
            await _assert_data_denied(monkeypatch, session, token=token, redis_values=redis_values)

    run_db_test(run_test)


@pytest.mark.parametrize("route_name", ["shell", "data"])
def test_dashboard_routes_reject_company_scope_mismatch(monkeypatch, route_name):
    async def run_test(session):
        company = await seed_company(session, f"{route_name}-scope")
        worker = await seed_worker(session, company.id, f"{route_name}-scope")
        await session.commit()

        token = f"{route_name}-scope-token"
        redis_values = {
            dashboard_token_key(token): build_dashboard_token_payload(
                worker_id=worker.id,
                company_id=worker.company_id + 999,
            )
        }

        if route_name == "shell":
            await _assert_shell_denied(monkeypatch, session, token=token, redis_values=redis_values)
        else:
            await _assert_data_denied(monkeypatch, session, token=token, redis_values=redis_values)

    run_db_test(run_test)
