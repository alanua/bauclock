from __future__ import annotations

import secrets

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from access.legacy_policy import can_access_dashboard
from bot.config import settings
from bot.redis_cache import redis_client
from bot.utils.scope import is_platform_identity_on_non_platform_bot, platform_context_only_text
from db.dashboard_tokens import DASHBOARD_TOKEN_TTL_SECONDS, build_dashboard_token_payload, dashboard_token_key
from db.models import Worker


router = Router()


@router.message(Command("dashboard"))
async def cmd_dashboard(message: Message, current_worker: Worker, locale: str):
    from_user = getattr(message, "from_user", None)
    if is_platform_identity_on_non_platform_bot(getattr(from_user, "username", None)):
        await message.answer(platform_context_only_text(locale))
        return

    if not can_access_dashboard(current_worker):
        return

    token = secrets.token_urlsafe(32)
    await redis_client.setex(
        dashboard_token_key(token),
        DASHBOARD_TOKEN_TTL_SECONDS,
        build_dashboard_token_payload(
            worker_id=current_worker.id,
            company_id=current_worker.company_id,
        ),
    )

    url = f"{settings.APP_URL.rstrip('/')}/dashboard?token={token}"
    text = (
        "Ihr persoenliches Dashboard:\n\n"
        f"{url}\n\n"
        "Gueltig: 30 Minuten\n"
        "Nicht weitergeben."
        if locale == "de"
        else "Ваш персональний дашборд:\n\n"
        f"{url}\n\n"
        "Дійсний: 30 хвилин\n"
        "Не передавайте його."
    )
    await message.answer(text)
