from __future__ import annotations

import json
from datetime import datetime, timezone


DASHBOARD_TOKEN_PREFIX = "dash_token:"
DASHBOARD_TOKEN_TTL_SECONDS = 1800


def dashboard_token_key(token: str) -> str:
    return f"{DASHBOARD_TOKEN_PREFIX}{token}"


def build_dashboard_token_payload(*, worker_id: int, company_id: int) -> str:
    return json.dumps(
        {
            "worker_id": int(worker_id),
            "company_id": int(company_id),
            "issued_at": datetime.now(timezone.utc).isoformat(),
        }
    )


def parse_dashboard_token_payload(raw_value: str | bytes | None) -> dict[str, int]:
    if raw_value is None:
        raise ValueError("dashboard_token_missing")
    if isinstance(raw_value, bytes):
        raw_value = raw_value.decode("utf-8")
    payload = json.loads(str(raw_value))
    worker_id = payload.get("worker_id")
    company_id = payload.get("company_id")
    if worker_id is None or company_id is None:
        raise ValueError("dashboard_token_invalid")
    return {
        "worker_id": int(worker_id),
        "company_id": int(company_id),
    }
