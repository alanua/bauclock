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

from db.models import Base, BillingType, Company, EventType, Request, Site, SitePartnerCompany, TimeEvent, Worker, WorkerAccessRole, WorkerType


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
    def __init__(self, text: str | None = None, username: str = "worker"):
        self.text = text
        self.from_user = SimpleNamespace(id=123456, username=username)
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


def test_worker_selects_private_time_action_before_qr_scan():
    async def run_test():
        state = FakeState()
        worker = SimpleNamespace(id=1, company_id=1, is_active=True, time_tracking_enabled=True)
        message = FakeMessage("Ankunft")

        await worker_handler.start_time_event_action(message, state, worker, "de")

        assert state.data["pending_event"] == EventType.CHECKIN.value
        assert state.current_state == worker_handler.TimeEventSelectionStates.waiting_for_site_qr
        message.answer.assert_awaited_once()

    asyncio.run(run_test())


def test_platform_identity_cannot_accept_worker_invite_on_client_bot(monkeypatch):
    async def run_test():
        state = FakeState()
        message = FakeMessage("/start inv_wrong_bot", username="AnOleksii")
        redis_stub = SimpleNamespace(get=AsyncMock())
        monkeypatch.setattr(worker_handler, "redis_client", redis_stub)
        monkeypatch.setattr(worker_handler, "is_platform_identity_on_non_platform_bot", lambda username: True)

        await worker_handler.cmd_start_invite(message, state, None, None, "de")

        redis_stub.get.assert_not_called()
        message.answer.assert_awaited_once()
        assert "@gewerbebot" in message.answer.await_args.args[0]

    asyncio.run(run_test())


def test_direct_site_qr_scan_without_pending_action_returns_public_info():
    async def run_test(session):
        company = Company(
            name="Generalbau S.E.K. GmbH",
            owner_telegram_id_enc="owner_enc",
            owner_telegram_id_hash="owner_hash",
        )
        session.add(company)
        await session.flush()
        session.add(
            Site(
                company_id=company.id,
                name="Objekt Brandenburg",
                description="Zufahrt ueber Tor 2.",
                address="Am Industriegelaende 3",
                qr_token="site_public",
                is_active=True,
            )
        )
        await session.commit()

        state = FakeState()
        worker = SimpleNamespace(id=1, company_id=company.id, is_active=True, time_tracking_enabled=True)
        message = FakeMessage("/start site_public")

        await worker_handler.cmd_start_site(message, state, session, worker, "de")

        message.answer.assert_awaited_once()
        answer_text = message.answer.await_args.args[0]
        assert "Generalbau S.E.K. GmbH" in answer_text
        assert "Objekt Brandenburg" in answer_text
        assert "Zufahrt ueber Tor 2." in answer_text
        assert "Standort" not in answer_text
        assert "Zeiterfassung" not in answer_text

    run_db_test(run_test)


def test_joined_gewerbe_worker_can_use_existing_sek_qr_for_checkin():
    async def run_test(session):
        sek_company = Company(
            name="Generalbau S.E.K. GmbH",
            owner_telegram_id_enc="sek_owner_enc",
            owner_telegram_id_hash="sek_owner_hash",
        )
        partner_company = Company(
            name="AOV Gewerbe",
            owner_telegram_id_enc="partner_owner_enc",
            owner_telegram_id_hash="partner_owner_hash",
        )
        session.add_all([sek_company, partner_company])
        await session.flush()
        site = Site(
            company_id=sek_company.id,
            name="Consum-Quartier",
            qr_token="site_shared",
            is_active=True,
        )
        session.add(site)
        await session.flush()
        worker = Worker(
            company_id=partner_company.id,
            site_id=site.id,
            telegram_id_enc="worker_enc",
            telegram_id_hash="worker_hash",
            full_name_enc="Partner Worker",
            worker_type=WorkerType.GEWERBE,
            billing_type=BillingType.HOURLY,
            can_view_dashboard=False,
            time_tracking_enabled=True,
            is_active=True,
        )
        session.add(worker)
        await session.flush()
        session.add(
            SitePartnerCompany(
                site_id=site.id,
                company_id=partner_company.id,
                role="subcontractor",
                is_active=True,
            )
        )
        await session.commit()

        state = FakeState()
        await state.update_data(pending_event=EventType.CHECKIN.value)
        message = FakeMessage("/start site_shared")

        await worker_handler.cmd_start_site(message, state, session, worker, "de")

        assert state.data["site_id"] == site.id
        assert "Standort" in message.answer.await_args.args[0]

        message.location = SimpleNamespace(latitude=52.0, longitude=13.0, horizontal_accuracy=5)
        await worker_handler.process_location(message, state, session, worker, "de")

        event = (await session.execute(select(TimeEvent))).scalar_one()
        assert event.worker_id == worker.id
        assert event.site_id == site.id
        assert worker.company_id == partner_company.id

    run_db_test(run_test)


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


def test_worker_invite_can_create_objektmanager_dashboard_access(monkeypatch):
    async def run_test(session):
        manager = await seed_worker(session)
        state = FakeState()
        await state.update_data(
            token="inv_objektmanager",
            invite_data={
                "company_id": manager.company_id,
                "name": "Site Manager",
                "worker_type": WorkerType.FESTANGESTELLT.value,
                "hourly_rate": 22,
                "contract_hours": 40,
                "created_by": manager.id,
                "access_role": WorkerAccessRole.OBJEKTMANAGER.value,
                "can_view_dashboard": True,
            },
        )
        redis_stub = SimpleNamespace(delete=AsyncMock())
        monkeypatch.setattr(worker_handler, "redis_client", redis_stub)
        callback = SimpleNamespace(
            from_user=SimpleNamespace(id=999888),
            message=SimpleNamespace(reply_markup=None, answer=AsyncMock(), edit_text=AsyncMock()),
        )

        await worker_handler.handle_language_selection(callback, state, session, "de")

        workers = (await session.execute(select(Worker).order_by(Worker.id))).scalars().all()
        created = workers[-1]
        assert created.company_id == manager.company_id
        assert created.access_role == WorkerAccessRole.OBJEKTMANAGER.value
        assert created.can_view_dashboard is True
        assert created.time_tracking_enabled is True
        redis_stub.delete.assert_awaited_once_with("inv_objektmanager")

    run_db_test(run_test)
