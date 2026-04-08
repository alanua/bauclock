from __future__ import annotations

import secrets

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import settings
from bot.redis_cache import redis_client
from db.dashboard_tokens import DASHBOARD_TOKEN_TTL_SECONDS, dashboard_token_key
from db.models import Worker


router = Router()


@router.message(Command("dashboard"))
async def cmd_dashboard(message: Message, current_worker: Worker, locale: str):
    if not current_worker or not current_worker.is_active or not current_worker.can_view_dashboard:
        return

    token = secrets.token_urlsafe(32)
    await redis_client.setex(
        dashboard_token_key(token),
        DASHBOARD_TOKEN_TTL_SECONDS,
        str(current_worker.id),
    )

    url = f"{settings.APP_URL.rstrip('/')}/dashboard?token={token}"
    text = (
        "Ihr persoenliches Dashboard:\n\n"
        f"{url}\n\n"
        "Gueltig: 30 Minuten\n"
        "Nicht weitergeben."
        if locale == "de"
        else "Your personal dashboard:\n\n"
        f"{url}\n\n"
        "Valid for 30 minutes.\n"
        "Do not share it."
    )
    await message.answer(text)
