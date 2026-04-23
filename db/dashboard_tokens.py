from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any


DASHBOARD_TOKEN_PREFIX = "dash_token:"
DASHBOARD_TOKEN_TTL_SECONDS = 1800


def dashboard_token_key(token: str) -> str:
    return f"{DASHBOARD_TOKEN_PREFIX}{token}"


def _load_dashboard_token_payload(raw_value: str | bytes | None) -> dict[str, Any]:
    if raw_value is None:
        raise ValueError("dashboard_token_missing")
    if isinstance(raw_value, bytes):
        raw_value = raw_value.decode("utf-8")
    return json.loads(str(raw_value))


def build_dashboard_token_payload(
    *,
    worker_id: int,
    company_id: int,
    issued_at: datetime | None = None,
) -> str:
    return json.dumps(
        {
            "worker_id": int(worker_id),
            "company_id": int(company_id),
            "issued_at": (issued_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
        }
    )


def parse_dashboard_token_payload(raw_value: str | bytes | None) -> dict[str, int]:
    payload = _load_dashboard_token_payload(raw_value)
    worker_id = payload.get("worker_id")
    company_id = payload.get("company_id")
    if worker_id is None or company_id is None:
        raise ValueError("dashboard_token_invalid")
    return {
        "worker_id": int(worker_id),
        "company_id": int(company_id),
    }


def dashboard_token_issued_at(raw_value: str | bytes | None) -> datetime | None:
    payload = _load_dashboard_token_payload(raw_value)
    issued_at = payload.get("issued_at")
    if issued_at in {None, ""}:
        return None
    try:
        parsed = datetime.fromisoformat(str(issued_at))
    except ValueError as exc:
        raise ValueError("dashboard_token_invalid") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def dashboard_token_is_expired(
    raw_value: str | bytes | None,
    *,
    now: datetime | None = None,
    ttl_seconds: int = DASHBOARD_TOKEN_TTL_SECONDS,
) -> bool:
    issued_at = dashboard_token_issued_at(raw_value)
    if issued_at is None:
        return False
    effective_now = now or datetime.now(timezone.utc)
    return effective_now - issued_at > timedelta(seconds=ttl_seconds)
