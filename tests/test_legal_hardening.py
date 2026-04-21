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
from api.services.audited_changes import (
    apply_audited_payment_update,
    apply_audited_worker_update,
    upsert_monthly_adjustment,
)
from api.services.dashboard_access import DashboardAccessError, get_dashboard_worker
from api.services.legal_acceptance import (
    get_legal_acceptance_overview,
    record_company_onboarding_acceptance,
    record_legal_acceptance,
    record_worker_onboarding_acknowledgements,
)
from api.services.retention_holds import (
    expire_retention_holds,
    is_entity_on_retention_hold,
    place_retention_hold,
    release_retention_holds,
)
from api.services.retention import run_retention_cycle
from db.dashboard_tokens import build_dashboard_token_payload, dashboard_token_key
from db.models import AuditLog, Base, BillingType, Company, EventType, LegalAcceptanceLog, MonthlyAdjustment, Payment, PaymentStatus, RetentionHold, Site, TimeEvent, Worker, WorkerAccessRole, WorkerType
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


def test_worker_permission_and_rate_updates_create_audit_logs():
    async def run_test(session):
        company = await seed_company(session, "worker-audit")
        owner = await seed_worker(
            session,
            company.id,
            "worker-audit-owner",
            can_view_dashboard=True,
            access_role=WorkerAccessRole.COMPANY_OWNER.value,
            time_tracking_enabled=False,
        )
        worker = await seed_worker(session, company.id, "worker-audit-target")
        worker.hourly_rate = 18.5
        worker.contract_hours_week = 35
        await session.commit()

        await apply_audited_worker_update(
            session,
            worker=worker,
            action="worker_role_updated",
            performed_by_worker_id=owner.id,
            company_id=company.id,
            access_role=WorkerAccessRole.ACCOUNTANT.value,
            can_view_dashboard=True,
        )
        await apply_audited_worker_update(
            session,
            worker=worker,
            action="worker_hourly_rate_updated",
            performed_by_worker_id=owner.id,
            company_id=company.id,
            hourly_rate=24.0,
        )
        await apply_audited_worker_update(
            session,
            worker=worker,
            action="worker_contract_hours_week_updated",
            performed_by_worker_id=owner.id,
            company_id=company.id,
            contract_hours_week=40,
        )
        await session.commit()

        audit_logs = (
            await session.execute(
                select(AuditLog)
                .where(
                    AuditLog.entity_type == "worker",
                    AuditLog.entity_id == worker.id,
                )
                .order_by(AuditLog.id.asc())
            )
        ).scalars().all()

        assert [log.action for log in audit_logs] == [
            "worker_role_updated",
            "worker_hourly_rate_updated",
            "worker_contract_hours_week_updated",
        ]
        assert audit_logs[0].old_value == {
            "access_role": WorkerAccessRole.WORKER.value,
            "can_view_dashboard": False,
        }
        assert audit_logs[0].new_value == {
            "access_role": WorkerAccessRole.ACCOUNTANT.value,
            "can_view_dashboard": True,
        }
        assert audit_logs[1].old_value == {"hourly_rate": 18.5}
        assert audit_logs[1].new_value == {"hourly_rate": 24.0}
        assert audit_logs[2].old_value == {"contract_hours_week": 35}
        assert audit_logs[2].new_value == {"contract_hours_week": 40}

    run_db_test(run_test)


