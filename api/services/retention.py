from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatch
import hashlib
import inspect
import json
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings
from api.services.retention_holds import active_retention_hold_entity_ids
from db.dashboard_tokens import DASHBOARD_TOKEN_PREFIX, dashboard_token_is_expired
from db.models import AuditLog, TimeEvent, Worker


INVITE_RETENTION_PATTERNS = ("inv_*", "owner_inv_*", "partner_inv_*")
TRANSIENT_STATE_RETENTION_PATTERNS = ("fsm:*",)
DASHBOARD_TOKEN_RETENTION_PATTERN = f"{DASHBOARD_TOKEN_PREFIX}*"

INVITE_RETENTION_ENTITY_TYPE = "invite_artifact"
TRANSIENT_STATE_RETENTION_ENTITY_TYPE = "transient_state"
DASHBOARD_TOKEN_RETENTION_ENTITY_TYPE = "dashboard_token"


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

    def add_error(self, error_code: str) -> None:
        if self.errors is None:
            self.errors = []
        if error_code not in self.errors:
            self.errors.append(error_code)

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


def retention_key_entity_id(*, entity_type: str, key: str) -> int:
    digest = hashlib.sha256(f"{entity_type}:{key}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False) & 0x7FFFFFFFFFFFFFFF


def _years_ago(years: int, *, now: datetime) -> datetime:
    return now - timedelta(days=365 * years)


def _effective_now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def _effective_destructive_mode(*, destructive: bool | None) -> bool:
    if destructive is None:
        return bool(settings.ENABLE_RETENTION and not settings.RETENTION_DRY_RUN)
    return bool(destructive and settings.ENABLE_RETENTION)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


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


def _decode_redis_value(raw_value: Any) -> str | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, bytes):
        return raw_value.decode("utf-8")
    return str(raw_value)


def _load_json_value(raw_value: Any) -> dict[str, Any] | None:
    decoded = _decode_redis_value(raw_value)
    if decoded is None:
        return None
    try:
        parsed = json.loads(decoded)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


async def _redis_matching_keys(
    redis_client: Any,
    *,
    patterns: tuple[str, ...],
) -> list[str]:
    if redis_client is None:
        return []

    matched_keys: set[str] = set()
    scan_iter = getattr(redis_client, "scan_iter", None)
    if callable(scan_iter):
        for pattern in patterns:
            scan_result = scan_iter(match=pattern)
            if hasattr(scan_result, "__aiter__"):
                async for key in scan_result:
                    matched_keys.add(str(key))
            else:
                for key in await _maybe_await(scan_result):
                    matched_keys.add(str(key))
        return sorted(matched_keys)

    keys_method = getattr(redis_client, "keys", None)
    if callable(keys_method):
        for pattern in patterns:
            for key in await _maybe_await(keys_method(pattern)):
                matched_keys.add(str(key))
        return sorted(matched_keys)

    values = getattr(redis_client, "values", None)
    if isinstance(values, dict):
        for key in values:
            if any(fnmatch(str(key), pattern) for pattern in patterns):
                matched_keys.add(str(key))
    return sorted(matched_keys)


async def _redis_get(redis_client: Any, key: str) -> Any:
    get_method = getattr(redis_client, "get", None)
    if not callable(get_method):
        values = getattr(redis_client, "values", None)
        if isinstance(values, dict):
            return values.get(key)
        return None
    return await _maybe_await(get_method(key))


async def _redis_ttl(redis_client: Any, key: str) -> int | None:
    ttl_method = getattr(redis_client, "ttl", None)
    if callable(ttl_method):
        ttl_value = await _maybe_await(ttl_method(key))
        return int(ttl_value) if ttl_value is not None else None

    ttls = getattr(redis_client, "ttls", None)
    if isinstance(ttls, dict):
        ttl_value = ttls.get(key)
        return int(ttl_value) if ttl_value is not None else None
    return None


async def _redis_delete(redis_client: Any, key: str) -> int:
    delete_method = getattr(redis_client, "delete", None)
    if callable(delete_method):
        deleted = await _maybe_await(delete_method(key))
        if isinstance(deleted, bool):
            return 1 if deleted else 0
        return int(deleted or 0)

    values = getattr(redis_client, "values", None)
    if isinstance(values, dict) and key in values:
        values.pop(key, None)
        ttls = getattr(redis_client, "ttls", None)
        if isinstance(ttls, dict):
            ttls.pop(key, None)
        return 1
    return 0


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


