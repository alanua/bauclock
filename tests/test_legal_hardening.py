import asyncio
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from types import ModuleType

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault(
    "ENCRYPTION_KEY",
    "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff",
)
os.environ.setdefault("HASH_PEPPER", "test_pepper")

if "api.redis_client" not in sys.modules:
    api_redis_module = ModuleType("api.redis_client")
    api_redis_module.redis_client = SimpleNamespace()
    api_redis_module.redis = api_redis_module.redis_client
    sys.modules["api.redis_client"] = api_redis_module

import api.routers.admin as admin_router
import api.routers.dashboard as dashboard_router
from api.config import settings
from api.services.arbzg_policy import get_worker_arbzg_flags
from api.services.dashboard_access import DashboardAccessError, get_dashboard_worker
from api.services.legal_acceptance import (
    get_legal_acceptance_overview,
    record_company_onboarding_acceptance,
    record_worker_onboarding_acknowledgements,
)
from api.services.retention import run_retention_cycle
from db.dashboard_tokens import build_dashboard_token_payload, dashboard_token_key
from db.models import AuditLog, Base, BillingType, Company, EventType, Payment, PaymentStatus, RetentionHold, Site, TimeEvent, Worker, WorkerAccessRole, WorkerType
from db.time_corrections import apply_manual_time_correction


class FakeRedis:
    def __init__(self, values: dict[str, str | None]):
        self.values = values

    async def get(self, key: str) -> str | None:
        return self.values.get(key)


def run_db_test(test_coro):
    async def runner():
        with TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "legal_hardening.db"
            engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
            session_maker = async_sessionmaker(engine, expire_on_commit=False)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with session_maker() as session:
                await test_coro(session)

            await engine.dispose()

    asyncio.run(runner())


async def seed_company(session, suffix: str) -> Company:
    company = Company(
        name=f"Company {suffix}",
        owner_telegram_id_enc=f"owner_enc_{suffix}",
        owner_telegram_id_hash=f"owner_hash_{suffix}",
    )
    session.add(company)
    await session.flush()
    return company


async def seed_site(session, company_id: int, suffix: str) -> Site:
    site = Site(
        company_id=company_id,
        name=f"Site {suffix}",
        qr_token=f"site_{suffix}",
        is_active=True,
    )
    session.add(site)
    await session.flush()
    return site


async def seed_worker(
    session,
    company_id: int,
    suffix: str,
    *,
    can_view_dashboard: bool = False,
    access_role: str = WorkerAccessRole.WORKER.value,
    site_id: int | None = None,
    time_tracking_enabled: bool = True,
) -> Worker:
    worker = Worker(
        company_id=company_id,
        site_id=site_id,
        telegram_id_enc=f"telegram_enc_{suffix}",
        telegram_id_hash=f"telegram_hash_{suffix}",
        full_name_enc=f"name_enc_{suffix}",
        worker_type=WorkerType.FESTANGESTELLT,
        billing_type=BillingType.HOURLY,
        can_view_dashboard=can_view_dashboard,
        access_role=access_role,
        time_tracking_enabled=time_tracking_enabled,
        is_active=True,
    )
    session.add(worker)
    await session.flush()
    return worker


def test_dashboard_token_rejects_company_mismatch():
    async def run_test(session):
        company = await seed_company(session, "token")
        worker = await seed_worker(
            session,
            company.id,
            "token-owner",
            can_view_dashboard=True,
            access_role=WorkerAccessRole.COMPANY_OWNER.value,
            time_tracking_enabled=False,
        )
        await session.commit()

        token = "company-mismatch"
        redis_client = FakeRedis(
            {
                dashboard_token_key(token): build_dashboard_token_payload(
                    worker_id=worker.id,
                    company_id=company.id + 99,
                )
            }
        )

        with pytest.raises(DashboardAccessError, match="dashboard_scope_denied"):
            await get_dashboard_worker(token, session, redis_client)

    run_db_test(run_test)