def test_payment_and_monthly_adjustment_mutations_create_audit_logs():
    async def run_test(session):
        company = await seed_company(session, "payment-audit")
        owner = await seed_worker(
            session,
            company.id,
            "payment-audit-owner",
            can_view_dashboard=True,
            access_role=WorkerAccessRole.COMPANY_OWNER.value,
            time_tracking_enabled=False,
        )
        worker = await seed_worker(session, company.id, "payment-audit-worker")
        payment = Payment(
            worker_id=worker.id,
            period_start=datetime(2026, 4, 1, tzinfo=timezone.utc),
            period_end=datetime(2026, 4, 30, tzinfo=timezone.utc),
            hours_paid=8,
            amount_paid=160,
            status=PaymentStatus.PENDING,
            payment_type="CONTRACT",
        )
        session.add(payment)
        await session.flush()

        await apply_audited_payment_update(
            session,
            payment=payment,
            performed_by_worker_id=owner.id,
            company_id=company.id,
            status=PaymentStatus.CONFIRMED,
            confirmed_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
        await apply_audited_payment_update(
            session,
            payment=payment,
            performed_by_worker_id=owner.id,
            company_id=company.id,
            amount_paid=175,
            period_end=datetime(2026, 5, 2, tzinfo=timezone.utc),
        )

        first_month = date(2026, 4, 1)
        adjustment = await upsert_monthly_adjustment(
            session,
            worker_id=worker.id,
            month=first_month,
            adjustment_minutes=30,
            reason="Night shift carry-over",
            performed_by_worker_id=owner.id,
            company_id=company.id,
        )
        updated_adjustment = await upsert_monthly_adjustment(
            session,
            worker_id=worker.id,
            month=first_month,
            adjustment_minutes=45,
            reason="Approved correction",
            performed_by_worker_id=owner.id,
            company_id=company.id,
        )
        await session.commit()

        payment_logs = (
            await session.execute(
                select(AuditLog)
                .where(
                    AuditLog.entity_type == "payment",
                    AuditLog.entity_id == payment.id,
                )
                .order_by(AuditLog.id.asc())
            )
        ).scalars().all()
        adjustment_logs = (
            await session.execute(
                select(AuditLog)
                .where(
                    AuditLog.entity_type == "monthly_adjustment",
                    AuditLog.entity_id == adjustment.id,
                )
                .order_by(AuditLog.id.asc())
            )
        ).scalars().all()
        stored_adjustment = await session.get(MonthlyAdjustment, adjustment.id)

        assert [log.action for log in payment_logs] == [
            "payment_status_updated",
            "payment_amount_date_updated",
        ]
        assert payment_logs[0].old_value["status"] == PaymentStatus.PENDING.value
        assert payment_logs[0].new_value["status"] == PaymentStatus.CONFIRMED.value
        assert payment_logs[1].old_value["amount_paid"] == 160
        assert payment_logs[1].new_value["amount_paid"] == 175
        assert payment_logs[1].old_value["period_end"] == "2026-04-30T00:00:00+00:00"
        assert payment_logs[1].new_value["period_end"] == "2026-05-02T00:00:00+00:00"

        assert adjustment.id == updated_adjustment.id
        assert stored_adjustment.adjustment_minutes == 45
        assert stored_adjustment.reason == "Approved correction"
        assert [log.action for log in adjustment_logs] == [
            "monthly_adjustment_created",
            "monthly_adjustment_updated",
        ]
        assert adjustment_logs[1].old_value == {
            "adjustment_minutes": 30,
            "reason": "Night shift carry-over",
        }
        assert adjustment_logs[1].new_value == {
            "adjustment_minutes": 45,
            "reason": "Approved correction",
        }

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


def test_legal_acceptance_events_store_versions_and_actions():
    async def run_test(session):
        company = await seed_company(session, "legal-events")
        actor = await seed_worker(session, company.id, "legal-events-worker")

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

        logs = (
            await session.execute(
                select(LegalAcceptanceLog)
                .where(LegalAcceptanceLog.company_id == company.id)
                .order_by(LegalAcceptanceLog.id.asc())
            )
        ).scalars().all()

        assert len(logs) == 6
        assert {log.action_type for log in logs if log.document_type in {"saas_terms", "avv_dpa"}} == {"accepted"}
        assert {
            log.action_type
            for log in logs
            if log.document_type in {"privacy_notice", "time_tracking_notice", "gps_site_presence_notice"}
        } == {"acknowledged"}
        assert all(log.document_version for log in logs)

    run_db_test(run_test)


def test_legal_acceptance_requires_document_version():
    async def run_test(session):
        company = await seed_company(session, "legal-version")
        actor = await seed_worker(session, company.id, "legal-version-worker")

        with pytest.raises(ValueError, match="document_version_required"):
            await record_legal_acceptance(
                session,
                actor_type="worker",
                actor_id=actor.id,
                company_id=company.id,
                document_type="privacy_notice",
                document_version=" ",
                action_type="acknowledged",
            )

    run_db_test(run_test)


def test_retention_hold_helpers_support_active_release_and_expiry():
    async def run_test(session):
        company = await seed_company(session, "hold-service")
        actor = await seed_worker(
            session,
            company.id,
            "hold-service-owner",
            can_view_dashboard=True,
            access_role=WorkerAccessRole.COMPANY_OWNER.value,
            time_tracking_enabled=False,
        )
        worker = await seed_worker(session, company.id, "hold-service-worker")

        expired_hold = await place_retention_hold(
            session,
            entity_type="time_event",
            entity_id=worker.id,
            hold_reason="Expired dispute review",
            hold_type="dispute_hold",
            company_id=company.id,
            held_by_worker_id=actor.id,
            hold_until=datetime(2026, 4, 1, tzinfo=timezone.utc),
        )
        active_hold = await place_retention_hold(
            session,
            entity_type="time_event",
            entity_id=worker.id,
            hold_reason="Open audit review",
            hold_type="audit_hold",
            company_id=company.id,
            held_by_worker_id=actor.id,
            hold_until=datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
        await session.commit()

        expired_count = await expire_retention_holds(
            session,
            now=datetime(2026, 4, 21, tzinfo=timezone.utc),
        )
        assert expired_count == 1
        assert await is_entity_on_retention_hold(
            session,
            entity_type="time_event",
            entity_id=worker.id,
            now=datetime(2026, 4, 21, tzinfo=timezone.utc),
        ) is True

        released_count = await release_retention_holds(
            session,
            entity_type="time_event",
            entity_id=worker.id,
            hold_type="audit_hold",
        )
        await session.commit()

        expired_hold_row = await session.get(RetentionHold, expired_hold.id)
        active_hold_row = await session.get(RetentionHold, active_hold.id)
        assert released_count == 1
        assert expired_hold_row.is_active is False
        assert active_hold_row.is_active is False
        assert active_hold_row.hold_reason == "Open audit review"
        assert active_hold_row.held_by_worker_id == actor.id
        assert active_hold_row.hold_until.isoformat().startswith("2026-05-01T00:00:00")
        assert await is_entity_on_retention_hold(
            session,
            entity_type="time_event",
            entity_id=worker.id,
            now=datetime(2026, 4, 21, tzinfo=timezone.utc),
        ) is False

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
