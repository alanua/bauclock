from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from enum import Enum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AuditLog


_SECRET_KEYS = {"token", "access_token", "refresh_token", "password", "secret", "api_key"}


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key)
            if normalized_key.casefold() in _SECRET_KEYS:
                continue
            result[normalized_key] = _json_safe(item)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def model_snapshot(entity: Any, *fields: str) -> dict[str, Any]:
    return {
        field: _json_safe(getattr(entity, field, None))
        for field in fields
    }


async def log_audit_event(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: int,
    action: str,
    old_value: Any = None,
    new_value: Any = None,
    performed_by_worker_id: int | None = None,
    company_id: int | None = None,
) -> AuditLog:
    event = AuditLog(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        old_value=_json_safe(old_value),
        new_value=_json_safe(new_value),
        performed_by_worker_id=performed_by_worker_id,
        company_id=company_id,
    )
    db.add(event)
    await db.flush()
    return event
