from bot.config import settings
from bot.utils.access import normalize_username


def is_platform_identity_username(username: str | None) -> bool:
    return normalize_username(username or "") in settings.PLATFORM_SUPERADMIN_USERNAMES


def is_platform_identity_on_non_platform_bot(username: str | None) -> bool:
    return is_platform_identity_username(username) and not settings.is_platform_bot


def platform_context_only_text(locale: str) -> str:
    platform_bot = settings.PLATFORM_BOT_USERNAME.lstrip("@")
    if locale == "de":
        return f"Dieser Plattform- und persoenliche Bereich ist nur in @{platform_bot} verfuegbar."
    return f"This platform and personal area is only available in @{platform_bot}."
