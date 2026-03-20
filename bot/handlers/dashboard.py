from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import Worker

router = Router()

@router.message(Command("dashboard"))
async def cmd_dashboard(message: Message, current_worker: Worker, session: AsyncSession):
    # Silent for non-admins - no response at all
    if not current_worker or not current_worker.can_view_dashboard:
        return
    
    import secrets
    from bot.config import settings
    from bot.redis_client import redis
    
    token = secrets.token_urlsafe(32)
    await redis.setex(f"dash_token:{token}", 1800, str(current_worker.id))
    
    from db.security import decrypt_string
    name = decrypt_string(current_worker.full_name_enc)
    url = f"{settings.APP_URL}/dashboard?token={token}"
    
    text = (
        f"📊 Ihr persönliches Dashboard:\n\n"
        f"{url}\n\n"
        f"⏱ Gültig: 30 Minuten\n"
        f"🔒 Nicht weitergeben!"
    )
    await message.answer(text)
