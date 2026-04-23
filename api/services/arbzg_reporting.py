from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.arbzg_policy import evaluate_arbzg_flags
from db.models import EventType, TimeEvent, Worker


async def build_company_arbzg_day_report(
    db: AsyncSession,
    *,
    company_id: int,
    target_day: date,
    site_id: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    # This report is compliance support only. It surfaces patterns for review,
    # but it does not adjudicate ArbZG compliance or enforce legal outcomes.
    effective_now = now or datetime.now(timezone.utc)
    worker_stmt = (
        select(Worker)
        .where(
            Worker.company_id == company_id,
            Worker.is_active.is_(True),
            Worker.time_tracking_enabled.is_(True),
        )
        .order_by(Worker.id.asc())
    )
    if site_id is not None:
        worker_stmt = worker_stmt.where(Worker.site_id == site_id)
    workers = (await db.execute(worker_stmt)).scalars().all()
    worker_ids = [int(worker.id) for worker in workers]
    if not worker_ids:
        return {
            "company_id": company_id,
            "date": target_day.isoformat(),
            "summary_counts": {},
            "total_workers": 0,
            "flagged_workers": 0,
            "items": [],
        }

    events = (
        await db.execute(
            select(TimeEvent)
            .where(
                TimeEvent.worker_id.in_(worker_ids),
                func.date(TimeEvent.timestamp) == target_day,
            )
            .order_by(TimeEvent.worker_id.asc(), TimeEvent.timestamp.asc(), TimeEvent.id.asc())
        )
    ).scalars().all()
    events_by_worker: dict[int, list[TimeEvent]] = {}
    for event in events:
        events_by_worker.setdefault(int(event.worker_id), []).append(event)

    previous_checkout_rows = (
        await db.execute(
            select(TimeEvent.worker_id, func.max(TimeEvent.timestamp))
            .where(
                TimeEvent.worker_id.in_(worker_ids),
                TimeEvent.event_type == EventType.CHECKOUT,
                func.date(TimeEvent.timestamp) < target_day,
            )
            .group_by(TimeEvent.worker_id)
        )
    ).all()
    previous_checkout_by_worker = {
        int(worker_id): previous_checkout_at
        for worker_id, previous_checkout_at in previous_checkout_rows
    }

    summary_counts: Counter[str] = Counter()
    items: list[dict[str, Any]] = []
    for worker in workers:
        flags = evaluate_arbzg_flags(
            events_by_worker.get(int(worker.id), []),
            now=effective_now,
            previous_checkout_at=previous_checkout_by_worker.get(int(worker.id)),
        )
        for flag in flags:
            summary_counts.update([str(flag["code"])])
        items.append(
            {
                "worker_id": int(worker.id),
                "date": target_day.isoformat(),
                "flags": flags,
                "review_state": "unreviewed" if flags else "clean",
                "is_reviewed": False,
            }
        )

    return {
        "company_id": company_id,
        "date": target_day.isoformat(),
        "summary_counts": dict(summary_counts),
        "total_workers": len(workers),
        "flagged_workers": sum(1 for item in items if item["flags"]),
        "items": items,
    }
