import asyncio
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models import Base, BillingType, Company, RequestStatus, Worker, WorkerType
from db.request_service import (
    RequestAccessError,
    create_request,
    list_company_requests,
    list_worker_requests,
    reject_request,
    resolve_request,
)


def run_db_test(test_coro):
    async def runner():
        with TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "requests.db"
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
        full_name_enc=f"name_enc_{suffix}",
        worker_type=WorkerType.FESTANGESTELLT,
        billing_type=BillingType.HOURLY,
        can_view_dashboard=can_view_dashboard,
        is_active=True,
    )
    session.add(worker)
    await session.flush()
    return worker


def test_create_worker_self_request():
    async def run_test(session):
        company = await seed_company(session, "self")
        worker = await seed_worker(session, company.id, "worker")

        request = await create_request(
            session,
            creator_worker=worker,
            text="  Problem on site  ",
            related_date=date(2026, 4, 10),
        )

        assert request.company_id == company.id
        assert request.created_by_worker_id == worker.id
        assert request.target_worker_id == worker.id
        assert request.related_date == date(2026, 4, 10)
        assert request.text == "Problem on site"
        assert request.status == RequestStatus.OPEN.value
        assert request.resolved_at is None

    run_db_test(run_test)


def test_list_worker_requests_returns_only_owned_requests():
    async def run_test(session):
        company = await seed_company(session, "worker-list")
        worker = await seed_worker(session, company.id, "worker")
        other_worker = await seed_worker(session, company.id, "other")
        manager = await seed_worker(
            session,
            company.id,
            "manager",
            can_view_dashboard=True,
        )

        own_request = await create_request(session, creator_worker=worker, text="Own")
        targeted_request = await create_request(
            session,
            creator_worker=manager,
            target_worker_id=worker.id,
            text="Manager-created for worker",
        )
        await create_request(session, creator_worker=other_worker, text="Other")
        await create_request(session, creator_worker=manager, text="General")

        worker_requests = await list_worker_requests(session, worker=worker)

        assert {request.id for request in worker_requests} == {
            own_request.id,
            targeted_request.id,
        }

    run_db_test(run_test)


def test_list_company_requests_for_dashboard_capable_manager():
    async def run_test(session):
        company = await seed_company(session, "manager-list")
        other_company = await seed_company(session, "other-company")
        manager = await seed_worker(
            session,
            company.id,
            "manager",
            can_view_dashboard=True,
        )
        worker = await seed_worker(session, company.id, "worker")
        other_company_worker = await seed_worker(
            session,
            other_company.id,
            "other-company-worker",
        )

        first_request = await create_request(session, creator_worker=worker, text="First")
        second_request = await create_request(
            session,
            creator_worker=manager,
            text="Second",
        )
        await create_request(
            session,
            creator_worker=other_company_worker,
            text="Other company",
        )

        company_requests = await list_company_requests(
            session,
            manager_worker=manager,
        )

        assert {request.id for request in company_requests} == {
            first_request.id,
            second_request.id,
        }

    run_db_test(run_test)


def test_list_company_requests_rejects_non_manager_worker():
    async def run_test(session):
        company = await seed_company(session, "denied")
        worker = await seed_worker(session, company.id, "worker")

        with pytest.raises(RequestAccessError, match="company_requests_denied"):
            await list_company_requests(session, manager_worker=worker)

    run_db_test(run_test)


def test_resolve_request():
    async def run_test(session):
        company = await seed_company(session, "resolve")
        manager = await seed_worker(
            session,
            company.id,
            "manager",
            can_view_dashboard=True,
        )
        worker = await seed_worker(session, company.id, "worker")
        request = await create_request(session, creator_worker=worker, text="Resolve me")

        resolved = await resolve_request(
            session,
            request_id=request.id,
            manager_worker=manager,
        )

        assert resolved.status == RequestStatus.RESOLVED.value
        assert resolved.resolved_at is not None
        assert resolved.updated_at is not None

    run_db_test(run_test)


def test_reject_request():
    async def run_test(session):
        company = await seed_company(session, "reject")
        manager = await seed_worker(
            session,
            company.id,
            "manager",
            can_view_dashboard=True,
        )
        worker = await seed_worker(session, company.id, "worker")
        request = await create_request(session, creator_worker=worker, text="Reject me")

        rejected = await reject_request(
            session,
            request_id=request.id,
            manager_worker=manager,
        )

        assert rejected.status == RequestStatus.REJECTED.value
        assert rejected.resolved_at is None
        assert rejected.updated_at is not None

    run_db_test(run_test)
