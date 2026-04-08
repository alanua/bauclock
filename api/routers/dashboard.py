from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.redis_client import redis_client
from api.services.dashboard_access import (
    DASHBOARD_RESPONSE_HEADERS,
    DashboardAccessError,
    get_company_present_worker_ids,
    get_dashboard_role,
    get_dashboard_worker,
)
from db.database import get_db
from db.models import Worker
from db.security import decrypt_string


router = APIRouter()


def _dashboard_access_denied() -> HTTPException:
    return HTTPException(status_code=404, detail="Not found")


@router.get("/dashboard")
async def serve_dashboard(
    token: str | None = Query(default=None),
):
    return FileResponse("api/static/dashboard.html", headers=DASHBOARD_RESPONSE_HEADERS)


@router.get("/api/dashboard/data")
async def dashboard_data(
    token: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    try:
        worker = await get_dashboard_worker(token, db, redis_client)
    except DashboardAccessError as exc:
        raise _dashboard_access_denied() from exc

    today = date.today()

    stmt = select(Worker).where(
        Worker.company_id == worker.company_id,
        Worker.is_active.is_(True),
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
