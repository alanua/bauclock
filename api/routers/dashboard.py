from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request as FastAPIRequest
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.redis_client import redis_client
from api.services.dashboard_access import (
    DASHBOARD_RESPONSE_HEADERS,
    DashboardContext,
    DashboardAccessError,
    get_company_present_worker_ids,
    get_dashboard_context,
    get_dashboard_role,
    get_miniapp_dashboard_context,
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
DASHBOARD_SHELL_VERSION = "20260412-auto-miniapp"


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
    company_id: int,
    requests: list[Request],
) -> list[dict[str, str | int | None]]:
    worker_names = await _get_company_worker_names(
        db,
        company_id=company_id,
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


def _dashboard_context_user(context: DashboardContext) -> dict[str, str]:
    if context.worker:
        return {
            "name": decrypt_string(context.worker.full_name_enc),
            "role": get_dashboard_role(context.worker),
        }
    return {
        "name": context.display_name or "Platform Superadmin",
        "role": context.role or "PLATFORM_SUPERADMIN",
    }


def _dashboard_manager(context: DashboardContext):
    if context.worker:
        return context.worker
    return SimpleNamespace(
        id=None,
        company_id=context.company_id,
        can_view_dashboard=True,
        is_active=True,
        created_by=None,
    )


async def _get_authenticated_dashboard_context(
    db: AsyncSession,
    *,
    token: str | None,
    telegram_init_data: str | None,
) -> DashboardContext:
    if (token or "").strip():
        return await get_dashboard_context(token, db, redis_client)
    return await get_miniapp_dashboard_context(telegram_init_data, db)


@router.get("/dashboard")
async def serve_dashboard(
    request: FastAPIRequest,
    token: str | None = Query(default=None),
    version: str | None = Query(default=None, alias="v"),
):
    if version != DASHBOARD_SHELL_VERSION:
        query_params = dict(request.query_params)
        query_params["v"] = DASHBOARD_SHELL_VERSION
        return RedirectResponse(
            f"{request.url.path}?{urlencode(query_params)}",
            status_code=307,
            headers=DASHBOARD_RESPONSE_HEADERS,
        )
    return FileResponse("api/static/dashboard.html", headers=DASHBOARD_RESPONSE_HEADERS)


@router.post("/api/dashboard/miniapp/bootstrap")
async def dashboard_miniapp_bootstrap(
    payload: MiniAppBootstrapRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        context = await get_miniapp_dashboard_context(payload.init_data, db)
    except DashboardAccessError as exc:
        raise _dashboard_access_denied() from exc

    return {
        "auth_mode": "miniapp",
        "user": _dashboard_context_user(context),
    }


@router.get("/api/dashboard/data")
async def dashboard_data(
    token: str | None = Query(default=None),
    telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
    db: AsyncSession = Depends(get_db),
):
    try:
        context = await _get_authenticated_dashboard_context(
            db,
            token=token,
            telegram_init_data=telegram_init_data,
        )
    except DashboardAccessError as exc:
        raise _dashboard_access_denied() from exc

    today = date.today()

    stmt = select(Worker).where(
        Worker.company_id == context.company_id,
        Worker.is_active.is_(True),
        Worker.time_tracking_enabled.is_(True),
    )
    workers = (await db.execute(stmt)).scalars().all()
    present_ids = await get_company_present_worker_ids(db, context.company_id, today)

    return {
        "user": _dashboard_context_user(context),
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
        context = await _get_authenticated_dashboard_context(
            db,
            token=token,
            telegram_init_data=telegram_init_data,
        )
        requests = await list_company_requests(db, manager_worker=_dashboard_manager(context))
    except (DashboardAccessError, RequestAccessError) as exc:
        raise _dashboard_access_denied() from exc

    return {
        "requests": await _serialize_company_requests(
            db,
            company_id=context.company_id,
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
        context = await _get_authenticated_dashboard_context(
            db,
            token=token,
            telegram_init_data=telegram_init_data,
        )
        request = await resolve_request(
            db,
            request_id=request_id,
            manager_worker=_dashboard_manager(context),
        )
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
        context = await _get_authenticated_dashboard_context(
            db,
            token=token,
            telegram_init_data=telegram_init_data,
        )
        request = await reject_request(
            db,
            request_id=request_id,
            manager_worker=_dashboard_manager(context),
        )
    except (DashboardAccessError, RequestAccessError) as exc:
        raise _dashboard_access_denied() from exc

    return {
        "id": request.id,
        "status": request.status,
        "resolved_at": _serialize_datetime(request.resolved_at),
    }
