from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.arbzg_policy import evaluate_arbzg_flags
from api.services.arbzg_reviews import load_arbzg_finding_map
from db.models import EventType, TimeEvent, Worker


def _review_summary_state(states: list[str]) -> tuple[str, bool]:
    if not states:
        return "clean", False
    unique_states = set(states)
    if unique_states == {"open"}:
        return "open", False
    if "open" in unique_states:
        return "open", False
    if len(unique_states) == 1:
        state = next(iter(unique_states))
        return state, True
    return "mixed", True


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
            "review_state_counts": {},
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

    finding_map = await load_arbzg_finding_map(
        db,
        company_id=company_id,
        target_date=target_day,
        worker_ids=worker_ids,
    )
    summary_counts: Counter[str] = Counter()
    review_state_counts: Counter[str] = Counter()
    items: list[dict[str, Any]] = []
    for worker in workers:
        raw_flags = evaluate_arbzg_flags(
            events_by_worker.get(int(worker.id), []),
            now=effective_now,
            previous_checkout_at=previous_checkout_by_worker.get(int(worker.id)),
        )
        serialized_flags: list[dict[str, Any]] = []
        for flag in raw_flags:
            finding = finding_map.get((int(worker.id), str(flag["code"])))
            review_state = str(finding["state"]) if finding is not None else "open"
            serialized_flags.append(
                {
                    **flag,
                    "finding_id": finding["id"] if finding is not None else None,
                    "review_state": review_state,
                    "review_reason": finding["state_reason"] if finding is not None else None,
                }
            )
            summary_counts.update([str(flag["code"])])

        item_review_state, is_reviewed = _review_summary_state(
            [str(flag["review_state"]) for flag in serialized_flags]
        )
        review_state_counts.update([item_review_state])
        items.append(
            {
                "worker_id": int(worker.id),
                "date": target_day.isoformat(),
                "flags": serialized_flags,
                "review_state": item_review_state,
                "is_reviewed": is_reviewed,
            }
        )

    return {
        "company_id": company_id,
        "date": target_day.isoformat(),
        "summary_counts": dict(summary_counts),
        "review_state_counts": dict(review_state_counts),
        "total_workers": len(workers),
        "flagged_workers": sum(1 for item in items if item["flags"]),
        "items": items,
    }
