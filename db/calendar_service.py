from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Sequence

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from access.legacy_policy import can_manage_calendar, dashboard_access_role, visible_site_id
from db.models import CalendarEvent, CalendarEventType, Site, Worker


class CalendarAccessError(Exception):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_event_type(event_type: CalendarEventType | str) -> str:
    return CalendarEventType(event_type).value


def _validate_date_range(date_from: date, date_to: date) -> None:
    if date_to < date_from:
        raise ValueError("calendar_event_date_range_invalid")


def _worker_visible_to_manager(manager_worker: Worker, scoped_worker: Worker | None) -> bool:
    if not scoped_worker or scoped_worker.company_id != manager_worker.company_id:
        return False
    access_role = dashboard_access_role(manager_worker)
    if access_role == "company_owner":
        return True
    if access_role == "objektmanager":
        site_id = visible_site_id(manager_worker)
        if site_id is None:
            return scoped_worker.id == manager_worker.id
        return scoped_worker.site_id == site_id
    return False


def _site_visible_to_manager(manager_worker: Worker, scoped_site: Site | None) -> bool:
    if not scoped_site or scoped_site.company_id != manager_worker.company_id:
        return False
    access_role = dashboard_access_role(manager_worker)
    if access_role == "company_owner":
        return True
    if access_role == "objektmanager":
        site_id = visible_site_id(manager_worker)
        return site_id is not None and scoped_site.id == site_id
    return False


async def create_calendar_event(
    db: AsyncSession,
    *,
    manager_worker: Worker,
    event_type: CalendarEventType | str,
    date_from: date,
    date_to: date,
    worker_id: int | None = None,
    site_id: int | None = None,
    comment: str | None = None,
) -> CalendarEvent:
    if not can_manage_calendar(manager_worker):
        raise CalendarAccessError("calendar_event_create_denied")
    if worker_id is not None and site_id is not None:
        raise ValueError("calendar_event_scope_ambiguous")

    _validate_date_range(date_from, date_to)

    if worker_id is not None:
        worker = await db.get(Worker, worker_id)
        if not _worker_visible_to_manager(manager_worker, worker):
            raise CalendarAccessError("calendar_event_worker_scope_denied")

    if site_id is not None:
        site = await db.get(Site, site_id)
        if not _site_visible_to_manager(manager_worker, site):
            raise CalendarAccessError("calendar_event_site_scope_denied")

    if dashboard_access_role(manager_worker) == "objektmanager" and worker_id is None and site_id is None:
        raise CalendarAccessError("calendar_event_company_wide_denied")

    calendar_event = CalendarEvent(
        company_id=manager_worker.company_id,
        worker_id=worker_id,
        site_id=site_id,
        event_type=_normalize_event_type(event_type),
        date_from=date_from,
        date_to=date_to,
        comment=(comment or "").strip() or None,
        is_active=True,
        created_by_worker_id=manager_worker.id,
    )
    db.add(calendar_event)
    await db.commit()
    await db.refresh(calendar_event)
    return calendar_event


async def list_company_calendar_events(
    db: AsyncSession,
    *,
    manager_worker: Worker,
    active_only: bool = True,
) -> Sequence[CalendarEvent]:
    if not can_manage_calendar(manager_worker):
        raise CalendarAccessError("company_calendar_events_denied")

    stmt = select(CalendarEvent).where(CalendarEvent.company_id == manager_worker.company_id)
    if active_only:
        stmt = stmt.where(CalendarEvent.is_active.is_(True))
    result = await db.execute(stmt.order_by(CalendarEvent.date_from.desc(), CalendarEvent.id.desc()))
    events = result.scalars().all()
    if dashboard_access_role(manager_worker) != "objektmanager":
        return events
    return [
        event
        for event in events
        if (
            (event.worker_id is not None and _worker_visible_to_manager(manager_worker, await db.get(Worker, event.worker_id)))
            or (event.site_id is not None and _site_visible_to_manager(manager_worker, await db.get(Site, event.site_id)))
        )
    ]


async def list_worker_calendar_events(
    db: AsyncSession,
    *,
    worker: Worker,
    active_only: bool = True,
) -> Sequence[CalendarEvent]:
    stmt = select(CalendarEvent).where(
        CalendarEvent.company_id == worker.company_id,
        _worker_relevant_calendar_filter(worker),
    )
    if active_only:
        stmt = stmt.where(CalendarEvent.is_active.is_(True))
    result = await db.execute(stmt.order_by(CalendarEvent.date_from.desc(), CalendarEvent.id.desc()))
    return result.scalars().all()


async def get_events_for_worker_on_date(
    db: AsyncSession,
    *,
    worker: Worker,
    target_date: date,
    active_only: bool = True,
) -> Sequence[CalendarEvent]:
    stmt = select(CalendarEvent).where(
        CalendarEvent.company_id == worker.company_id,
        CalendarEvent.date_from <= target_date,
        CalendarEvent.date_to >= target_date,
        _worker_relevant_calendar_filter(worker),
    )
    if active_only:
        stmt = stmt.where(CalendarEvent.is_active.is_(True))
    result = await db.execute(stmt.order_by(CalendarEvent.date_from.desc(), CalendarEvent.id.desc()))
    return result.scalars().all()


async def deactivate_calendar_event(
    db: AsyncSession,
    *,
    event_id: int,
    manager_worker: Worker,
) -> CalendarEvent:
    if not can_manage_calendar(manager_worker):
        raise CalendarAccessError("calendar_event_deactivate_denied")

    calendar_event = await db.get(CalendarEvent, event_id)
    if not calendar_event or calendar_event.company_id != manager_worker.company_id:
        raise CalendarAccessError("calendar_event_not_found")
    if dashboard_access_role(manager_worker) == "objektmanager":
        worker = await db.get(Worker, calendar_event.worker_id) if calendar_event.worker_id else None
        site = await db.get(Site, calendar_event.site_id) if calendar_event.site_id else None
        if not _worker_visible_to_manager(manager_worker, worker) and not _site_visible_to_manager(manager_worker, site):
            raise CalendarAccessError("calendar_event_scope_denied")

    calendar_event.is_active = False
    calendar_event.updated_at = _utcnow()
    db.add(calendar_event)
    await db.commit()
    await db.refresh(calendar_event)
    return calendar_event


def _worker_relevant_calendar_filter(worker: Worker):
    scope_filters = [
        CalendarEvent.worker_id == worker.id,
        and_(CalendarEvent.worker_id.is_(None), CalendarEvent.site_id.is_(None)),
    ]
    if worker.site_id is not None:
        scope_filters.append(CalendarEvent.site_id == worker.site_id)

    return or_(*scope_filters)
