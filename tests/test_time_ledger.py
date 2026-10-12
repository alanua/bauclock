from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from api.services.time_ledger import calculate_time_ledger


@dataclass
class Event:
    event_type: str
    timestamp: datetime


@dataclass
class ScopedEvent:
    company_id: str
    worker_id: str
    event_type: str
    timestamp: datetime


def t(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 1, 5, hour, minute, tzinfo=timezone.utc)


def test_normal_checkin_checkout() -> None:
    ledger = calculate_time_ledger(
        [Event("CHECKIN", t(8)), Event("CHECKOUT", t(17))],
        now=t(18),
    )

    assert ledger.work_minutes == 540
    assert ledger.break_minutes == 0
    assert ledger.status == "completed"
    assert not ledger.has_issues


def test_one_pause() -> None:
    ledger = calculate_time_ledger(
        [
            Event("CHECKIN", t(8)),
            Event("PAUSE_START", t(12)),
            Event("PAUSE_END", t(12, 30)),
            Event("CHECKOUT", t(17)),
        ],
        now=t(18),
    )

    assert ledger.work_minutes == 510
    assert ledger.break_minutes == 30
    assert [segment.kind for segment in ledger.segments] == ["work", "break", "work"]


def test_multiple_pauses() -> None:
    ledger = calculate_time_ledger(
        [
            Event("CHECKIN", t(8)),
            Event("PAUSE_START", t(10)),
            Event("PAUSE_END", t(10, 15)),
            Event("PAUSE_START", t(12)),
            Event("PAUSE_END", t(12, 30)),
            Event("CHECKOUT", t(16)),
        ],
        now=t(18),
    )

    assert ledger.work_minutes == 435
    assert ledger.break_minutes == 45


def test_checkout_while_paused_closes_break() -> None:
    ledger = calculate_time_ledger(
        [
            Event("CHECKIN", t(8)),
            Event("PAUSE_START", t(12)),
            Event("CHECKOUT", t(12, 30)),
        ],
        now=t(18),
    )

    assert ledger.work_minutes == 240
    assert ledger.break_minutes == 30
    assert ledger.status == "completed"


def test_missing_checkout_uses_supplied_now() -> None:
    ledger = calculate_time_ledger(
        [Event("CHECKIN", t(8)), Event("PAUSE_START", t(12))],
        now=t(12, 45),
    )

    assert ledger.work_minutes == 240
    assert ledger.break_minutes == 45
    assert ledger.status == "open_pause"


def test_invalid_sequence_returns_issue_in_strict_mode() -> None:
    ledger = calculate_time_ledger(
        [Event("PAUSE_END", t(8)), Event("CHECKOUT", t(9))],
        now=t(10),
    )

    assert ledger.work_minutes == 0
    assert ledger.break_minutes == 0
    assert ledger.has_issues
    assert [issue.code for issue in ledger.issues] == [
        "pause_end_without_pause",
        "checkout_without_open_day",
    ]


def test_replayed_duplicate_events_are_issues_without_extra_minutes() -> None:
    ledger = calculate_time_ledger(
        [
            Event("CHECKIN", t(8)),
            Event("CHECKIN", t(8)),
            Event("CHECKOUT", t(17)),
            Event("CHECKOUT", t(17)),
        ],
        now=t(18),
    )

    assert ledger.work_minutes == 540
    assert ledger.break_minutes == 0
    assert ledger.status == "completed"
    assert [issue.code for issue in ledger.issues] == [
        "duplicate_checkin",
        "checkout_without_open_day",
    ]
    assert [(segment.kind, segment.start, segment.end, segment.minutes) for segment in ledger.segments] == [
        ("work", t(8), t(17), 540),
    ]


def test_mixed_scoped_stream_is_flagged_without_counting_multiple_workers() -> None:
    mixed_ledger = calculate_time_ledger(
        [
            ScopedEvent("company-a", "worker-a", "CHECKIN", t(8)),
            ScopedEvent("company-b", "worker-b", "CHECKIN", t(8, 5)),
            ScopedEvent("company-a", "worker-a", "CHECKOUT", t(12)),
            ScopedEvent("company-b", "worker-b", "CHECKOUT", t(12, 5)),
        ],
        now=t(13),
    )
    worker_a_ledger = calculate_time_ledger(
        [
            ScopedEvent("company-a", "worker-a", "CHECKIN", t(8)),
            ScopedEvent("company-a", "worker-a", "CHECKOUT", t(12)),
        ],
        now=t(13),
    )
    worker_b_ledger = calculate_time_ledger(
        [
            ScopedEvent("company-b", "worker-b", "CHECKIN", t(8, 5)),
            ScopedEvent("company-b", "worker-b", "CHECKOUT", t(12, 5)),
        ],
        now=t(13),
    )

    assert worker_a_ledger.work_minutes == 240
    assert worker_b_ledger.work_minutes == 240
    assert not worker_a_ledger.has_issues
    assert not worker_b_ledger.has_issues
    assert mixed_ledger.work_minutes == worker_a_ledger.work_minutes
    assert mixed_ledger.work_minutes != worker_a_ledger.work_minutes + worker_b_ledger.work_minutes
    assert [issue.code for issue in mixed_ledger.issues] == [
        "duplicate_checkin",
        "checkout_without_open_day",
    ]
