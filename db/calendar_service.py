from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Sequence

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from access.legacy_policy import can_view_admin_features
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
    if not can_view_admin_features(manager_worker):
        raise CalendarAccessError("calendar_event_create_denied")
    if worker_id is not None and site_id is not None:
        raise ValueError("calendar_event_scope_ambiguous")

    _validate_date_range(date_from, date_to)

    if worker_id is not None:
        worker = await db.get(Worker, worker_id)
        if not worker or worker.company_id != manager_worker.company_id:
            raise CalendarAccessError("calendar_event_worker_scope_denied")

    if site_id is not None:
        site = await db.get(Site, site_id)
        if not site or site.company_id != manager_worker.company_id:
            raise CalendarAccessError("calendar_event_site_scope_denied")

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
    if not can_view_admin_features(manager_worker):
        raise CalendarAccessError("company_calendar_events_denied")

    stmt = select(CalendarEvent).where(CalendarEvent.company_id == manager_worker.company_id)
    if active_only:
        stmt = stmt.where(CalendarEvent.is_active.is_(True))
    result = await db.execute(stmt.order_by(CalendarEvent.date_from.desc(), CalendarEvent.id.desc()))
    return result.scalars().all()


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
    if not can_view_admin_features(manager_worker):
        raise CalendarAccessError("calendar_event_deactivate_denied")

    calendar_event = await db.get(CalendarEvent, event_id)
    if not calendar_event or calendar_event.company_id != manager_worker.company_id:
        raise CalendarAccessError("calendar_event_not_found")

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
