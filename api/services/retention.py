from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings
from api.services.retention_holds import active_retention_hold_entity_ids
from db.models import AuditLog, TimeEvent, Worker


@dataclass
class RetentionClassReport:
    name: str
    candidate_count: int = 0
    held_count: int = 0
    skipped_count: int = 0
    eligible_for_anonymization: int = 0
    anonymized_count: int = 0
    deleted_count: int = 0
    errors: list[str] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "candidate_count": self.candidate_count,
            "held_count": self.held_count,
            "skipped_count": self.skipped_count,
            "eligible_for_anonymization": self.eligible_for_anonymization,
            "anonymized_count": self.anonymized_count,
            "deleted_count": self.deleted_count,
            "errors": list(self.errors or []),
        }


def _years_ago(years: int, *, now: datetime) -> datetime:
    return now - timedelta(days=365 * years)


def _effective_now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def _effective_destructive_mode(*, destructive: bool | None) -> bool:
    if destructive is None:
        return bool(settings.ENABLE_RETENTION and not settings.RETENTION_DRY_RUN)
    return bool(destructive and settings.ENABLE_RETENTION)


async def _held_entity_ids(
    db: AsyncSession,
    *,
    entity_type: str,
    now: datetime,
) -> set[int]:
    return await active_retention_hold_entity_ids(
        db,
        entity_type=entity_type,
        now=now,
    )


async def _candidate_time_event_ids(
    db: AsyncSession,
    *,
    cutoff: datetime,
    company_id: int | None,
) -> list[int]:
    stmt = (
        select(TimeEvent.id)
        .join(Worker, Worker.id == TimeEvent.worker_id)
        .where(TimeEvent.timestamp < cutoff)
    )
    if company_id is not None:
        stmt = stmt.where(Worker.company_id == company_id)
    return list((await db.execute(stmt)).scalars().all())


async def _candidate_audit_log_ids(
    db: AsyncSession,
    *,
    cutoff: datetime,
    company_id: int | None,
) -> list[int]:
    stmt = select(AuditLog.id).where(AuditLog.created_at < cutoff)
    if company_id is not None:
        stmt = stmt.where(AuditLog.company_id == company_id)
    return list((await db.execute(stmt)).scalars().all())


async def _report_for_time_events(
    db: AsyncSession,
    *,
    now: datetime,
    company_id: int | None,
    destructive: bool,
) -> RetentionClassReport:
    report = RetentionClassReport(name="time_events")
    cutoff = _years_ago(settings.DATA_RETENTION_YEARS_TIME_EVENTS, now=now)
    candidate_ids = await _candidate_time_event_ids(
        db,
        cutoff=cutoff,
        company_id=company_id,
    )
    report.candidate_count = len(candidate_ids)
    held_ids = await _held_entity_ids(db, entity_type="time_event", now=now)
    eligible_ids = [entity_id for entity_id in candidate_ids if entity_id not in held_ids]
    report.held_count = len(candidate_ids) - len(eligible_ids)
    report.eligible_for_anonymization = len(eligible_ids)

    if not destructive or not eligible_ids:
        report.skipped_count = len(eligible_ids)
        return report

    await db.execute(delete(TimeEvent).where(TimeEvent.id.in_(eligible_ids)))
    report.deleted_count = len(eligible_ids)
    return report


async def _report_for_audit_logs(
    db: AsyncSession,
    *,
    now: datetime,
    company_id: int | None,
    destructive: bool,
) -> RetentionClassReport:
    report = RetentionClassReport(name="audit_logs")
    cutoff = _years_ago(settings.DATA_RETENTION_YEARS_AUDIT_LOGS, now=now)
    candidate_ids = await _candidate_audit_log_ids(
        db,
        cutoff=cutoff,
        company_id=company_id,
    )
    report.candidate_count = len(candidate_ids)
    held_ids = await _held_entity_ids(db, entity_type="audit_log", now=now)
    eligible_ids = [entity_id for entity_id in candidate_ids if entity_id not in held_ids]
    report.held_count = len(candidate_ids) - len(eligible_ids)

    if not destructive or not eligible_ids:
        report.skipped_count = len(eligible_ids)
        return report

    await db.execute(delete(AuditLog).where(AuditLog.id.in_(eligible_ids)))
    report.deleted_count = len(eligible_ids)
    return report


def _placeholder_report(name: str) -> RetentionClassReport:
    return RetentionClassReport(name=name)


def _reports_to_by_class(reports: list[RetentionClassReport]) -> dict[str, dict[str, Any]]:
    return {
        report.name: report.as_dict()
        for report in reports
    }


def _totals(reports: list[RetentionClassReport]) -> dict[str, int]:
    return {
        "candidate_count": sum(report.candidate_count for report in reports),
        "held_count": sum(report.held_count for report in reports),
        "skipped_count": sum(report.skipped_count for report in reports),
        "eligible_for_anonymization": sum(report.eligible_for_anonymization for report in reports),
        "anonymized_count": sum(report.anonymized_count for report in reports),
        "deleted_count": sum(report.deleted_count for report in reports),
        "errors": sum(len(report.errors or []) for report in reports),
    }


async def run_retention_cycle(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    company_id: int | None = None,
    destructive: bool | None = None,
) -> dict[str, Any]:
    effective_now = _effective_now(now)
    destructive_mode = _effective_destructive_mode(destructive=destructive)
    reports = [
        await _report_for_time_events(
            db,
            now=effective_now,
            company_id=company_id,
            destructive=destructive_mode,
        ),
        await _report_for_audit_logs(
            db,
            now=effective_now,
            company_id=company_id,
            destructive=destructive_mode,
        ),
        _placeholder_report("invites"),
        _placeholder_report("transient_states"),
        _placeholder_report("logs"),
    ]

    if destructive_mode:
        await db.commit()

    by_class = _reports_to_by_class(reports)
    return {
        "enabled": bool(settings.ENABLE_RETENTION),
        "company_id": company_id,
        "mode": "destructive" if destructive_mode else "dry_run",
        "dry_run": not destructive_mode,
        "destructive_requested": bool(destructive),
        "destructive_executed": destructive_mode,
        "by_class": by_class,
        "reports": [by_class[name] for name in by_class],
        "totals": _totals(reports),
    }
