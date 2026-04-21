import csv
from datetime import datetime
from io import StringIO

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from access.legacy_policy import can_manage_payments
from api.redis_client import redis_client
from api.services.audit_logger import log_audit_event
from api.services.dashboard_access import DashboardAccessError, get_dashboard_worker
from db.database import get_db
from db.models import Payment, PaymentType, Worker
from db.security import decrypt_string


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

    stmt = (
        select(Payment, Worker)
        .join(Worker, Payment.worker_id == Worker.id)
        .where(
            Payment.period_start >= start_date,
            Payment.period_end <= end_date,
            Payment.status == "CONFIRMED",
            Payment.payment_type == PaymentType.CONTRACT,
            Worker.company_id == actor_worker.company_id,
        )
    )
    result = await db.execute(stmt)
    records = result.all()

    output = StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(
        [
            "Worker Name",
            "Worker Type",
            "Hours Paid",
            "Hourly Rate",
            "Total Amount Base",
            "Period Start",
            "Period End",
        ]
    )

    for payment, worker in records:
        writer.writerow(
            [
                decrypt_string(worker.full_name_enc),
                worker.worker_type.value,
                f"{payment.hours_paid:.2f}",
                f"{(worker.hourly_rate or 0.0):.2f}",
                f"{payment.amount_paid:.2f}",
                payment.period_start.isoformat(),
                payment.period_end.isoformat(),
            ]
        )

    await log_audit_event(
        db,
        entity_type="datev_export",
        entity_id=0,
        action="datev_export_triggered",
        old_value=None,
        new_value={
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "rows": len(records),
            "payment_type": PaymentType.CONTRACT.value,
        },
        performed_by_worker_id=actor_worker.id,
        company_id=actor_worker.company_id,
    )
    await db.commit()

    return output.getvalue()
