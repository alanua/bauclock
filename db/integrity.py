from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    EmploymentStatus,
    EmploymentType,
    EventType,
    Site,
    SitePartnerCompany,
    TimeEvent,
    Worker,
    WorkerAccessRole,
    WorkerType,
)


class DataTrustError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


ACTIVE_EMPLOYMENT_STATUSES = {
    EmploymentStatus.ACTIVE.value,
    EmploymentStatus.TRIAL_ACTIVE.value,
    EmploymentStatus.CONVERTED.value,
}

HIRED_WORKER_TYPES = {
    WorkerType.FESTANGESTELLT.value,
    WorkerType.MINIJOB.value,
}

HIRED_EMPLOYMENT_TYPES = {
    EmploymentType.EMPLOYEE_FULL_TIME.value,
    EmploymentType.EMPLOYEE_PART_TIME.value,
    EmploymentType.MINIJOB.value,
    EmploymentType.TEMPORARY.value,
    EmploymentType.TRIAL_PERIOD.value,
}

ALLOWED_NEXT_EVENTS = {
    None: {EventType.CHECKIN},
    EventType.CHECKIN: {EventType.PAUSE_START, EventType.CHECKOUT},
    EventType.PAUSE_START: {EventType.PAUSE_END, EventType.CHECKOUT},
    EventType.PAUSE_END: {EventType.PAUSE_START, EventType.CHECKOUT},
    EventType.CHECKOUT: set(),
}


def enum_value(value) -> str | None:
    return getattr(value, "value", value)


def is_hired_membership(
    *,
    worker_type: str | WorkerType | None,
    employment_type: str | None,
    access_role: str | None,
) -> bool:
    if access_role == WorkerAccessRole.COMPANY_OWNER.value:
        return False
    return enum_value(worker_type) in HIRED_WORKER_TYPES or employment_type in HIRED_EMPLOYMENT_TYPES


def worker_is_active_hired(worker: Worker) -> bool:
    return bool(
        worker
        and worker.is_active
        and worker.employment_status in ACTIVE_EMPLOYMENT_STATUSES
        and is_hired_membership(
            worker_type=worker.worker_type,
            employment_type=worker.employment_type,
            access_role=worker.access_role,
        )
    )


async def find_active_hired_membership(
    session: AsyncSession,
    *,
    telegram_id_hash: str,
    exclude_company_id: int | None = None,
    exclude_worker_id: int | None = None,
) -> Worker | None:
    stmt = select(Worker).where(
        Worker.telegram_id_hash == telegram_id_hash,
        Worker.is_active.is_(True),
        Worker.employment_status.in_(ACTIVE_EMPLOYMENT_STATUSES),
        Worker.access_role != WorkerAccessRole.COMPANY_OWNER.value,
        or_(
            Worker.worker_type.in_([WorkerType.FESTANGESTELLT, WorkerType.MINIJOB]),
            Worker.employment_type.in_(HIRED_EMPLOYMENT_TYPES),
        ),
    )
    if exclude_company_id is not None:
        stmt = stmt.where(Worker.company_id != exclude_company_id)
    if exclude_worker_id is not None:
        stmt = stmt.where(Worker.id != exclude_worker_id)
    return await session.scalar(stmt.order_by(Worker.id))


async def company_can_use_site(
    session: AsyncSession,
    *,
    company_id: int,
    site_id: int,
) -> bool:
    site = await session.scalar(
        select(Site).where(Site.id == site_id, Site.is_active.is_(True))
    )
    if not site:
        return False
    if site.company_id == company_id:
        return True
    partnership = await session.scalar(
        select(SitePartnerCompany.id).where(
            SitePartnerCompany.site_id == site_id,
            SitePartnerCompany.company_id == company_id,
            SitePartnerCompany.is_active.is_(True),
        )
    )
    return bool(partnership)


async def validate_worker_site_context(
    session: AsyncSession,
    *,
    worker: Worker,
    site: Site | None,
) -> None:
    if not worker or not worker.is_active:
        raise DataTrustError("worker_inactive")
    if not site or not site.is_active:
        raise DataTrustError("site_not_available")
    if not await company_can_use_site(session, company_id=worker.company_id, site_id=site.id):
        raise DataTrustError("site_not_allowed")


async def last_time_event_for_day(
    session: AsyncSession,
    *,
    worker_id: int,
    target_date: date,
) -> TimeEvent | None:
    return await session.scalar(
        select(TimeEvent)
        .where(
            TimeEvent.worker_id == worker_id,
            func.date(TimeEvent.timestamp) == target_date,
        )
        .order_by(TimeEvent.timestamp.desc(), TimeEvent.id.desc())
    )


def is_valid_next_time_event(
    last_event_type: EventType | str | None,
    next_event_type: EventType,
) -> bool:
    normalized_last = EventType(enum_value(last_event_type)) if last_event_type else None
    return next_event_type in ALLOWED_NEXT_EVENTS.get(normalized_last, set())


async def validate_time_event_context(
    session: AsyncSession,
    *,
    worker: Worker,
    site: Site | None,
    next_event_type: EventType,
    target_date: date | None = None,
) -> None:
    await validate_worker_site_context(session, worker=worker, site=site)
    if not worker.time_tracking_enabled:
        raise DataTrustError("time_tracking_disabled")

    current_date = target_date or datetime.now(timezone.utc).date()
    last_event = await last_time_event_for_day(
        session,
        worker_id=worker.id,
        target_date=current_date,
    )
    last_event_type = last_event.event_type if last_event else None
    if not is_valid_next_time_event(last_event_type, next_event_type):
        raise DataTrustError("invalid_time_sequence")
