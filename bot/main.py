import asyncio
import sys
import os
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.redis import RedisStorage

# Must add project root to python path because this script is entrypoint
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.config import settings
from bot.logger import logger
from bot.middlewares import DBSessionMiddleware, I18nMiddleware
from bot.handlers import chief, worker, dashboard, admin

async def main():
    logger.info("Initializing SEK Zeiterfassung Bot...")
    
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    
    storage = RedisStorage.from_url(settings.REDIS_URL)
    dp = Dispatcher(storage=storage)
    
    # Register global middlewares
    dp.update.outer_middleware(DBSessionMiddleware())
    dp.update.middleware(I18nMiddleware())
    
    # Register routers (worker MUST intercept deep links first)
    dp.include_router(worker.router)
    dp.include_router(chief.router)
    dp.include_router(dashboard.router)
    dp.include_router(admin.router)
    
    logger.info("Starting polling...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
