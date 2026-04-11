import asyncio
import importlib
import sys
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.calendar_service import create_calendar_event
from db.models import (
    Base,
    BillingType,
    CalendarEventType,
    Company,
    Worker,
    WorkerType,
)


class Filter:
    def __getattr__(self, name):
        return self

    def __eq__(self, other):
        return self

    def startswith(self, *args, **kwargs):
        return self

    def in_(self, *args, **kwargs):
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

    types_module = sys.modules.setdefault("aiogram.types", ModuleType("aiogram.types"))
    for name in (
        "Message",
        "CallbackQuery",
        "InlineKeyboardMarkup",
        "InlineKeyboardButton",
        "ReplyKeyboardMarkup",
        "KeyboardButton",
        "ReplyKeyboardRemove",
    ):
        setattr(types_module, name, TelegramType)

    fsm_context_module = sys.modules.setdefault("aiogram.fsm.context", ModuleType("aiogram.fsm.context"))
    fsm_context_module.FSMContext = TelegramType
    fsm_state_module = sys.modules.setdefault("aiogram.fsm.state", ModuleType("aiogram.fsm.state"))
    fsm_state_module.State = type("State", (), {})
    fsm_state_module.StatesGroup = type("StatesGroup", (), {})

    redis_module = sys.modules.setdefault("bot.redis_cache", ModuleType("bot.redis_cache"))
    redis_module.redis_client = SimpleNamespace(get=AsyncMock(), delete=AsyncMock())


install_import_stubs()
worker_handler = importlib.import_module("bot.handlers.worker")


class FakeState:
    def __init__(self):
        self.data = {}
        self.current_state = None
        self.clear_count = 0

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def get_data(self):
        return dict(self.data)

    async def set_state(self, state):
        self.current_state = state

    async def clear(self):
        self.data.clear()
        self.current_state = None
        self.clear_count += 1


class FakeMessage:
    def __init__(self, text: str | None = None):
        self.text = text
        self.answer = AsyncMock()


class FakeCallback:
    def __init__(self, data: str):
        self.data = data
        self.answer = AsyncMock()
        self.message = SimpleNamespace(edit_text=AsyncMock())


def run_db_test(test_coro):
    async def runner():
        with TemporaryDirectory() as tmp_dir:
            engine = create_async_engine(f"sqlite+aiosqlite:///{Path(tmp_dir) / 'worker_calendar.db'}")
            session_maker = async_sessionmaker(engine, expire_on_commit=False)
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with session_maker() as session:
                await test_coro(session)
            await engine.dispose()

    asyncio.run(runner())


async def seed_company(session) -> Company:
    company = Company(name="SEK", owner_telegram_id_enc="owner_enc", owner_telegram_id_hash="owner_hash")
    session.add(company)
    await session.flush()
    return company


async def seed_worker(
    session,
    company_id: int,
    suffix: str,
    *,
    can_view_dashboard: bool = False,
) -> Worker:
    worker = Worker(
        company_id=company_id,
        telegram_id_enc=f"telegram_enc_{suffix}",
        telegram_id_hash=f"telegram_hash_{suffix}",
        full_name_enc=f"name_enc_{suffix}",
        worker_type=WorkerType.FESTANGESTELLT,
        billing_type=BillingType.HOURLY,
        can_view_dashboard=can_view_dashboard,
        is_active=True,
    )
    session.add(worker)
    await session.flush()
    return worker


async def seed_manager_and_worker(session):
    company = await seed_company(session)
    manager = await seed_worker(session, company.id, "manager", can_view_dashboard=True)
    worker = await seed_worker(session, company.id, "worker")
    return manager, worker


def test_open_calendar_flow():
    async def run_test():
        state = FakeState()
        worker = SimpleNamespace(id=1, company_id=1, is_active=True)
        message = FakeMessage("📅 Календар")

        await worker_handler.start_calendar_view(message, state, worker, "uk")

        message.answer.assert_awaited_once()
        assert state.current_state == worker_handler.CalendarViewStates.waiting_for_date_choice
        assert state.clear_count == 1

    asyncio.run(run_test())


def test_view_today(monkeypatch):
    async def run_test(session):
        monkeypatch.setattr(worker_handler, "_calendar_today", lambda: date(2026, 5, 6))
        manager, worker = await seed_manager_and_worker(session)
        await create_calendar_event(
            session,
            manager_worker=manager,
            event_type=CalendarEventType.PUBLIC_HOLIDAY,
            date_from=date(2026, 5, 6),
            date_to=date(2026, 5, 6),
            comment="Державне свято",
        )
        state = FakeState()
        callback = FakeCallback("calendar_date_today")

        await worker_handler.choose_calendar_view_date(callback, state, session, worker, "uk")

        callback.message.edit_text.assert_awaited_once()
        rendered = callback.message.edit_text.await_args.args[0]
        assert "Свято" in rendered
        assert "06.05.2026" in rendered
        assert "Державне свято" in rendered
        assert state.current_state is None
        callback.answer.assert_awaited_once()

    run_db_test(run_test)


def test_view_manual_date_with_one_event():
    async def run_test(session):
        manager, worker = await seed_manager_and_worker(session)
        await create_calendar_event(
            session,
            manager_worker=manager,
            worker_id=worker.id,
            event_type=CalendarEventType.VACATION,
            date_from=date(2026, 5, 4),
            date_to=date(2026, 5, 8),
            comment="Погоджено",
        )
        state = FakeState()
        callback = FakeCallback("calendar_date_custom")

        await worker_handler.choose_calendar_view_date(callback, state, session, worker, "uk")
        message = FakeMessage("06.05.2026")
        await worker_handler.submit_calendar_manual_date(message, state, session, worker, "uk")

        message.answer.assert_awaited_once()
        rendered = message.answer.await_args.args[0]
        assert "Відпустка" in rendered
        assert "04.05.2026 - 08.05.2026" in rendered
        assert "Погоджено" in rendered
        assert state.current_state is None

    run_db_test(run_test)


def test_view_date_with_no_events(monkeypatch):
    async def run_test(session):
        monkeypatch.setattr(worker_handler, "_calendar_today", lambda: date(2026, 5, 7))
        _, worker = await seed_manager_and_worker(session)
        state = FakeState()
        callback = FakeCallback("calendar_date_today")

        await worker_handler.choose_calendar_view_date(callback, state, session, worker, "uk")

        callback.message.edit_text.assert_awaited_once()
        rendered = callback.message.edit_text.await_args.args[0]
        assert "нічого не зафіксовано" in rendered.lower()

    run_db_test(run_test)


def test_invalid_manual_date_input():
    async def run_test(session):
        _, worker = await seed_manager_and_worker(session)
        state = FakeState()
        await state.set_state(worker_handler.CalendarViewStates.waiting_for_manual_date)
        message = FakeMessage("2026-05-06")

        await worker_handler.submit_calendar_manual_date(message, state, session, worker, "uk")

        message.answer.assert_awaited_once()
        assert "Невірна дата" in message.answer.await_args.args[0]
        assert state.current_state == worker_handler.CalendarViewStates.waiting_for_manual_date

    run_db_test(run_test)


def test_cancel_calendar_flow():
    async def run_test(session):
        _, worker = await seed_manager_and_worker(session)
        state = FakeState()
        callback = FakeCallback("calendar_date_cancel")

        await worker_handler.choose_calendar_view_date(callback, state, session, worker, "uk")

        assert state.data == {}
        assert state.current_state is None
        assert state.clear_count == 1
        callback.message.edit_text.assert_awaited_once()
        callback.answer.assert_awaited_once()

    run_db_test(run_test)
