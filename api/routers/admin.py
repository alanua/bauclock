import csv
from io import StringIO
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.database import get_db
from db.models import Payment, Worker, WorkerType, PaymentType
from db.security import decrypt_string

router = APIRouter()

@router.get("/health", summary="Health check endpoint")
async def health_check():
    """Returns the health status of the API."""
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

@router.get("/export/datev", response_class=PlainTextResponse, summary="Export billing data for DATEV")
async def export_datev(
    start_date: datetime = Query(..., description="Start of the billing period"),
    end_date: datetime = Query(..., description="End of the billing period"),
    db: AsyncSession = Depends(get_db)
):
    """
    Generates a CSV export of confirmed payments within the given period.
    Format is intended for DATEV: Worker Name, Hours, Rate, Total Amount, Worker Type
    """
    # Query confirmed payments in the period mapping to workers
    stmt = select(Payment, Worker).join(Worker, Payment.worker_id == Worker.id).where(
        Payment.period_start >= start_date,
        Payment.period_end <= end_date,
        Payment.status == "CONFIRMED",
        Payment.payment_type == PaymentType.CONTRACT
    )
    result = await db.execute(stmt)
    records = result.all()

    # Generate CSV in memory
    output = StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(["Worker Name", "Worker Type", "Hours Paid", "Hourly Rate", "Total Amount Base", "Period Start", "Period End"])

    for payment, worker in records:
        name = decrypt_string(worker.full_name_enc)
        rate = worker.hourly_rate or 0.0
        
        writer.writerow([
            name,
            worker.worker_type.value,
            f"{payment.hours_paid:.2f}",
            f"{rate:.2f}",
            f"{payment.amount_paid:.2f}",
            payment.period_start.isoformat(),
            payment.period_end.isoformat()
        ])

    return output.getvalue()
