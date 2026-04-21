from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings
from api.services.retention_holds import active_retention_hold_entity_ids
from db.models import AuditLog, TimeEvent


@dataclass
class RetentionClassReport:
    name: str
    candidate_count: int = 0
    held_count: int = 0
    anonymized_count: int = 0
    deleted_count: int = 0
    errors: int = 0

    def as_dict(self) -> dict[str, int | str]:
        return {
            "name": self.name,
            "candidate_count": self.candidate_count,
            "held_count": self.held_count,
            "anonymized_count": self.anonymized_count,
            "deleted_count": self.deleted_count,
            "errors": self.errors,
        }


def _years_ago(years: int, *, now: datetime) -> datetime:
    return now - timedelta(days=365 * years)


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


async def _report_for_model(
    db: AsyncSession,
    *,
    name: str,
    entity_type: str,
    model,
    cutoff_column,
    years: int,
    now: datetime,
) -> RetentionClassReport:
    report = RetentionClassReport(name=name)
    cutoff = _years_ago(years, now=now)
    candidate_ids = list(
        (
            await db.execute(
                select(model.id).where(cutoff_column < cutoff)
            )
        ).scalars().all()
    )
    report.candidate_count = len(candidate_ids)
    held_ids = await _held_entity_ids(db, entity_type=entity_type, now=now)
    eligible_ids = [entity_id for entity_id in candidate_ids if entity_id not in held_ids]
    report.held_count = len(candidate_ids) - len(eligible_ids)

    if not settings.ENABLE_RETENTION or settings.RETENTION_DRY_RUN or not eligible_ids:
        return report

    if model is TimeEvent:
        await db.execute(
            delete(TimeEvent).where(TimeEvent.id.in_(eligible_ids))
        )
        report.deleted_count = len(eligible_ids)
        return report

    if model is AuditLog:
        await db.execute(
            delete(AuditLog).where(AuditLog.id.in_(eligible_ids))
        )
        report.deleted_count = len(eligible_ids)
        return report

    return report


async def run_retention_cycle(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    effective_now = now or datetime.now(timezone.utc)
    reports = [
        await _report_for_model(
            db,
            name="time_events",
            entity_type="time_event",
            model=TimeEvent,
            cutoff_column=TimeEvent.timestamp,
            years=settings.DATA_RETENTION_YEARS_TIME_EVENTS,
            now=effective_now,
        ),
        await _report_for_model(
            db,
            name="audit_logs",
            entity_type="audit_log",
            model=AuditLog,
            cutoff_column=AuditLog.created_at,
            years=settings.DATA_RETENTION_YEARS_AUDIT_LOGS,
            now=effective_now,
        ),
        RetentionClassReport(name="invites"),
        RetentionClassReport(name="transient_states"),
        RetentionClassReport(name="logs"),
    ]

    if settings.ENABLE_RETENTION and not settings.RETENTION_DRY_RUN:
        await db.commit()

    return {
        "enabled": bool(settings.ENABLE_RETENTION),
        "dry_run": bool(settings.RETENTION_DRY_RUN),
        "reports": [report.as_dict() for report in reports],
        "totals": {
            "candidate_count": sum(report.candidate_count for report in reports),
            "held_count": sum(report.held_count for report in reports),
            "anonymized_count": sum(report.anonymized_count for report in reports),
            "deleted_count": sum(report.deleted_count for report in reports),
            "errors": sum(report.errors for report in reports),
        },
    }
