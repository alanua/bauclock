from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.audit_logger import log_audit_event, model_snapshot
from db.models import MonthlyAdjustment, Payment, Worker


_UNSET = object()


def _changed_fields(entity: Any, updates: dict[str, Any]) -> list[str]:
    changed: list[str] = []
    for field, value in updates.items():
        if value is _UNSET:
            continue
        if getattr(entity, field) != value:
            changed.append(field)
    return changed


async def apply_audited_worker_update(
    db: AsyncSession,
    *,
    worker: Worker,
    action: str,
    performed_by_worker_id: int | None,
    company_id: int | None,
    access_role: str | object = _UNSET,
    can_view_dashboard: bool | object = _UNSET,
    site_id: int | None | object = _UNSET,
    hourly_rate: float | None | object = _UNSET,
    contract_hours_week: int | None | object = _UNSET,
) -> bool:
    updates = {
        "access_role": access_role,
        "can_view_dashboard": can_view_dashboard,
        "site_id": site_id,
        "hourly_rate": hourly_rate,
        "contract_hours_week": contract_hours_week,
    }
    changed_fields = _changed_fields(worker, updates)
    if not changed_fields:
        return False

    old_value = model_snapshot(worker, *changed_fields)
    for field in changed_fields:
        setattr(worker, field, updates[field])
    db.add(worker)
    await log_audit_event(
        db,
        entity_type="worker",
        entity_id=worker.id,
        action=action,
        old_value=old_value,
        new_value=model_snapshot(worker, *changed_fields),
        performed_by_worker_id=performed_by_worker_id,
        company_id=company_id,
    )
    return True


async def apply_audited_payment_update(
    db: AsyncSession,
    *,
    payment: Payment,
    performed_by_worker_id: int | None,
    company_id: int | None,
    status: object = _UNSET,
    amount_paid: object = _UNSET,
    period_start: object = _UNSET,
    period_end: object = _UNSET,
    confirmed_at: object = _UNSET,
) -> bool:
    updates = {
        "status": status,
        "amount_paid": amount_paid,
        "period_start": period_start,
        "period_end": period_end,
        "confirmed_at": confirmed_at,
    }
    changed_fields = _changed_fields(payment, updates)
    if not changed_fields:
        return False

    if "status" in changed_fields:
        action = "payment_status_updated"
    elif {"amount_paid", "period_start", "period_end"} & set(changed_fields):
        action = "payment_amount_date_updated"
    else:
        action = "payment_updated"

    old_value = model_snapshot(payment, *changed_fields)
    for field in changed_fields:
        setattr(payment, field, updates[field])
    db.add(payment)
    await log_audit_event(
        db,
        entity_type="payment",
        entity_id=payment.id,
        action=action,
        old_value=old_value,
        new_value=model_snapshot(payment, *changed_fields),
        performed_by_worker_id=performed_by_worker_id,
        company_id=company_id,
    )
    return True


async def upsert_monthly_adjustment(
    db: AsyncSession,
    *,
    worker_id: int,
    month: date,
    adjustment_minutes: int,
    reason: str | None,
    performed_by_worker_id: int | None,
    company_id: int | None,
) -> MonthlyAdjustment:
    adjustment = await db.scalar(
        select(MonthlyAdjustment)
        .where(
            MonthlyAdjustment.worker_id == worker_id,
            MonthlyAdjustment.month == month,
        )
        .order_by(MonthlyAdjustment.id.desc())
        .limit(1)
    )

    normalized_reason = (reason or "").strip() or None
    if adjustment is None:
        adjustment = MonthlyAdjustment(
            worker_id=worker_id,
            month=month,
            adjustment_minutes=adjustment_minutes,
            reason=normalized_reason,
            created_by=performed_by_worker_id,
        )
        db.add(adjustment)
        await db.flush()
        await log_audit_event(
            db,
            entity_type="monthly_adjustment",
            entity_id=adjustment.id,
            action="monthly_adjustment_created",
            old_value=None,
            new_value=model_snapshot(
                adjustment,
                "worker_id",
                "month",
                "adjustment_minutes",
                "reason",
                "created_by",
            ),
            performed_by_worker_id=performed_by_worker_id,
            company_id=company_id,
        )
        return adjustment

    changed_fields = _changed_fields(
        adjustment,
        {
            "adjustment_minutes": adjustment_minutes,
            "reason": normalized_reason,
        },
    )
    if not changed_fields:
        return adjustment

    old_value = model_snapshot(adjustment, *changed_fields)
    adjustment.adjustment_minutes = adjustment_minutes
    adjustment.reason = normalized_reason
    db.add(adjustment)
    await log_audit_event(
        db,
        entity_type="monthly_adjustment",
        entity_id=adjustment.id,
        action="monthly_adjustment_updated",
        old_value=old_value,
        new_value=model_snapshot(adjustment, *changed_fields),
        performed_by_worker_id=performed_by_worker_id,
        company_id=company_id,
    )
    return adjustment
