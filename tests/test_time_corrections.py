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
            db_path = Path(tmp_dir) / "time_corrections.db"
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


def test_objektmanager_cannot_move_manual_correction_to_other_site():
    async def run_test(session):
        company = await seed_company(session, "manual-site-scope")
        own_site = await seed_site(session, company.id, "own")
        other_site = await seed_site(session, company.id, "other")
        manager = await seed_worker(
            session,
            company.id,
            "objektmanager",
            can_view_dashboard=True,
            access_role=WorkerAccessRole.OBJEKTMANAGER.value,
            site_id=own_site.id,
            time_tracking_enabled=False,
        )
        worker = await seed_worker(session, company.id, "worker", site_id=own_site.id)
        event = TimeEvent(
            worker_id=worker.id,
            site_id=own_site.id,
            event_type=EventType.CHECKIN,
            timestamp=datetime(2026, 4, 21, 8, 0, tzinfo=timezone.utc),
        )
        session.add(event)
        await session.commit()

        with pytest.raises(ManualTimeCorrectionError, match="manual_time_site_scope_denied"):
            await apply_manual_time_correction(
                session,
                actor_worker=manager,
                event_id=event.id,
                reason="Supervisor correction",
                new_site_id=other_site.id,
            )

        unchanged = await session.get(TimeEvent, event.id)
        assert unchanged.site_id == own_site.id

    run_db_test(run_test)


def test_company_owner_can_move_manual_correction_to_same_company_site():
    async def run_test(session):
        company = await seed_company(session, "manual-owner-site-scope")
        own_site = await seed_site(session, company.id, "own")
        other_site = await seed_site(session, company.id, "other")
        owner = await seed_worker(
            session,
            company.id,
            "owner",
            can_view_dashboard=True,
            access_role=WorkerAccessRole.COMPANY_OWNER.value,
            time_tracking_enabled=False,
        )
        worker = await seed_worker(session, company.id, "worker", site_id=own_site.id)
        event = TimeEvent(
            worker_id=worker.id,
            site_id=own_site.id,
            event_type=EventType.CHECKIN,
            timestamp=datetime(2026, 4, 21, 8, 0, tzinfo=timezone.utc),
        )
        session.add(event)
        await session.commit()

        corrected = await apply_manual_time_correction(
            session,
            actor_worker=owner,
            event_id=event.id,
            reason="Owner correction",
            new_site_id=other_site.id,
        )

        assert corrected.site_id == other_site.id
        assert corrected.is_manual is True
        assert corrected.corrected_by_worker_id == owner.id
        assert corrected.correction_reason == "Owner correction"

    run_db_test(run_test)
