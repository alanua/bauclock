from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from access.legacy_policy import can_manage_calendar, dashboard_access_role
from api.services.audit_logger import log_audit_event, model_snapshot
from db.models import EventType, Site, TimeEvent, Worker


class ManualTimeCorrectionError(Exception):
    pass


def _worker_in_actor_scope(actor_worker: Worker, target_worker: Worker) -> bool:
    role = dashboard_access_role(actor_worker)
    if actor_worker.company_id != target_worker.company_id:
        return False
    if role == "company_owner":
        return True
    if role == "objektmanager":
        if actor_worker.site_id is None:
            return target_worker.id == actor_worker.id
        return target_worker.site_id == actor_worker.site_id
    return False


async def apply_manual_time_correction(
    db: AsyncSession,
    *,
    actor_worker: Worker,
    event_id: int,
    reason: str,
    new_timestamp: datetime | None = None,
    new_event_type: EventType | str | None = None,
    new_site_id: int | None = None,
) -> TimeEvent:
    normalized_reason = (reason or "").strip()
    if not normalized_reason:
        raise ValueError("correction_reason_required")
    if not can_manage_calendar(actor_worker):
        raise ManualTimeCorrectionError("manual_time_correction_denied")

    event = await db.get(TimeEvent, event_id)
    if not event:
        raise ManualTimeCorrectionError("manual_time_event_not_found")

    target_worker = await db.get(Worker, event.worker_id)
    if not target_worker or not _worker_in_actor_scope(actor_worker, target_worker):
        raise ManualTimeCorrectionError("manual_time_scope_denied")

    old_snapshot = model_snapshot(
        event,
        "worker_id",
        "site_id",
        "event_type",
        "timestamp",
        "is_manual",
        "correction_reason",
        "corrected_by_worker_id",
        "corrected_at",
    )

    if new_event_type is not None:
        event.event_type = EventType(getattr(new_event_type, "value", new_event_type))
    if new_timestamp is not None:
        event.timestamp = new_timestamp
    if new_site_id is not None:
        site = await db.get(Site, new_site_id)
        if not site or site.company_id != actor_worker.company_id or not site.is_active:
            raise ManualTimeCorrectionError("manual_time_site_scope_denied")
        event.site_id = site.id

    now = datetime.now(timezone.utc)
    event.is_manual = True
    event.corrected_by_worker_id = actor_worker.id
    event.correction_reason = normalized_reason
    event.corrected_at = now
    db.add(event)
    await log_audit_event(
        db,
        entity_type="time_event",
        entity_id=event.id,
        action="manual_time_correction",
        old_value=old_snapshot,
        new_value=model_snapshot(
            event,
            "worker_id",
            "site_id",
            "event_type",
            "timestamp",
            "is_manual",
            "correction_reason",
            "corrected_by_worker_id",
            "corrected_at",
        ),
        performed_by_worker_id=actor_worker.id,
        company_id=actor_worker.company_id,
    )
    await db.commit()
    await db.refresh(event)
    return event
