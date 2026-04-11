import asyncio
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.calendar_service import (
    create_calendar_event,
    deactivate_calendar_event,
    get_events_for_worker_on_date,
    list_worker_calendar_events,
)
from db.models import (
    Base,
    BillingType,
    CalendarEventType,
    Company,
    Site,
    Worker,
    WorkerType,
)


def run_db_test(test_coro):
    async def runner():
        with TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "calendar.db"
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
        is_active=True,
    )
    session.add(worker)
    await session.flush()
    return worker


def test_create_worker_vacation_event():
    async def run_test(session):
        company = await seed_company(session, "vacation")
        manager = await seed_worker(
            session,
            company.id,
            "manager",
            can_view_dashboard=True,
        )
        worker = await seed_worker(session, company.id, "worker")

        event = await create_calendar_event(
            session,
            manager_worker=manager,
            worker_id=worker.id,
            event_type=CalendarEventType.VACATION,
            date_from=date(2026, 5, 4),
            date_to=date(2026, 5, 8),
            comment="Approved vacation",
        )

        assert event.company_id == company.id
        assert event.worker_id == worker.id
        assert event.site_id is None
        assert event.event_type == CalendarEventType.VACATION.value
        assert event.date_from == date(2026, 5, 4)
        assert event.date_to == date(2026, 5, 8)
        assert event.comment == "Approved vacation"
        assert event.is_active is True
        assert event.created_by_worker_id == manager.id

    run_db_test(run_test)


def test_create_company_wide_public_holiday_event():
    async def run_test(session):
        company = await seed_company(session, "holiday")
        manager = await seed_worker(
            session,
            company.id,
            "manager",
            can_view_dashboard=True,
        )

        event = await create_calendar_event(
            session,
            manager_worker=manager,
            event_type="public_holiday",
            date_from=date(2026, 5, 1),
            date_to=date(2026, 5, 1),
        )

        assert event.company_id == company.id
        assert event.worker_id is None
        assert event.site_id is None
        assert event.event_type == CalendarEventType.PUBLIC_HOLIDAY.value
        assert event.is_active is True

    run_db_test(run_test)


def test_list_worker_relevant_events():
    async def run_test(session):
        company = await seed_company(session, "worker-list")
        other_company = await seed_company(session, "other-company")
        site = await seed_site(session, company.id, "site")
        other_site = await seed_site(session, company.id, "other-site")
        manager = await seed_worker(
            session,
            company.id,
            "manager",
            can_view_dashboard=True,
        )
        worker = await seed_worker(session, company.id, "worker", site_id=site.id)
        other_worker = await seed_worker(session, company.id, "other-worker")
        other_company_manager = await seed_worker(
            session,
            other_company.id,
            "other-company-manager",
            can_view_dashboard=True,
        )

        worker_event = await create_calendar_event(
            session,
            manager_worker=manager,
            worker_id=worker.id,
            event_type=CalendarEventType.VACATION,
            date_from=date(2026, 5, 4),
            date_to=date(2026, 5, 8),
        )
        company_event = await create_calendar_event(
            session,
            manager_worker=manager,
            event_type=CalendarEventType.PUBLIC_HOLIDAY,
            date_from=date(2026, 5, 1),
            date_to=date(2026, 5, 1),
        )
        site_event = await create_calendar_event(
            session,
            manager_worker=manager,
            site_id=site.id,
            event_type=CalendarEventType.NON_WORKING_DAY,
            date_from=date(2026, 5, 15),
            date_to=date(2026, 5, 15),
        )
        await create_calendar_event(
            session,
            manager_worker=manager,
            worker_id=other_worker.id,
            event_type=CalendarEventType.SICK_LEAVE,
            date_from=date(2026, 5, 6),
            date_to=date(2026, 5, 6),
        )
        await create_calendar_event(
            session,
            manager_worker=manager,
            site_id=other_site.id,
            event_type=CalendarEventType.NON_WORKING_DAY,
            date_from=date(2026, 5, 16),
            date_to=date(2026, 5, 16),
        )
        await create_calendar_event(
            session,
            manager_worker=other_company_manager,
            event_type=CalendarEventType.PUBLIC_HOLIDAY,
            date_from=date(2026, 5, 1),
            date_to=date(2026, 5, 1),
        )

        events = await list_worker_calendar_events(session, worker=worker)

        assert {event.id for event in events} == {
            worker_event.id,
            company_event.id,
            site_event.id,
        }

    run_db_test(run_test)


def test_deactivate_calendar_event():
    async def run_test(session):
        company = await seed_company(session, "deactivate")
        manager = await seed_worker(
            session,
            company.id,
            "manager",
            can_view_dashboard=True,
        )
        event = await create_calendar_event(
            session,
            manager_worker=manager,
            event_type=CalendarEventType.PUBLIC_HOLIDAY,
            date_from=date(2026, 5, 1),
            date_to=date(2026, 5, 1),
        )

        deactivated = await deactivate_calendar_event(
            session,
            event_id=event.id,
            manager_worker=manager,
        )

        assert deactivated.is_active is False
        assert deactivated.updated_at is not None

    run_db_test(run_test)


def test_get_events_for_worker_on_date():
    async def run_test(session):
        company = await seed_company(session, "on-date")
        site = await seed_site(session, company.id, "site")
        manager = await seed_worker(
            session,
            company.id,
            "manager",
            can_view_dashboard=True,
        )
        worker = await seed_worker(session, company.id, "worker", site_id=site.id)

        vacation = await create_calendar_event(
            session,
            manager_worker=manager,
            worker_id=worker.id,
            event_type=CalendarEventType.VACATION,
            date_from=date(2026, 5, 4),
            date_to=date(2026, 5, 8),
        )
        public_holiday = await create_calendar_event(
            session,
            manager_worker=manager,
            event_type=CalendarEventType.PUBLIC_HOLIDAY,
            date_from=date(2026, 5, 6),
            date_to=date(2026, 5, 6),
        )
        site_event = await create_calendar_event(
            session,
            manager_worker=manager,
            site_id=site.id,
            event_type=CalendarEventType.NON_WORKING_DAY,
            date_from=date(2026, 5, 6),
            date_to=date(2026, 5, 6),
        )
        out_of_range = await create_calendar_event(
            session,
            manager_worker=manager,
            worker_id=worker.id,
            event_type=CalendarEventType.SICK_LEAVE,
            date_from=date(2026, 5, 10),
            date_to=date(2026, 5, 10),
        )
        inactive = await create_calendar_event(
            session,
            manager_worker=manager,
            worker_id=worker.id,
            event_type=CalendarEventType.SICK_LEAVE,
            date_from=date(2026, 5, 6),
            date_to=date(2026, 5, 6),
        )
        await deactivate_calendar_event(
            session,
            event_id=inactive.id,
            manager_worker=manager,
        )

        events = await get_events_for_worker_on_date(
            session,
            worker=worker,
            target_date=date(2026, 5, 6),
        )

        assert {event.id for event in events} == {
            vacation.id,
            public_holiday.id,
            site_event.id,
        }
        assert out_of_range.id not in {event.id for event in events}
        assert inactive.id not in {event.id for event in events}

    run_db_test(run_test)
