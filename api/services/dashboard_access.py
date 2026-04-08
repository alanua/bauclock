from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.dashboard_tokens import dashboard_token_key
from db.models import TimeEvent, Worker


DASHBOARD_RESPONSE_HEADERS = {"Cache-Control": "no-store"}


class DashboardAccessError(Exception):
    pass
def get_dashboard_role(worker: Worker) -> str:
    return "OWNER" if worker.created_by is None else "SUPERVISOR"


async def get_dashboard_worker(
    token: str | None,
    db: AsyncSession,
    redis_client: Any,
) -> Worker:
    normalized_token = (token or "").strip()
    if not normalized_token:
        raise DashboardAccessError("missing_dashboard_token")

    worker_id = await redis_client.get(dashboard_token_key(normalized_token))
    if not worker_id:
        raise DashboardAccessError("invalid_dashboard_token")

    try:
        worker_id_int = int(worker_id)
    except (TypeError, ValueError) as exc:
        raise DashboardAccessError("invalid_dashboard_token") from exc

    worker = await db.get(Worker, worker_id_int)
    if not worker or not worker.is_active or not worker.can_view_dashboard:
        raise DashboardAccessError("dashboard_access_denied")

    return worker


async def get_company_present_worker_ids(
    db: AsyncSession,
    company_id: int,
    day: date,
) -> set[int]:
    stmt = (
        select(TimeEvent.worker_id)
        .join(Worker, Worker.id == TimeEvent.worker_id)
        .where(
            Worker.company_id == company_id,
            Worker.is_active.is_(True),
            func.date(TimeEvent.timestamp) == day,
        )
        .distinct()
    )
    result = await db.execute(stmt)
    return set(result.scalars().all())
