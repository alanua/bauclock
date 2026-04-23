import asyncio
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace

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

import api.routers.dashboard as dashboard_router
from db.dashboard_tokens import build_dashboard_token_payload, dashboard_token_key
from db.models import Base, BillingType, Company, RequestStatus, Worker, WorkerType
from db.request_service import create_request


class FakeRedis:
    def __init__(self, values: dict[str, str | None]):
        self.values = values

    async def get(self, key: str) -> str | None:
        return self.values.get(key)


def run_db_test(test_coro):
    async def runner():
        with TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "dashboard_requests.db"
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
    can_view_dashboard: bool = False,
) -> Worker:
    worker = Worker(
        company_id=company_id,
        telegram_id_enc=f"telegram_enc_{suffix}",
        telegram_id_hash=f"telegram_hash_{suffix}",
        full_name_enc=f"Worker {suffix}",
        worker_type=WorkerType.FESTANGESTELLT,
        billing_type=BillingType.HOURLY,
        can_view_dashboard=can_view_dashboard,
        is_active=True,
    )
    session.add(worker)
    await session.flush()
    return worker


def dashboard_token_for(worker: Worker) -> tuple[str, FakeRedis]:
    token = f"dashboard-token-{worker.id}"
    redis_client = FakeRedis(
        {
            dashboard_token_key(token): build_dashboard_token_payload(
                worker_id=worker.id,
                company_id=worker.company_id,
            )
        }
    )
    return token, redis_client


def test_dashboard_capable_user_can_fetch_company_requests(monkeypatch):
    async def run_test(session):
        company = await seed_company(session, "fetch")
        manager = await seed_worker(
            session,
            company.id,
            "manager",
            can_view_dashboard=True,
        )
        worker = await seed_worker(session, company.id, "worker")
        await create_request(
            session,
            creator_worker=worker,
            text="Problem with equipment",
        )

        token, redis_client = dashboard_token_for(manager)
        monkeypatch.setattr(dashboard_router, "redis_client", redis_client)
        monkeypatch.setattr(dashboard_router, "decrypt_string", lambda value: value)

        response = await dashboard_router.dashboard_requests(token=token, db=session)

        assert len(response["requests"]) == 1
        assert response["requests"][0]["target_worker_name"] == "Worker worker"
        assert response["requests"][0]["text"] == "Problem with equipment"
        assert response["requests"][0]["status"] == RequestStatus.OPEN.value

    run_db_test(run_test)


def test_non_dashboard_user_is_denied_company_requests(monkeypatch):
    async def run_test(session):
        company = await seed_company(session, "denied")
        worker = await seed_worker(session, company.id, "worker", can_view_dashboard=False)

        token, redis_client = dashboard_token_for(worker)
        monkeypatch.setattr(dashboard_router, "redis_client", redis_client)

        with pytest.raises(HTTPException) as exc_info:
            await dashboard_router.dashboard_requests(token=token, db=session)

        assert exc_info.value.status_code == 403

    run_db_test(run_test)


def test_resolve_action_updates_status(monkeypatch):
    async def run_test(session):
        company = await seed_company(session, "resolve")
        manager = await seed_worker(
            session,
            company.id,
            "manager",
            can_view_dashboard=True,
        )
        worker = await seed_worker(session, company.id, "worker")
        request = await create_request(
            session,
            creator_worker=worker,
            text="Need review",
        )

        token, redis_client = dashboard_token_for(manager)
        monkeypatch.setattr(dashboard_router, "redis_client", redis_client)

        response = await dashboard_router.dashboard_request_resolve(
            request_id=request.id,
            token=token,
            db=session,
        )
        refreshed = await session.get(type(request), request.id)

        assert response["status"] == RequestStatus.RESOLVED.value
        assert refreshed.status == RequestStatus.RESOLVED.value
        assert refreshed.resolved_at is not None

    run_db_test(run_test)


def test_reject_action_updates_status(monkeypatch):
    async def run_test(session):
        company = await seed_company(session, "reject")
        manager = await seed_worker(
            session,
            company.id,
            "manager",
            can_view_dashboard=True,
        )
        worker = await seed_worker(session, company.id, "worker")
        request = await create_request(
            session,
            creator_worker=worker,
            text="Wrong hours",
        )

        token, redis_client = dashboard_token_for(manager)
        monkeypatch.setattr(dashboard_router, "redis_client", redis_client)

        response = await dashboard_router.dashboard_request_reject(
            request_id=request.id,
            token=token,
            db=session,
        )
        refreshed = await session.get(type(request), request.id)

        assert response["status"] == RequestStatus.REJECTED.value
        assert refreshed.status == RequestStatus.REJECTED.value
        assert refreshed.resolved_at is None

    run_db_test(run_test)
