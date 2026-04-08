from __future__ import annotations

from collections.abc import Iterable


def normalize_username(username: str | None) -> str:
    return (username or "").strip().lstrip("@").casefold()


def normalize_usernames(usernames: Iterable[str] | None) -> list[str]:
    if not usernames:
        return []

    normalized = []
    for username in usernames:
        cleaned = normalize_username(username)
        if cleaned:
            normalized.append(cleaned)

    return normalized


def normalize_phone(phone: str | None) -> str:
    return "".join(character for character in (phone or "") if character.isdigit())