def test_manual_time_correction_requires_reason_and_is_visible_in_worker_home(monkeypatch):
    async def run_test(session):
        company = await seed_company(session, "manual")
        site = await seed_site(session, company.id, "manual")
        owner = await seed_worker(
            session,
            company.id,
            "manual-owner",
            can_view_dashboard=True,
            access_role=WorkerAccessRole.COMPANY_OWNER.value,
            time_tracking_enabled=False,
        )
        worker = await seed_worker(session, company.id, "manual-worker", site_id=site.id)
        event = TimeEvent(
            worker_id=worker.id,
            site_id=site.id,
            event_type=EventType.CHECKIN,
            timestamp=datetime.now(timezone.utc).replace(hour=8, minute=0, second=0, microsecond=0),
        )
        session.add(event)
        await session.commit()

        with pytest.raises(ValueError, match="correction_reason_required"):
            await apply_manual_time_correction(
                session,
                actor_worker=owner,
                event_id=event.id,
                reason="",
                new_timestamp=event.timestamp + timedelta(minutes=15),
            )

        corrected = await apply_manual_time_correction(
            session,
            actor_worker=owner,
            event_id=event.id,
            reason="Supervisor correction",
            new_timestamp=event.timestamp + timedelta(minutes=15),
        )

        monkeypatch.setattr(dashboard_router, "decrypt_string", lambda value: value)
        worker_home = await dashboard_router._serialize_worker_home(session, worker=worker)
        audit_logs = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.entity_type == "time_event",
                    AuditLog.entity_id == event.id,
                )
            )
        ).scalars().all()

        assert corrected.is_manual is True
        assert corrected.correction_reason == "Supervisor correction"
        assert corrected.corrected_by_worker_id == owner.id
        assert worker_home["today_events"][0]["is_manual"] is True
        assert worker_home["today_events"][0]["correction_reason"] == "Supervisor correction"
        assert len(audit_logs) == 1
        assert audit_logs[0].action == "manual_time_correction"

    run_db_test(run_test)


def test_arbzg_flags_include_break_and_rest_period_warning():
    async def run_test(session):
        company = await seed_company(session, "arbzg")
        site = await seed_site(session, company.id, "arbzg")
        worker = await seed_worker(session, company.id, "arbzg-worker", site_id=site.id)
        today = date(2026, 4, 21)
        previous_checkout = datetime(2026, 4, 20, 23, 30, tzinfo=timezone.utc)
        checkin = datetime(2026, 4, 21, 8, 0, tzinfo=timezone.utc)
        session.add_all(
            [
                TimeEvent(
                    worker_id=worker.id,
                    site_id=site.id,
                    event_type=EventType.CHECKOUT,
                    timestamp=previous_checkout,
                ),
                TimeEvent(
                    worker_id=worker.id,
                    site_id=site.id,
                    event_type=EventType.CHECKIN,
                    timestamp=checkin,
                ),
            ]
        )
        await session.commit()

        flags = await get_worker_arbzg_flags(
            session,
            worker_id=worker.id,
            target_day=today,
            now=datetime(2026, 4, 21, 15, 30, tzinfo=timezone.utc),
        )
        codes = {flag["code"] for flag in flags}

        assert "break_reminder_after_6h" in codes
        assert "rest_period_warning" in codes

    run_db_test(run_test)


