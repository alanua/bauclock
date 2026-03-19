from aiogram import Bot

async def send_telegram_message(telegram_id: int, text: str, bot_token: str):
    bot = Bot(token=bot_token)
    try:
        await bot.send_message(chat_id=telegram_id, text=text)
    finally:
        await bot.session.close()

async def send_telegram_document(telegram_id: int, document: bytes, filename: str, caption: str, bot_token: str):
    from aiogram.types import BufferedInputFile
    bot = Bot(token=bot_token)
    try:
        file = BufferedInputFile(document, filename=filename)
        await bot.send_document(chat_id=telegram_id, document=file, caption=caption)
    finally:
        await bot.session.close()
