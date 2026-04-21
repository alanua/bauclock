from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import RetentionHold


def _effective_now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def _active_hold_filter(*, now: datetime):
    return and_(
        RetentionHold.is_active.is_(True),
        or_(
            and_(RetentionHold.hold_until.is_(None), RetentionHold.expires_at.is_(None)),
            RetentionHold.hold_until > now,
            and_(RetentionHold.hold_until.is_(None), RetentionHold.expires_at > now),
        ),
    )


async def place_retention_hold(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: int,
    hold_reason: str,
    hold_type: str = "admin_hold",
    company_id: int | None = None,
    held_by_worker_id: int | None = None,
    hold_until: datetime | None = None,
) -> RetentionHold:
    normalized_reason = (hold_reason or "").strip()
    if not normalized_reason:
        raise ValueError("hold_reason_required")

    hold = RetentionHold(
        entity_type=entity_type,
        entity_id=entity_id,
        hold_type=hold_type,
        hold_reason=normalized_reason,
        reason=normalized_reason,
        company_id=company_id,
        held_by_worker_id=held_by_worker_id,
        hold_until=hold_until,
        expires_at=hold_until,
        is_active=True,
    )
    db.add(hold)
    await db.flush()
    return hold


async def release_retention_holds(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: int,
    hold_type: str | None = None,
) -> int:
    stmt = select(RetentionHold).where(
        RetentionHold.entity_type == entity_type,
        RetentionHold.entity_id == entity_id,
        RetentionHold.is_active.is_(True),
    )
    if hold_type is not None:
        stmt = stmt.where(RetentionHold.hold_type == hold_type)

    holds = (await db.execute(stmt.order_by(RetentionHold.id.asc()))).scalars().all()
    for hold in holds:
        hold.is_active = False
        db.add(hold)
    await db.flush()
    return len(holds)


async def expire_retention_holds(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    effective_now = _effective_now(now)
    holds = (
        await db.execute(
            select(RetentionHold).where(
                RetentionHold.is_active.is_(True),
                or_(
                    RetentionHold.hold_until <= effective_now,
                    and_(RetentionHold.hold_until.is_(None), RetentionHold.expires_at <= effective_now),
                ),
            )
        )
    ).scalars().all()
    for hold in holds:
        hold.is_active = False
        db.add(hold)
    await db.flush()
    return len(holds)


async def is_entity_on_retention_hold(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: int,
    now: datetime | None = None,
) -> bool:
    effective_now = _effective_now(now)
    hold = await db.scalar(
        select(RetentionHold.id).where(
            RetentionHold.entity_type == entity_type,
            RetentionHold.entity_id == entity_id,
            _active_hold_filter(now=effective_now),
        )
    )
    return bool(hold)


async def active_retention_hold_entity_ids(
    db: AsyncSession,
    *,
    entity_type: str,
    now: datetime | None = None,
) -> set[int]:
    effective_now = _effective_now(now)
    result = await db.execute(
        select(RetentionHold.entity_id).where(
            RetentionHold.entity_type == entity_type,
            _active_hold_filter(now=effective_now),
        )
    )
    return {int(entity_id) for entity_id in result.scalars().all()}
