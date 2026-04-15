import asyncio
import os
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock


os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault(
    "ENCRYPTION_KEY",
    "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff",
)
os.environ.setdefault("HASH_PEPPER", "test_pepper")


class Filter:
    def __getattr__(self, name):
        return self

    def __eq__(self, other):
        return self

    def startswith(self, *args, **kwargs):
        return self


class TelegramType:
    def __init__(self, *args, **kwargs):
        self.__dict__.update(kwargs)


class Router:
    def message(self, *args, **kwargs):
        return self._decorator

    def callback_query(self, *args, **kwargs):
        return self._decorator

    @staticmethod
    def _decorator(func):
        return func


def install_import_stubs() -> None:
    aiogram_module = sys.modules.setdefault("aiogram", ModuleType("aiogram"))
    aiogram_module.Router = Router
    aiogram_module.F = Filter()

    filters_module = sys.modules.setdefault("aiogram.filters", ModuleType("aiogram.filters"))
    filters_module.Command = TelegramType

    enums_module = sys.modules.setdefault("aiogram.enums", ModuleType("aiogram.enums"))
    enums_module.ParseMode = SimpleNamespace(HTML="HTML")

    types_module = sys.modules.setdefault("aiogram.types", ModuleType("aiogram.types"))
    for name in (
        "BufferedInputFile",
        "CallbackQuery",
        "InlineKeyboardButton",
        "InlineKeyboardMarkup",
        "Message",
        "KeyboardButton",
        "ReplyKeyboardMarkup",
        "ReplyKeyboardRemove",
    ):
        setattr(types_module, name, TelegramType)

    fsm_context_module = sys.modules.setdefault("aiogram.fsm.context", ModuleType("aiogram.fsm.context"))
    fsm_context_module.FSMContext = TelegramType
    fsm_state_module = sys.modules.setdefault("aiogram.fsm.state", ModuleType("aiogram.fsm.state"))
    fsm_state_module.State = type("State", (), {})
    fsm_state_module.StatesGroup = type("StatesGroup", (), {})

    redis_module = sys.modules.setdefault("bot.redis_cache", ModuleType("bot.redis_cache"))
    redis_module.redis_client = SimpleNamespace(setex=AsyncMock())

    qr_module = sys.modules.setdefault("bot.utils.qr", ModuleType("bot.utils.qr"))
    qr_module.generate_qr_code = lambda data: SimpleNamespace(getvalue=lambda: b"qr")

    pdf_module = sys.modules.setdefault("bot.utils.pdf", ModuleType("bot.utils.pdf"))
    pdf_module.generate_site_pdf = lambda *args, **kwargs: b"pdf"


install_import_stubs()

from bot.handlers import chief as chief_handler


class FakeState:
    def __init__(self):
        self.current_state = None
        self.clear = AsyncMock()

    async def set_state(self, state):
        self.current_state = state


class FakeSession:
    async def execute(self, stmt):
        return SimpleNamespace(scalar_one_or_none=lambda: None)


class FakeMessage:
    def __init__(self, username: str):
        self.text = "/start"
        self.from_user = SimpleNamespace(id=123456, username=username, full_name=username)
        self.answer = AsyncMock()


def test_platform_superadmin_start_does_not_enter_company_setup(monkeypatch):
    async def run_test():
        monkeypatch.setattr(chief_handler.bot_config, "PLATFORM_SUPERADMIN_USERNAMES", ["anoleksii"])
        monkeypatch.setattr(chief_handler.bot_config, "BOT_ROLE", "platform")

        state = FakeState()
        message = FakeMessage("AnOleksii")

        await chief_handler.cmd_start(
            message=message,
            state=state,
            session=FakeSession(),
            current_worker=None,
            locale="de",
        )

        message.answer.assert_awaited_once()
        assert "Mini App" in message.answer.await_args.args[0]
        assert state.current_state is None

    asyncio.run(run_test())


def test_uninvited_user_start_stays_public(monkeypatch):
    async def run_test():
        monkeypatch.setattr(chief_handler.bot_config, "PLATFORM_SUPERADMIN_USERNAMES", [])

        state = FakeState()
        message = FakeMessage("Visitor")

        await chief_handler.cmd_start(
            message=message,
            state=state,
            session=FakeSession(),
            current_worker=None,
            locale="de",
        )

        message.answer.assert_awaited_once()
        assert "Generalbau S.E.K. GmbH" in message.answer.await_args.args[0]
        assert state.current_state is None

    asyncio.run(run_test())
