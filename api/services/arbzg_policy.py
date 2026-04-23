from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import EventType, TimeEvent


def _event_type_value(event_type: Any) -> str:
    return getattr(event_type, "value", event_type)


def _minutes_between(start: datetime | None, end: datetime | None) -> int:
    if not start or not end:
        return 0
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return max(int((end - start).total_seconds() // 60), 0)


def calculate_day_work_break_minutes(
    events: list[TimeEvent],
    *,
    now: datetime,
) -> tuple[int, int]:
    work_minutes = 0
    break_minutes = 0
    active_start: datetime | None = None
    pause_start: datetime | None = None

    for event in events:
        event_type = _event_type_value(event.event_type)
        timestamp = event.timestamp
        if event_type == EventType.CHECKIN.value:
            active_start = timestamp
            pause_start = None
        elif event_type == EventType.PAUSE_START.value:
            work_minutes += _minutes_between(active_start, timestamp)
            active_start = None
            pause_start = timestamp
        elif event_type == EventType.PAUSE_END.value:
            break_minutes += _minutes_between(pause_start, timestamp)
            pause_start = None
            active_start = timestamp
        elif event_type == EventType.CHECKOUT.value:
            work_minutes += _minutes_between(active_start, timestamp)
            break_minutes += _minutes_between(pause_start, timestamp)
            active_start = None
            pause_start = None

    work_minutes += _minutes_between(active_start, now)
    break_minutes += _minutes_between(pause_start, now)
    return work_minutes, break_minutes


def evaluate_arbzg_flags(
    events: list[TimeEvent],
    *,
    now: datetime,
    previous_checkout_at: datetime | None = None,
) -> list[dict[str, object]]:
    if not events:
        return []

    work_minutes, break_minutes = calculate_day_work_break_minutes(events, now=now)
    flags: list[dict[str, object]] = []

    if work_minutes > 360 and break_minutes < 30:
        flags.append(
            {
                "code": "break_reminder_after_6h",
                "severity": "warning",
                "label": "Pause nach mehr als 6h pruefen",
            }
        )
    if work_minutes > 540 and break_minutes < 45:
        flags.append(
            {
                "code": "break_reminder_after_9h",
                "severity": "critical",
                "label": "Pause nach mehr als 9h unzureichend",
            }
        )
    if work_minutes >= 570:
        flags.append(
            {
                "code": "daily_duration_warning",
                "severity": "warning" if work_minutes < 600 else "critical",
                "label": "Tagesarbeitszeit nahe oder ueber 10h",
            }
        )

    first_checkin = next(
        (
            event.timestamp
            for event in events
            if _event_type_value(event.event_type) == EventType.CHECKIN.value
        ),
        None,
    )
    if previous_checkout_at and first_checkin and _minutes_between(previous_checkout_at, first_checkin) < 11 * 60:
        flags.append(
            {
                "code": "rest_period_warning",
                "severity": "warning",
                "label": "Ruhezeit unter 11h moeglich",
            }
        )

    return flags


async def get_worker_arbzg_flags(
    db: AsyncSession,
    *,
    worker_id: int,
    target_day: date,
    now: datetime | None = None,
) -> list[dict[str, object]]:
    effective_now = now or datetime.now(timezone.utc)
    events = (
        await db.execute(
            select(TimeEvent)
            .where(
                TimeEvent.worker_id == worker_id,
                func.date(TimeEvent.timestamp) == target_day,
            )
            .order_by(TimeEvent.timestamp.asc(), TimeEvent.id.asc())
        )
    ).scalars().all()
    previous_checkout_at = await db.scalar(
        select(TimeEvent.timestamp)
        .where(
            TimeEvent.worker_id == worker_id,
            TimeEvent.event_type == EventType.CHECKOUT,
            func.date(TimeEvent.timestamp) < target_day,
        )
        .order_by(TimeEvent.timestamp.desc(), TimeEvent.id.desc())
        .limit(1)
    )
    return evaluate_arbzg_flags(
        list(events),
        now=effective_now,
        previous_checkout_at=previous_checkout_at,
    )
