from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import BillingType, Company, Worker, WorkerAccessRole, WorkerType
from db.security import encrypt_string, hash_string


async def ensure_company_owner_worker(
    telegram_user,
    session: AsyncSession,
    company: Company,
) -> Worker:
    tg_id_str = str(telegram_user.id)
    tg_hash = hash_string(tg_id_str)

    stmt = select(Worker).where(
        Worker.company_id == company.id,
        Worker.telegram_id_hash == tg_hash,
    )
    existing_worker = (await session.execute(stmt)).scalar_one_or_none()
    if existing_worker:
        updated = False
        if not existing_worker.can_view_dashboard:
            existing_worker.can_view_dashboard = True
            updated = True
        if existing_worker.access_role != WorkerAccessRole.COMPANY_OWNER.value:
            existing_worker.access_role = WorkerAccessRole.COMPANY_OWNER.value
            updated = True
        if not existing_worker.is_active:
            existing_worker.is_active = True
            updated = True
        if existing_worker.created_by is not None:
            existing_worker.created_by = None
            updated = True
        if existing_worker.time_tracking_enabled:
            existing_worker.time_tracking_enabled = False
            updated = True
        if updated:
            session.add(existing_worker)
            await session.commit()
        return existing_worker

    chief_worker = Worker(
        company_id=company.id,
        telegram_id_enc=encrypt_string(tg_id_str),
        telegram_id_hash=tg_hash,
        full_name_enc=encrypt_string(telegram_user.full_name or "Chief Owner"),
        worker_type=WorkerType.FESTANGESTELLT,
        billing_type=BillingType.HOURLY,
        access_role=WorkerAccessRole.COMPANY_OWNER.value,
        can_view_dashboard=True,
        time_tracking_enabled=False,
        is_active=True,
        created_by=None,
    )
    session.add(chief_worker)
    await session.commit()
    return chief_worker