async def _report_for_invites(
    db: AsyncSession,
    *,
    redis_client: Any,
    now: datetime,
    company_id: int | None,
    destructive: bool,
) -> RetentionClassReport:
    report = RetentionClassReport(name="invites")
    keys = await _redis_matching_keys(redis_client, patterns=INVITE_RETENTION_PATTERNS)
    if redis_client is None:
        report.add_error("redis_unavailable")
        return report

    held_ids = await _held_entity_ids(db, entity_type=INVITE_RETENTION_ENTITY_TYPE, now=now)
    deletable_keys: list[str] = []
    for key in keys:
        payload = _load_json_value(await _redis_get(redis_client, key)) or {}
        related_company_id = payload.get("company_id") or payload.get("general_contractor_company_id")
        if company_id is not None and int(related_company_id or 0) != company_id:
            continue

        ttl = await _redis_ttl(redis_client, key)
        if ttl is None:
            report.add_error("invite_ttl_unavailable")
            continue
        if ttl != -1:
            continue

        report.candidate_count += 1
        entity_id = retention_key_entity_id(entity_type=INVITE_RETENTION_ENTITY_TYPE, key=key)
        if entity_id in held_ids:
            report.held_count += 1
            continue
        deletable_keys.append(key)

    if not destructive or not deletable_keys:
        report.skipped_count = len(deletable_keys)
        return report

    for key in deletable_keys:
        report.deleted_count += await _redis_delete(redis_client, key)
    return report


async def _report_for_transient_states(
    db: AsyncSession,
    *,
    redis_client: Any,
    now: datetime,
    company_id: int | None,
    destructive: bool,
) -> RetentionClassReport:
    report = RetentionClassReport(name="transient_states")
    if redis_client is None:
        report.add_error("redis_unavailable")
        return report
    if company_id is not None:
        report.add_error("company_scope_not_supported")
        return report

    keys = await _redis_matching_keys(redis_client, patterns=TRANSIENT_STATE_RETENTION_PATTERNS)
    held_ids = await _held_entity_ids(db, entity_type=TRANSIENT_STATE_RETENTION_ENTITY_TYPE, now=now)
    deletable_keys: list[str] = []
    for key in keys:
        ttl = await _redis_ttl(redis_client, key)
        if ttl is None:
            report.add_error("transient_state_ttl_unavailable")
            continue
        if ttl != -1:
            continue

        report.candidate_count += 1
        entity_id = retention_key_entity_id(entity_type=TRANSIENT_STATE_RETENTION_ENTITY_TYPE, key=key)
        if entity_id in held_ids:
            report.held_count += 1
            continue
        deletable_keys.append(key)

    if not destructive or not deletable_keys:
        report.skipped_count = len(deletable_keys)
        return report

    for key in deletable_keys:
        report.deleted_count += await _redis_delete(redis_client, key)
    return report


async def _report_for_dashboard_tokens(
    db: AsyncSession,
    *,
    redis_client: Any,
    now: datetime,
    company_id: int | None,
    destructive: bool,
) -> RetentionClassReport:
    report = RetentionClassReport(name="dashboard_tokens")
    if redis_client is None:
        report.add_error("redis_unavailable")
        return report

    keys = await _redis_matching_keys(redis_client, patterns=(DASHBOARD_TOKEN_RETENTION_PATTERN,))
    held_ids = await _held_entity_ids(db, entity_type=DASHBOARD_TOKEN_RETENTION_ENTITY_TYPE, now=now)
    deletable_keys: list[str] = []
    for key in keys:
        raw_value = await _redis_get(redis_client, key)
        payload = _load_json_value(raw_value) or {}
        payload_company_id = payload.get("company_id")
        if company_id is not None and int(payload_company_id or 0) != company_id:
            continue

        ttl = await _redis_ttl(redis_client, key)
        if ttl is None:
            report.add_error("dashboard_token_ttl_unavailable")
            continue

        token_expired = False
        try:
            token_expired = dashboard_token_is_expired(raw_value, now=now)
        except ValueError:
            token_expired = True

        if ttl != -1 and not token_expired:
            continue

        report.candidate_count += 1
        entity_id = retention_key_entity_id(entity_type=DASHBOARD_TOKEN_RETENTION_ENTITY_TYPE, key=key)
        if entity_id in held_ids:
            report.held_count += 1
            continue
        deletable_keys.append(key)

    if not destructive or not deletable_keys:
        report.skipped_count = len(deletable_keys)
        return report

    for key in deletable_keys:
        report.deleted_count += await _redis_delete(redis_client, key)
    return report


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
    redis_client: Any | None = None,
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
        await _report_for_invites(
            db,
            redis_client=redis_client,
            now=effective_now,
            company_id=company_id,
            destructive=destructive_mode,
        ),
        await _report_for_transient_states(
            db,
            redis_client=redis_client,
            now=effective_now,
            company_id=company_id,
            destructive=destructive_mode,
        ),
        await _report_for_dashboard_tokens(
            db,
            redis_client=redis_client,
            now=effective_now,
            company_id=company_id,
            destructive=destructive_mode,
        ),
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
