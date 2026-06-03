from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


CHECKIN = "CHECKIN"
PAUSE_START = "PAUSE_START"
PAUSE_END = "PAUSE_END"
CHECKOUT = "CHECKOUT"


@dataclass(frozen=True)
class TimeLedgerSegment:
    kind: str
    start: datetime
    end: datetime
    minutes: int


@dataclass(frozen=True)
class TimeLedgerIssue:
    code: str
    message: str
    event_type: str | None = None
    timestamp: datetime | None = None


@dataclass(frozen=True)
class TimeLedger:
    work_minutes: int
    break_minutes: int
    status: str
    segments: tuple[TimeLedgerSegment, ...] = field(default_factory=tuple)
    issues: tuple[TimeLedgerIssue, ...] = field(default_factory=tuple)

    @property
    def has_issues(self) -> bool:
        return bool(self.issues)


def _event_type_value(event_type: Any) -> str:
    return str(getattr(event_type, "value", event_type))


def _event_timestamp(event: Any) -> datetime:
    return getattr(event, "timestamp")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _minutes_between(start: datetime | None, end: datetime | None) -> int:
    if start is None or end is None:
        return 0
    return max(int((_as_utc(end) - _as_utc(start)).total_seconds() // 60), 0)


def _segment(kind: str, start: datetime | None, end: datetime | None) -> TimeLedgerSegment | None:
    minutes = _minutes_between(start, end)
    if start is None or end is None or minutes <= 0:
        return None
    return TimeLedgerSegment(kind=kind, start=start, end=end, minutes=minutes)


def calculate_time_ledger(
    events: list[Any],
    *,
    now: datetime,
    strict: bool = True,
) -> TimeLedger:
    """Calculate canonical work/break minutes from ordered TimeEvent-like objects.

    The service is pure and deterministic. It accepts ORM TimeEvent rows or any
    object with `event_type` and `timestamp` attributes, but it intentionally does
    not import ORM models.
    """

    work_minutes = 0
    break_minutes = 0
    active_start: datetime | None = None
    pause_start: datetime | None = None
    segments: list[TimeLedgerSegment] = []
    issues: list[TimeLedgerIssue] = []

    def add_issue(code: str, message: str, event_type: str | None, timestamp: datetime | None) -> None:
        issues.append(TimeLedgerIssue(code=code, message=message, event_type=event_type, timestamp=timestamp))

    for event in events:
        event_type = _event_type_value(getattr(event, "event_type"))
        timestamp = _event_timestamp(event)

        if event_type == CHECKIN:
            if active_start is not None or pause_start is not None:
                add_issue("duplicate_checkin", "CHECKIN received while a day is already open", event_type, timestamp)
                if strict:
                    continue
            active_start = timestamp
            pause_start = None

        elif event_type == PAUSE_START:
            if active_start is None:
                add_issue("pause_start_without_checkin", "PAUSE_START received without active work", event_type, timestamp)
                if strict:
                    continue
            segment = _segment("work", active_start, timestamp)
            if segment is not None:
                segments.append(segment)
                work_minutes += segment.minutes
            active_start = None
            pause_start = timestamp

        elif event_type == PAUSE_END:
            if pause_start is None:
                add_issue("pause_end_without_pause", "PAUSE_END received without active pause", event_type, timestamp)
                if strict:
                    continue
            segment = _segment("break", pause_start, timestamp)
            if segment is not None:
                segments.append(segment)
                break_minutes += segment.minutes
            pause_start = None
            active_start = timestamp

        elif event_type == CHECKOUT:
            if active_start is None and pause_start is None:
                add_issue("checkout_without_open_day", "CHECKOUT received without active work or pause", event_type, timestamp)
                if strict:
                    continue
            work_segment = _segment("work", active_start, timestamp)
            if work_segment is not None:
                segments.append(work_segment)
                work_minutes += work_segment.minutes
            break_segment = _segment("break", pause_start, timestamp)
            if break_segment is not None:
                segments.append(break_segment)
                break_minutes += break_segment.minutes
            active_start = None
            pause_start = None

        else:
            add_issue("unknown_event_type", "Unknown time event type", str(event_type), timestamp)
            if strict:
                continue

    if active_start is not None:
        segment = _segment("work", active_start, now)
        if segment is not None:
            segments.append(segment)
            work_minutes += segment.minutes
    if pause_start is not None:
        segment = _segment("break", pause_start, now)
        if segment is not None:
            segments.append(segment)
            break_minutes += segment.minutes

    if active_start is None and pause_start is None:
        status = "completed"
    elif pause_start is not None:
        status = "open_pause"
    else:
        status = "open_work"

    return TimeLedger(
        work_minutes=work_minutes,
        break_minutes=break_minutes,
        status=status,
        segments=tuple(segments),
        issues=tuple(issues),
    )
