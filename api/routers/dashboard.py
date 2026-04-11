from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.redis_client import redis_client
from api.services.dashboard_access import (
    DASHBOARD_RESPONSE_HEADERS,
    DashboardAccessError,
    get_company_present_worker_ids,
    get_dashboard_role,
    get_dashboard_worker,
    get_miniapp_dashboard_worker,
)
from db.database import get_db
from db.models import Request, Worker
from db.request_service import (
    RequestAccessError,
    list_company_requests,
    reject_request,
    resolve_request,
)
from db.security import decrypt_string


router = APIRouter()


class MiniAppBootstrapRequest(BaseModel):
    init_data: str


def _dashboard_access_denied() -> HTTPException:
    return HTTPException(status_code=404, detail="Not found")


def _serialize_datetime(value) -> str | None:
    return value.isoformat() if value else None


async def _get_company_worker_names(
    db: AsyncSession,
    *,
    company_id: int,
    worker_ids: set[int],
) -> dict[int, str]:
    if not worker_ids:
        return {}

    stmt = select(Worker).where(
        Worker.company_id == company_id,
        Worker.id.in_(worker_ids),
    )
    workers = (await db.execute(stmt)).scalars().all()
    return {
        company_worker.id: decrypt_string(company_worker.full_name_enc)
        for company_worker in workers
    }


async def _serialize_company_requests(
    db: AsyncSession,
    *,
    manager_worker: Worker,
    requests: list[Request],
) -> list[dict[str, str | int | None]]:
    worker_names = await _get_company_worker_names(
        db,
        company_id=manager_worker.company_id,
        worker_ids={
            request.target_worker_id
            for request in requests
            if request.target_worker_id is not None
        },
    )
    return [
        {
            "id": request.id,
            "created_at": _serialize_datetime(request.created_at),
            "related_date": request.related_date.isoformat() if request.related_date else None,
            "target_worker_name": worker_names.get(request.target_worker_id, "-"),
            "text": request.text,
            "status": request.status,
        }
        for request in requests
    ]


async def _get_authenticated_dashboard_worker(
    db: AsyncSession,
    *,
    token: str | None,
    telegram_init_data: str | None,
) -> Worker:
    if (token or "").strip():
        return await get_dashboard_worker(token, db, redis_client)
    return await get_miniapp_dashboard_worker(telegram_init_data, db)


@router.get("/dashboard")
async def serve_dashboard(
    token: str | None = Query(default=None),
):
    return FileResponse("api/static/dashboard.html", headers=DASHBOARD_RESPONSE_HEADERS)


@router.post("/api/dashboard/miniapp/bootstrap")
async def dashboard_miniapp_bootstrap(
    payload: MiniAppBootstrapRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        worker = await get_miniapp_dashboard_worker(payload.init_data, db)
    except DashboardAccessError as exc:
        raise _dashboard_access_denied() from exc

    return {
        "auth_mode": "miniapp",
        "user": {
            "name": decrypt_string(worker.full_name_enc),
            "role": get_dashboard_role(worker),
        },
    }


@router.get("/api/dashboard/data")
async def dashboard_data(
    token: str | None = Query(default=None),
    telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
    db: AsyncSession = Depends(get_db),
):
    try:
        worker = await _get_authenticated_dashboard_worker(
            db,
            token=token,
            telegram_init_data=telegram_init_data,
        )
    except DashboardAccessError as exc:
        raise _dashboard_access_denied() from exc

    today = date.today()

    stmt = select(Worker).where(
        Worker.company_id == worker.company_id,
        Worker.is_active.is_(True),
        Worker.time_tracking_enabled.is_(True),
    )
    workers = (await db.execute(stmt)).scalars().all()
    present_ids = await get_company_present_worker_ids(db, worker.company_id, today)

    return {
        "user": {
            "name": decrypt_string(worker.full_name_enc),
            "role": get_dashboard_role(worker),
        },
        "today": {
            "present": len(present_ids),
            "total_workers": len(workers),
        },
        "workers": [
            {
                "id": company_worker.id,
                "name": decrypt_string(company_worker.full_name_enc),
                "type": company_worker.worker_type.value,
                "rate": float(company_worker.hourly_rate or 0),
                "contract_hours_week": int(company_worker.contract_hours_week or 0),
                "present_today": company_worker.id in present_ids,
            }
            for company_worker in workers
        ],
    }


@router.get("/api/dashboard/requests")
async def dashboard_requests(
    token: str | None = Query(default=None),
    telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
    db: AsyncSession = Depends(get_db),
):
    try:
        worker = await _get_authenticated_dashboard_worker(
            db,
            token=token,
            telegram_init_data=telegram_init_data,
        )
        requests = await list_company_requests(db, manager_worker=worker)
    except (DashboardAccessError, RequestAccessError) as exc:
        raise _dashboard_access_denied() from exc

    return {
        "requests": await _serialize_company_requests(
            db,
            manager_worker=worker,
            requests=list(requests),
        )
    }


@router.api_route("/api/dashboard/requests/{request_id}/resolve", methods=["POST", "PATCH"])
async def dashboard_request_resolve(
    request_id: int,
    token: str | None = Query(default=None),
    telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
    db: AsyncSession = Depends(get_db),
):
    try:
        worker = await _get_authenticated_dashboard_worker(
            db,
            token=token,
            telegram_init_data=telegram_init_data,
        )
        request = await resolve_request(db, request_id=request_id, manager_worker=worker)
    except (DashboardAccessError, RequestAccessError) as exc:
        raise _dashboard_access_denied() from exc

    return {
        "id": request.id,
        "status": request.status,
        "resolved_at": _serialize_datetime(request.resolved_at),
    }


@router.api_route("/api/dashboard/requests/{request_id}/reject", methods=["POST", "PATCH"])
async def dashboard_request_reject(
    request_id: int,
    token: str | None = Query(default=None),
    telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
    db: AsyncSession = Depends(get_db),
):
    try:
        worker = await _get_authenticated_dashboard_worker(
            db,
            token=token,
            telegram_init_data=telegram_init_data,
        )
        request = await reject_request(db, request_id=request_id, manager_worker=worker)
    except (DashboardAccessError, RequestAccessError) as exc:
        raise _dashboard_access_denied() from exc

    return {
        "id": request.id,
        "status": request.status,
        "resolved_at": _serialize_datetime(request.resolved_at),
    }