def test_retention_cycle_reports_candidates_and_holds_without_deleting_in_dry_run(monkeypatch):
    async def run_test(session):
        monkeypatch.setattr(settings, "ENABLE_RETENTION", False)
        monkeypatch.setattr(settings, "RETENTION_DRY_RUN", True)
        monkeypatch.setattr(settings, "DATA_RETENTION_YEARS_TIME_EVENTS", 3)
        monkeypatch.setattr(settings, "DATA_RETENTION_YEARS_AUDIT_LOGS", 5)

        company = await seed_company(session, "retention")
        site = await seed_site(session, company.id, "retention")
        worker = await seed_worker(session, company.id, "retention-worker", site_id=site.id)
        old_event = TimeEvent(
            worker_id=worker.id,
            site_id=site.id,
            event_type=EventType.CHECKIN,
            timestamp=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        old_audit = AuditLog(
            entity_type="worker",
            entity_id=worker.id,
            action="worker_updated",
            old_value={},
            new_value={},
            company_id=company.id,
            created_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        hold = RetentionHold(
            entity_type="time_event",
            entity_id=1,
            hold_type="open_dispute",
            company_id=company.id,
            is_active=True,
        )
        session.add_all([old_event, old_audit])
        await session.flush()
        hold.entity_id = old_event.id
        session.add(hold)
        await session.commit()

        report = await run_retention_cycle(session, now=datetime(2026, 4, 21, tzinfo=timezone.utc))

        totals = report["totals"]
        assert totals["candidate_count"] >= 2
        assert totals["held_count"] == 1
        assert totals["deleted_count"] == 0
        assert await session.get(TimeEvent, old_event.id) is not None
        assert await session.get(AuditLog, old_audit.id) is not None

    run_db_test(run_test)


def test_legal_acceptance_overview_tracks_company_and_worker_evidence():
    async def run_test(session):
        company = await seed_company(session, "legal")
        actor = await seed_worker(session, company.id, "legal-worker")

        await record_company_onboarding_acceptance(
            session,
            actor_worker_id=actor.id,
            company_id=company.id,
        )
        await record_worker_onboarding_acknowledgements(
            session,
            worker_id=actor.id,
            company_id=company.id,
            gps_notice_enabled=True,
        )
        await session.commit()

        overview = await get_legal_acceptance_overview(session, company_id=company.id)

        assert overview["company_documents_complete"] is True
        assert overview["worker_notice_completion"] == {"completed": 1, "total": 1}

    run_db_test(run_test)


def test_datev_export_requires_token_and_excludes_overtime(monkeypatch):
    async def run_test(session):
        company = await seed_company(session, "datev")
        owner = await seed_worker(
            session,
            company.id,
            "datev-owner",
            can_view_dashboard=True,
            access_role=WorkerAccessRole.COMPANY_OWNER.value,
            time_tracking_enabled=False,
        )
        worker = await seed_worker(session, company.id, "datev-worker")
        start_date = datetime(2026, 4, 1, tzinfo=timezone.utc)
        end_date = datetime(2026, 4, 30, tzinfo=timezone.utc)
        session.add_all(
            [
                Payment(
                    worker_id=worker.id,
                    period_start=start_date,
                    period_end=end_date,
                    hours_paid=8,
                    amount_paid=160,
                    status=PaymentStatus.CONFIRMED,
                    payment_type="CONTRACT",
                ),
                Payment(
                    worker_id=worker.id,
                    period_start=start_date,
                    period_end=end_date,
                    hours_paid=3,
                    amount_paid=90,
                    status=PaymentStatus.CONFIRMED,
                    payment_type="OVERTIME",
                ),
            ]
        )
        await session.commit()

        token = "datev-token"
        monkeypatch.setattr(admin_router, "decrypt_string", lambda value: value)
        monkeypatch.setattr(
            admin_router,
            "redis_client",
            FakeRedis(
                {
                    dashboard_token_key(token): build_dashboard_token_payload(
                        worker_id=owner.id,
                        company_id=owner.company_id,
                    )
                }
            ),
        )

        csv_data = await admin_router.export_datev(
            start_date=start_date,
            end_date=end_date,
            token=token,
            db=session,
        )
        audit_logs = (
            await session.execute(
                select(AuditLog).where(AuditLog.entity_type == "datev_export")
            )
        ).scalars().all()

        assert "160.00" in csv_data
        assert "90.00" not in csv_data
        assert len(audit_logs) == 1
        assert audit_logs[0].action == "datev_export_triggered"

        with pytest.raises(HTTPException) as exc_info:
            await admin_router.export_datev(
                start_date=start_date,
                end_date=end_date,
                token="missing-token",
                db=session,
            )
        assert exc_info.value.status_code == 403

    run_db_test(run_test)
