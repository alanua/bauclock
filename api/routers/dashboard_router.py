from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request as FastAPIRequest
from sqlalchemy.ext.asyncio import AsyncSession

from api.redis_client import redis_client
from api.routers import dashboard as dashboard_views
from api.services.dashboard_access import DashboardAccessError, get_dashboard_context
from db.database import get_db


router = APIRouter()


@router.get("/dashboard")
async def serve_dashboard(
    request: FastAPIRequest,
    token: str | None = Query(default=None),
    version: str | None = Query(default=None, alias="v"),
    db: AsyncSession = Depends(get_db),
):
    try:
        await get_dashboard_context(token, db, redis_client)
    except DashboardAccessError as exc:
        raise dashboard_views._dashboard_access_denied() from exc
    return await dashboard_views.serve_dashboard(request=request, token=token, version=version)


@router.get("/api/dashboard/data")
async def dashboard_data(
    token: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    try:
        await get_dashboard_context(token, db, redis_client)
    except DashboardAccessError as exc:
        raise dashboard_views._dashboard_access_denied() from exc
    return await dashboard_views.dashboard_data(token=token, telegram_init_data=None, db=db)
