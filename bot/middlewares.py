from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User
from db.database import SessionLocal
from db.models import Worker, Company
from sqlalchemy import select
from bot.config import settings
from bot.utils.scope import is_platform_identity_on_non_platform_bot

class DBSessionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        async with SessionLocal() as session:
            data["session"] = session
            return await handler(event, data)

class I18nMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        session = data.get("session")
        if not session:
            # Fallback if DB isn't loaded
            data["locale"] = "de"
            return await handler(event, data)
            
        # Get the telegram user from the event
        tg_user: User = data.get("event_from_user")
        if not tg_user:
            data["locale"] = "de"
            return await handler(event, data)

        if is_platform_identity_on_non_platform_bot(getattr(tg_user, "username", None)):
            data["locale"] = "de"
            data["current_worker"] = None
            return await handler(event, data)
            
        # Try to find a worker to set their locale
        import hashlib
        from db.security import hash_string
        tg_hash = hash_string(str(tg_user.id))
        
        stmt = select(Worker).where(Worker.telegram_id_hash == tg_hash)
        result = await session.execute(stmt)
        worker = result.scalar_one_or_none()
        
        if worker and worker.language:
            data["locale"] = worker.language.value
        else:
            data["locale"] = "de"

        # Also inject worker into data for easy access in handlers
        data["current_worker"] = worker
        
        return await handler(event, data)
