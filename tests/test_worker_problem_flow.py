import asyncio
import importlib
import sys
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models import Base, BillingType, Company, Request, Worker, WorkerType


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
            engine = create_async_engine(f"sqlite+aiosqlite:///{Path(tmp_dir) / 'worker_problem.db'}")
            session_maker = async_sessionmaker(engine, expire_on_commit=False)
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with session_maker() as session:
                await test_coro(session)
            await engine.dispose()

    asyncio.run(runner())


async def seed_worker(session) -> Worker:
    company = Company(name="SEK", owner_telegram_id_enc="owner_enc", owner_telegram_id_hash="owner_hash")
    session.add(company)
    await session.flush()

    worker = Worker(
        company_id=company.id,
        telegram_id_enc="telegram_enc_worker",
        telegram_id_hash="telegram_hash_worker",
        full_name_enc="name_enc_worker",
        worker_type=WorkerType.FESTANGESTELLT,
        billing_type=BillingType.HOURLY,
        can_view_dashboard=False,
        is_active=True,
    )
    session.add(worker)
    await session.flush()
    return worker


async def list_requests(session) -> list[Request]:
    result = await session.execute(select(Request).order_by(Request.id))
    return list(result.scalars().all())


def test_opening_problem_flow():
    async def run_test():
        state = FakeState()
        worker = SimpleNamespace(id=1, company_id=1, is_active=True)
        message = FakeMessage("⚠️ Проблема")

        await worker_handler.start_report_problem(message, state, worker, "uk")

        message.answer.assert_awaited_once()
        assert state.current_state == worker_handler.ReportProblemStates.waiting_for_date
        assert state.clear_count == 1

    asyncio.run(run_test())


def test_choosing_problem_date_mode(monkeypatch):
    async def run_test():
        monkeypatch.setattr(worker_handler, "_problem_today", lambda: date(2026, 4, 10))
        state = FakeState()
        callback = FakeCallback("problem_date_yesterday")

        await worker_handler.choose_report_problem_date(callback, state, "uk")

        assert state.data["related_date"] == date(2026, 4, 9)
        assert state.current_state == worker_handler.ReportProblemStates.waiting_for_description
        callback.message.edit_text.assert_awaited_once()
        callback.answer.assert_awaited_once()

    asyncio.run(run_test())


def test_creating_problem_request_with_today(monkeypatch):
    async def run_test(session):
        monkeypatch.setattr(worker_handler, "_problem_today", lambda: date(2026, 4, 10))
        worker = await seed_worker(session)
        state = FakeState()
        await worker_handler.choose_report_problem_date(FakeCallback("problem_date_today"), state, "uk")
        await worker_handler.submit_report_problem(FakeMessage("Broken QR code"), state, session, worker, "uk")

        requests = await list_requests(session)
        assert len(requests) == 1
        assert requests[0].created_by_worker_id == worker.id
        assert requests[0].target_worker_id == worker.id
        assert requests[0].company_id == worker.company_id
        assert requests[0].related_date == date(2026, 4, 10)
        assert requests[0].text == "Broken QR code"
        assert state.current_state is None

    run_db_test(run_test)


def test_creating_problem_request_without_date():
    async def run_test(session):
        worker = await seed_worker(session)
        state = FakeState()
        await worker_handler.choose_report_problem_date(FakeCallback("problem_date_none"), state, "uk")
        await worker_handler.submit_report_problem(FakeMessage("Forgot checkout"), state, session, worker, "uk")

        requests = await list_requests(session)
        assert len(requests) == 1
        assert requests[0].related_date is None
        assert requests[0].target_worker_id == worker.id

    run_db_test(run_test)


def test_cancelling_problem_flow():
    async def run_test():
        state = FakeState()
        state.data["related_date"] = date(2026, 4, 10)
        callback = FakeCallback("problem_date_cancel")

        await worker_handler.choose_report_problem_date(callback, state, "uk")

        assert state.data == {}
        assert state.current_state is None
        assert state.clear_count == 1
        callback.message.edit_text.assert_awaited_once()
        callback.answer.assert_awaited_once()

    asyncio.run(run_test())


def test_empty_problem_text_does_not_create_request():
    async def run_test(session):
        worker = await seed_worker(session)
        state = FakeState()
        await state.update_data(related_date=date(2026, 4, 10))
        await state.set_state(worker_handler.ReportProblemStates.waiting_for_description)
        message = FakeMessage("   ")

        await worker_handler.submit_report_problem(message, state, session, worker, "uk")

        assert await list_requests(session) == []
        assert state.current_state == worker_handler.ReportProblemStates.waiting_for_description
        message.answer.assert_awaited_once()

    run_db_test(run_test)
