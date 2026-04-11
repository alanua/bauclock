from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Sequence

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from access.legacy_policy import can_view_admin_features
from db.models import Request, RequestStatus, Worker


class RequestAccessError(Exception):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_text(text: str) -> str:
    normalized = (text or "").strip()
    if not normalized:
        raise ValueError("request_text_required")
    return normalized


async def create_request(
    db: AsyncSession,
    *,
    creator_worker: Worker | None,
    text: str,
    company_id: int | None = None,
    target_worker_id: int | None = None,
    related_date: date | None = None,
) -> Request:
    if creator_worker:
        company_id = company_id or creator_worker.company_id
        if company_id != creator_worker.company_id:
            raise RequestAccessError("creator_company_mismatch")
        if not can_view_admin_features(creator_worker):
            target_worker_id = creator_worker.id
    elif company_id is None:
        raise ValueError("company_id_required")

    if target_worker_id is not None:
        target_worker = await db.get(Worker, target_worker_id)
        if not target_worker or target_worker.company_id != company_id:
            raise RequestAccessError("target_worker_company_mismatch")

    request = Request(
        company_id=company_id,
        created_by_worker_id=creator_worker.id if creator_worker else None,
        target_worker_id=target_worker_id,
        related_date=related_date,
        text=_normalize_text(text),
        status=RequestStatus.OPEN.value,
    )
    db.add(request)
    await db.commit()
    await db.refresh(request)
    return request


async def list_company_requests(db: AsyncSession, *, manager_worker: Worker) -> Sequence[Request]:
    if not can_view_admin_features(manager_worker):
        raise RequestAccessError("company_requests_denied")

    result = await db.execute(
        select(Request)
        .where(Request.company_id == manager_worker.company_id)
        .order_by(Request.created_at.desc(), Request.id.desc())
    )
    return result.scalars().all()


async def list_worker_requests(db: AsyncSession, *, worker: Worker) -> Sequence[Request]:
    result = await db.execute(
        select(Request)
        .where(
            Request.company_id == worker.company_id,
            or_(
                Request.created_by_worker_id == worker.id,
                Request.target_worker_id == worker.id,
            ),
        )
        .order_by(Request.created_at.desc(), Request.id.desc())
    )
    return result.scalars().all()


async def resolve_request(db: AsyncSession, *, request_id: int, manager_worker: Worker) -> Request:
    return await _set_request_status(
        db,
        request_id=request_id,
        manager_worker=manager_worker,
        status=RequestStatus.RESOLVED,
    )


async def reject_request(db: AsyncSession, *, request_id: int, manager_worker: Worker) -> Request:
    return await _set_request_status(
        db,
        request_id=request_id,
        manager_worker=manager_worker,
        status=RequestStatus.REJECTED,
    )


async def _set_request_status(
    db: AsyncSession,
    *,
    request_id: int,
    manager_worker: Worker,
    status: RequestStatus,
) -> Request:
    if not can_view_admin_features(manager_worker):
        raise RequestAccessError("request_status_change_denied")

    request = await db.get(Request, request_id)
    if not request or request.company_id != manager_worker.company_id:
        raise RequestAccessError("request_not_found")

    now = _utcnow()
    request.status = status.value
    request.updated_at = now
    request.resolved_at = now if status == RequestStatus.RESOLVED else None
    db.add(request)
    await db.commit()
    await db.refresh(request)
    return request
