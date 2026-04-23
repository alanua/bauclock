from __future__ import annotations

import csv
from datetime import datetime
from io import StringIO

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.audit_logger import log_audit_event
from db.models import Payment, PaymentStatus, PaymentType, Worker
from db.security import decrypt_string


class DatevExportError(Exception):
    pass


async def export_datev_csv(
    db: AsyncSession,
    *,
    actor_worker: Worker,
    start_date: datetime,
    end_date: datetime,
) -> str:
    if end_date < start_date:
        raise DatevExportError("date_range_invalid")

    stmt = (
        select(Payment, Worker)
        .join(Worker, Payment.worker_id == Worker.id)
        .where(
            Payment.period_start >= start_date,
            Payment.period_end <= end_date,
            Payment.status == PaymentStatus.CONFIRMED,
            Payment.payment_type == PaymentType.CONTRACT.value,
            Worker.company_id == actor_worker.company_id,
        )
        .order_by(Payment.period_start.asc(), Payment.period_end.asc(), Payment.id.asc())
    )
    records = (await db.execute(stmt)).all()

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
                f"{float(payment.hours_paid or 0):.2f}",
                f"{float(worker.hourly_rate or 0):.2f}",
                f"{float(payment.amount_paid or 0):.2f}",
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
