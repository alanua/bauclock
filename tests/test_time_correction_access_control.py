import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault(
    "ENCRYPTION_KEY",
    "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff",
)
os.environ.setdefault("HASH_PEPPER", "test_pepper")

if "api.redis_client" not in sys.modules:
    api_redis_module = ModuleType("api.redis_client")
    api_redis_module.redis_client = SimpleNamespace()
    api_redis_module.redis = api_redis_module.redis_client
    sys.modules["api.redis_client"] = api_redis_module

from db.models import Base, BillingType, EventType, Site, TimeEvent, Worker, WorkerAccessRole, WorkerType
from db.time_corrections import ManualTimeCorrectionError, apply_manual_time_correction


def run_db_test(test_coro):
    async def runner():
        with TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "time_correction_access_control.db"
            engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
            session_maker = async_sessionmaker(engine, expire_on_commit=False)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with session_maker() as session:
                await test_coro(session)

            await engine.dispose()

    asyncio.run(runner())


async def seed_company(session, suffix: str):
    from db.models import Company

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
    access_role: str = WorkerAccessRole.WORKER.value,
    can_view_dashboard: bool = False,
    site_id: int | None = None,
    time_tracking_enabled: bool = True,
) -> Worker:
    worker = Worker(
        company_id=company_id,
        site_id=site_id,
        telegram_id_enc=f"telegram_enc_{suffix}",
        telegram_id_hash=f"telegram_hash_{suffix}",
        full_name_enc=f"name_enc_{suffix}",
        worker_type=WorkerType.FESTANGESTELLT,
        billing_type=BillingType.HOURLY,
        can_view_dashboard=can_view_dashboard,
        access_role=access_role,
        time_tracking_enabled=time_tracking_enabled,
        is_active=True,
    )
    session.add(worker)
    await session.flush()
    return worker


async def seed_time_event(session, worker: Worker, site: Site) -> TimeEvent:
    event = TimeEvent(
        worker_id=worker.id,
        site_id=site.id,
        event_type=EventType.CHECKIN,
        timestamp=datetime(2026, 4, 21, 8, 0, tzinfo=timezone.utc),
    )
    session.add(event)
    await session.flush()
    return event


def test_accountant_cannot_apply_manual_time_correction():
    async def run_test(session):
        company = await seed_company(session, "manual-accountant")
        site = await seed_site(session, company.id, "site")
        accountant = await seed_worker(
            session,
            company.id,
            "accountant",
            access_role=WorkerAccessRole.ACCOUNTANT.value,
            can_view_dashboard=True,
            time_tracking_enabled=False,
        )
        worker = await seed_worker(session, company.id, "worker", site_id=site.id)
        event = await seed_time_event(session, worker, site)
        await session.commit()

        with pytest.raises(ManualTimeCorrectionError, match="manual_time_correction_denied"):
            await apply_manual_time_correction(
                session,
                actor_worker=accountant,
                event_id=event.id,
                reason="Accountant correction",
                new_timestamp=datetime(2026, 4, 21, 9, 0, tzinfo=timezone.utc),
            )

        unchanged = await session.get(TimeEvent, event.id)
        assert unchanged.timestamp == datetime(2026, 4, 21, 8, 0, tzinfo=timezone.utc)
        assert unchanged.is_manual is False

    run_db_test(run_test)


def test_objektmanager_cannot_correct_other_site_worker_event():
    async def run_test(session):
        company = await seed_company(session, "manual-other-site")
        own_site = await seed_site(session, company.id, "own")
        other_site = await seed_site(session, company.id, "other")
        manager = await seed_worker(
            session,
            company.id,
            "objektmanager",
            access_role=WorkerAccessRole.OBJEKTMANAGER.value,
            can_view_dashboard=True,
            site_id=own_site.id,
            time_tracking_enabled=False,
        )
        other_worker = await seed_worker(session, company.id, "other-worker", site_id=other_site.id)
        event = await seed_time_event(session, other_worker, other_site)
        await session.commit()

        with pytest.raises(ManualTimeCorrectionError, match="manual_time_scope_denied"):
            await apply_manual_time_correction(
                session,
                actor_worker=manager,
                event_id=event.id,
                reason="Other site correction",
                new_timestamp=datetime(2026, 4, 21, 9, 0, tzinfo=timezone.utc),
            )

        unchanged = await session.get(TimeEvent, event.id)
        assert unchanged.timestamp == datetime(2026, 4, 21, 8, 0, tzinfo=timezone.utc)
        assert unchanged.is_manual is False

    run_db_test(run_test)


def test_owner_cannot_move_manual_correction_to_other_company_site():
    async def run_test(session):
        company = await seed_company(session, "manual-owner")
        other_company = await seed_company(session, "manual-other-company")
        site = await seed_site(session, company.id, "site")
        other_site = await seed_site(session, other_company.id, "other")
        owner = await seed_worker(
            session,
            company.id,
            "owner",
            access_role=WorkerAccessRole.COMPANY_OWNER.value,
            can_view_dashboard=True,
            time_tracking_enabled=False,
        )
        worker = await seed_worker(session, company.id, "worker", site_id=site.id)
        event = await seed_time_event(session, worker, site)
        await session.commit()

        with pytest.raises(ManualTimeCorrectionError, match="manual_time_site_scope_denied"):
            await apply_manual_time_correction(
                session,
                actor_worker=owner,
                event_id=event.id,
                reason="Cross company site correction",
                new_site_id=other_site.id,
            )

        unchanged = await session.get(TimeEvent, event.id)
        assert unchanged.site_id == site.id
        assert unchanged.is_manual is False

    run_db_test(run_test)
