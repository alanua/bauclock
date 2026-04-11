from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from access.legacy_policy import can_access_dashboard, legacy_dashboard_role
from api.services.telegram_init_data import TelegramInitDataError, validate_telegram_init_data
from db.dashboard_tokens import dashboard_token_key
from db.models import (
    BillingType,
    Company,
    CompanyPublicProfile,
    TimeEvent,
    Worker,
    WorkerAccessRole,
    WorkerType,
)
from db.security import encrypt_string, hash_string


DASHBOARD_RESPONSE_HEADERS = {"Cache-Control": "no-store"}


class DashboardAccessError(Exception):
    pass


def get_dashboard_role(worker: Worker) -> str:
    return legacy_dashboard_role(worker)


def _normalize_username(username: str | None) -> str:
    return (username or "").strip().lstrip("@").casefold()


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
    if not can_access_dashboard(worker):
        raise DashboardAccessError("dashboard_access_denied")

    return worker


async def _get_sek_company(db: AsyncSession) -> Company | None:
    profile = (
        await db.execute(
            select(CompanyPublicProfile).where(
                CompanyPublicProfile.slug == "sek",
                CompanyPublicProfile.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if profile and profile.company_id:
        return await db.get(Company, profile.company_id)

    return (
        await db.execute(select(Company).where(func.lower(Company.name).like("%sek%")).limit(1))
    ).scalar_one_or_none()


async def _ensure_sek_admin_worker(
    db: AsyncSession,
    *,
    telegram_user: dict[str, Any],
    telegram_id_hash: str,
    existing_worker: Worker | None,
) -> Worker | None:
    company = await _get_sek_company(db)
    if not company:
        return None

    if existing_worker and existing_worker.company_id != company.id:
        return None

    owner_worker = (
        await db.execute(
            select(Worker).where(
                Worker.company_id == company.id,
                Worker.telegram_id_hash == company.owner_telegram_id_hash,
            )
        )
    ).scalar_one_or_none()
    access_role = (
        WorkerAccessRole.OBJEKTMANAGER.value
        if owner_worker and owner_worker.telegram_id_hash != telegram_id_hash
        else WorkerAccessRole.COMPANY_OWNER.value
    )

    if existing_worker:
        existing_worker.is_active = True
        existing_worker.can_view_dashboard = True
        if existing_worker.access_role == WorkerAccessRole.WORKER.value:
            existing_worker.access_role = access_role
        db.add(existing_worker)
        await db.commit()
        await db.refresh(existing_worker)
        return existing_worker

    first_name = str(telegram_user.get("first_name") or "").strip()
    last_name = str(telegram_user.get("last_name") or "").strip()
    username = str(telegram_user.get("username") or "").strip()
    full_name = " ".join(value for value in [first_name, last_name] if value).strip()
    if not full_name and username:
        full_name = username
    if not full_name:
        full_name = "SEK Admin"

    worker = Worker(
        company_id=company.id,
        telegram_id_enc=encrypt_string(str(telegram_user["id"])),
        telegram_id_hash=telegram_id_hash,
        full_name_enc=encrypt_string(full_name),
        worker_type=WorkerType.FESTANGESTELLT,
        billing_type=BillingType.HOURLY,
        access_role=access_role,
        can_view_dashboard=True,
        time_tracking_enabled=False,
        is_active=True,
        created_by=owner_worker.id if owner_worker else None,
    )
    db.add(worker)
    await db.commit()
    await db.refresh(worker)
    return worker


async def get_miniapp_dashboard_worker(
    init_data: str | None,
    db: AsyncSession,
    *,
    bot_token: str | None = None,
) -> Worker:
    normalized_init_data = (init_data or "").strip()
    if not normalized_init_data:
        raise DashboardAccessError("missing_miniapp_init_data")

    if bot_token is None:
        from api.config import settings

        bot_token = settings.BOT_TOKEN
        admin_usernames = settings.ADMIN_USERNAMES
    else:
        admin_usernames = []

    try:
        payload = validate_telegram_init_data(
            normalized_init_data,
            bot_token=bot_token,
        )
    except TelegramInitDataError as exc:
        raise DashboardAccessError("invalid_miniapp_init_data") from exc

    telegram_user = payload["user"]
    telegram_user_id = telegram_user.get("id")
    telegram_id_hash = hash_string(str(telegram_user_id))
    worker = (
        await db.execute(
            select(Worker).where(Worker.telegram_id_hash == telegram_id_hash)
        )
    ).scalar_one_or_none()
    if can_access_dashboard(worker):
        return worker

    username = _normalize_username(telegram_user.get("username"))
    if username and username in admin_usernames:
        worker = await _ensure_sek_admin_worker(
            db,
            telegram_user=telegram_user,
            telegram_id_hash=telegram_id_hash,
            existing_worker=worker,
        )
    if not can_access_dashboard(worker):
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
            Worker.time_tracking_enabled.is_(True),
            func.date(TimeEvent.timestamp) == day,
        )
        .distinct()
    )
    result = await db.execute(stmt)
    return set(result.scalars().all())
