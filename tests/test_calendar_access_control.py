import asyncio
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.calendar_service import (
    CalendarAccessError,
    create_calendar_event,
    deactivate_calendar_event,
    list_company_calendar_events,
)
from db.models import (
    Base,
    BillingType,
    CalendarEventType,
    Company,
    Site,
    Worker,
    WorkerAccessRole,
    WorkerType,
)


def run_db_test(test_coro):
    async def runner():
        with TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "calendar_access_control.db"
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
    can_view_dashboard: bool = False,
    site_id: int | None = None,
    access_role: str = WorkerAccessRole.WORKER.value,
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
        is_active=True,
    )
    session.add(worker)
    await session.flush()
    return worker


def test_calendar_access_denies_accountant_create_list_and_deactivate():
    async def run_test(session):
        company = await seed_company(session, "accountant-calendar")
        owner = await seed_worker(
            session,
            company.id,
            "owner",
            can_view_dashboard=True,
            access_role=WorkerAccessRole.COMPANY_OWNER.value,
        )
        accountant = await seed_worker(
            session,
            company.id,
            "accountant",
            can_view_dashboard=True,
            access_role=WorkerAccessRole.ACCOUNTANT.value,
        )
        worker = await seed_worker(session, company.id, "worker")
        event = await create_calendar_event(
            session,
            manager_worker=owner,
            worker_id=worker.id,
            event_type=CalendarEventType.VACATION,
            date_from=date(2026, 6, 1),
            date_to=date(2026, 6, 1),
        )

        with pytest.raises(CalendarAccessError, match="calendar_event_create_denied"):
            await create_calendar_event(
                session,
                manager_worker=accountant,
                worker_id=worker.id,
                event_type=CalendarEventType.VACATION,
                date_from=date(2026, 6, 2),
                date_to=date(2026, 6, 2),
            )
        with pytest.raises(CalendarAccessError, match="company_calendar_events_denied"):
            await list_company_calendar_events(session, manager_worker=accountant)
        with pytest.raises(CalendarAccessError, match="calendar_event_deactivate_denied"):
            await deactivate_calendar_event(
                session,
                event_id=event.id,
                manager_worker=accountant,
            )

    run_db_test(run_test)


def test_objektmanager_calendar_denies_company_wide_and_other_site_targets():
    async def run_test(session):
        company = await seed_company(session, "objektmanager-calendar")
        own_site = await seed_site(session, company.id, "own")
        other_site = await seed_site(session, company.id, "other")
        manager = await seed_worker(
            session,
            company.id,
            "objektmanager",
            can_view_dashboard=True,
            access_role=WorkerAccessRole.OBJEKTMANAGER.value,
            site_id=own_site.id,
        )
        own_worker = await seed_worker(session, company.id, "own-worker", site_id=own_site.id)
        other_worker = await seed_worker(session, company.id, "other-worker", site_id=other_site.id)

        with pytest.raises(CalendarAccessError, match="calendar_event_company_wide_denied"):
            await create_calendar_event(
                session,
                manager_worker=manager,
                event_type=CalendarEventType.PUBLIC_HOLIDAY,
                date_from=date(2026, 6, 1),
                date_to=date(2026, 6, 1),
            )
        with pytest.raises(CalendarAccessError, match="calendar_event_worker_scope_denied"):
            await create_calendar_event(
                session,
                manager_worker=manager,
                worker_id=other_worker.id,
                event_type=CalendarEventType.VACATION,
                date_from=date(2026, 6, 2),
                date_to=date(2026, 6, 2),
            )
        with pytest.raises(CalendarAccessError, match="calendar_event_site_scope_denied"):
            await create_calendar_event(
                session,
                manager_worker=manager,
                site_id=other_site.id,
                event_type=CalendarEventType.NON_WORKING_DAY,
                date_from=date(2026, 6, 3),
                date_to=date(2026, 6, 3),
            )

        allowed_worker_event = await create_calendar_event(
            session,
            manager_worker=manager,
            worker_id=own_worker.id,
            event_type=CalendarEventType.VACATION,
            date_from=date(2026, 6, 4),
            date_to=date(2026, 6, 4),
        )
        allowed_site_event = await create_calendar_event(
            session,
            manager_worker=manager,
            site_id=own_site.id,
            event_type=CalendarEventType.NON_WORKING_DAY,
            date_from=date(2026, 6, 5),
            date_to=date(2026, 6, 5),
        )

        visible_events = await list_company_calendar_events(session, manager_worker=manager)
        assert {event.id for event in visible_events} == {
            allowed_worker_event.id,
            allowed_site_event.id,
        }

    run_db_test(run_test)


def test_owner_calendar_denies_cross_company_worker_and_site_targets():
    async def run_test(session):
        company = await seed_company(session, "owner-calendar")
        other_company = await seed_company(session, "other-owner-calendar")
        owner = await seed_worker(
            session,
            company.id,
            "owner",
            can_view_dashboard=True,
            access_role=WorkerAccessRole.COMPANY_OWNER.value,
        )
        other_site = await seed_site(session, other_company.id, "other")
        other_worker = await seed_worker(session, other_company.id, "other-worker", site_id=other_site.id)

        with pytest.raises(CalendarAccessError, match="calendar_event_worker_scope_denied"):
            await create_calendar_event(
                session,
                manager_worker=owner,
                worker_id=other_worker.id,
                event_type=CalendarEventType.VACATION,
                date_from=date(2026, 6, 1),
                date_to=date(2026, 6, 1),
            )
        with pytest.raises(CalendarAccessError, match="calendar_event_site_scope_denied"):
            await create_calendar_event(
                session,
                manager_worker=owner,
                site_id=other_site.id,
                event_type=CalendarEventType.NON_WORKING_DAY,
                date_from=date(2026, 6, 2),
                date_to=date(2026, 6, 2),
            )

    run_db_test(run_test)
