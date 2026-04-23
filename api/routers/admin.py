from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from access.legacy_policy import can_manage_payments
from api.redis_client import redis_client
from api.services.datev_export import DatevExportError, export_datev_csv
from api.services.dashboard_access import DashboardAccessError, get_dashboard_worker
from db.database import get_db


router = APIRouter()


def _admin_access_denied() -> HTTPException:
    return HTTPException(status_code=403, detail="Forbidden")


@router.get("/health", summary="Health check endpoint")
async def health_check():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@router.get("/export/datev", response_class=PlainTextResponse, summary="Export billing data for DATEV")
async def export_datev(
    start_date: datetime = Query(..., description="Start of the billing period"),
    end_date: datetime = Query(..., description="End of the billing period"),
    token: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    try:
        actor_worker = await get_dashboard_worker(token, db, redis_client)
    except DashboardAccessError as exc:
        raise _admin_access_denied() from exc
    if not can_manage_payments(actor_worker):
        raise _admin_access_denied()

    try:
        return await export_datev_csv(
            db,
            actor_worker=actor_worker,
            start_date=start_date,
            end_date=end_date,
        )
    except DatevExportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
