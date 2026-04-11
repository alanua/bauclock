from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import parse_qsl


class TelegramInitDataError(Exception):
    pass


def validate_telegram_init_data(
    init_data: str,
    *,
    bot_token: str,
    max_age_seconds: int = 86400,
    now: int | None = None,
) -> dict[str, Any]:
    normalized_init_data = (init_data or "").strip()
    normalized_bot_token = (bot_token or "").strip()
    if not normalized_init_data:
        raise TelegramInitDataError("missing_init_data")
    if not normalized_bot_token:
        raise TelegramInitDataError("missing_bot_token")

    pairs = dict(parse_qsl(normalized_init_data, keep_blank_values=True, strict_parsing=False))
    received_hash = pairs.pop("hash", "")
    if not received_hash:
        raise TelegramInitDataError("missing_hash")

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", normalized_bot_token.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash):
        raise TelegramInitDataError("invalid_hash")

    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError as exc:
        raise TelegramInitDataError("invalid_auth_date") from exc
    current_time = int(time.time()) if now is None else now
    if max_age_seconds > 0 and current_time - auth_date > max_age_seconds:
        raise TelegramInitDataError("expired_auth_date")

    try:
        user = json.loads(pairs.get("user", "{}"))
    except json.JSONDecodeError as exc:
        raise TelegramInitDataError("invalid_user") from exc
    if not isinstance(user, dict) or not user.get("id"):
        raise TelegramInitDataError("missing_user")

    return {
        "auth_date": auth_date,
        "query_id": pairs.get("query_id"),
        "user": user,
    }
