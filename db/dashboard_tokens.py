from __future__ import annotations


DASHBOARD_TOKEN_PREFIX = "dash_token:"
DASHBOARD_TOKEN_TTL_SECONDS = 1800


def dashboard_token_key(token: str) -> str:
    return f"{DASHBOARD_TOKEN_PREFIX}{token}"
