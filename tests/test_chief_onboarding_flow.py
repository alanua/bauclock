import asyncio
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


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
    redis_module.redis_client = SimpleNamespace(setex=AsyncMock(), get=AsyncMock(), delete=AsyncMock())

    qr_module = sys.modules.setdefault("bot.utils.qr", ModuleType("bot.utils.qr"))
    qr_module.generate_qr_code = lambda data: SimpleNamespace(getvalue=lambda: b"qr")

    pdf_module = sys.modules.setdefault("bot.utils.pdf", ModuleType("bot.utils.pdf"))
    pdf_module.generate_site_pdf = lambda *args, **kwargs: b"pdf"


install_import_stubs()

from bot.handlers import chief as chief_handler
from db.models import (
    Base,
    BillingType,
    Company,
    CompanyPublicProfile,
    Site,
    SitePartnerCompany,
    Worker,
    WorkerAccessRole,
    WorkerType,
)
from db.security import hash_string


class FakeState:
    def __init__(self):
        self.data = {}
        self.current_state = None

    async def set_state(self, state):
        self.current_state = state

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def get_data(self):
        return dict(self.data)

    async def clear(self):
        self.data.clear()
        self.current_state = None


class FakeSession:
    async def scalar(self, stmt):
        return None

    async def execute(self, stmt):
        return SimpleNamespace(scalar_one_or_none=lambda: None)


class FakeMessage:
    def __init__(self, username: str):
        self.text = "/start"
        self.from_user = SimpleNamespace(id=123456, username=username, full_name=username)
        self.answer = AsyncMock()


def run_db_test(test_coro):
    async def runner():
        with TemporaryDirectory() as tmp_dir:
            engine = create_async_engine(f"sqlite+aiosqlite:///{Path(tmp_dir) / 'chief_onboarding.db'}")
            session_maker = async_sessionmaker(engine, expire_on_commit=False)
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with session_maker() as session:
                await test_coro(session)
            await engine.dispose()

    asyncio.run(runner())


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


def test_platform_identity_on_sek_bot_does_not_enter_personal_context(monkeypatch):
    async def run_test():
        monkeypatch.setattr(chief_handler.bot_config, "PLATFORM_SUPERADMIN_USERNAMES", ["anoleksii"])
        monkeypatch.setattr(chief_handler.bot_config, "BOT_ROLE", "dedicated_client")
        monkeypatch.setattr(chief_handler.bot_config, "BOT_USERNAME", "SEKbaubot")
        monkeypatch.setattr(chief_handler.bot_config, "PLATFORM_BOT_USERNAME", "gewerbebot")

        state = FakeState()
        message = FakeMessage("AnOleksii")
        current_worker = SimpleNamespace(is_active=True, can_view_dashboard=True)

        await chief_handler.cmd_start(
            message=message,
            state=state,
            session=FakeSession(),
            current_worker=current_worker,
            locale="de",
        )

        assert state.current_state is None
        assert "@gewerbebot" in message.answer.await_args.args[0]
        assert "dashboard" not in message.answer.await_args.args[0].casefold()

    asyncio.run(run_test())


def test_platform_superadmin_can_create_owner_invite(monkeypatch):
    async def run_test():
        redis_stub = SimpleNamespace(setex=AsyncMock())
        monkeypatch.setattr(chief_handler, "redis_client", redis_stub)
        monkeypatch.setattr(chief_handler.bot_config, "PLATFORM_SUPERADMIN_USERNAMES", ["anoleksii"])
        monkeypatch.setattr(chief_handler.bot_config, "BOT_ROLE", "platform")
        monkeypatch.setattr(chief_handler.bot_config, "DEDICATED_CLIENT_BOT_USERNAME", "SEKbaubot")
        monkeypatch.setattr(chief_handler.bot_config, "SHARED_CLIENT_BOT_USERNAME", "bauuhrbot")

        state = FakeState()
        message = FakeMessage("AnOleksii")
        message.text = "/owner_invite Alpha Bau"

        await chief_handler.cmd_owner_invite(message=message, state=state, locale="de")

        redis_stub.setex.assert_awaited_once()
        token = redis_stub.setex.await_args.args[0]
        payload = json.loads(redis_stub.setex.await_args.args[2])
        assert token.startswith("owner_inv_")
        assert payload["company_name"] == "Alpha Bau"
        assert payload["target_bot_role"] == "shared_client"
        assert payload["target_bot_username"] == "bauuhrbot"
        assert "bauuhrbot" in message.answer.await_args.args[0]
        assert state.current_state is None

    asyncio.run(run_test())


def test_platform_superadmin_routes_sek_owner_invite_to_dedicated_bot(monkeypatch):
    async def run_test():
        redis_stub = SimpleNamespace(setex=AsyncMock())
        monkeypatch.setattr(chief_handler, "redis_client", redis_stub)
        monkeypatch.setattr(chief_handler.bot_config, "PLATFORM_SUPERADMIN_USERNAMES", ["anoleksii"])
        monkeypatch.setattr(chief_handler.bot_config, "BOT_ROLE", "platform")
        monkeypatch.setattr(chief_handler.bot_config, "DEDICATED_CLIENT_BOT_USERNAME", "SEKbaubot")
        monkeypatch.setattr(chief_handler.bot_config, "SHARED_CLIENT_BOT_USERNAME", "bauuhrbot")

        state = FakeState()
        message = FakeMessage("AnOleksii")
        message.text = "/owner_invite Generalbau S.E.K. GmbH"

        await chief_handler.cmd_owner_invite(message=message, state=state, locale="de")

        redis_stub.setex.assert_awaited_once()
        payload = json.loads(redis_stub.setex.await_args.args[2])
        assert payload["target_bot_role"] == "dedicated_client"
        assert payload["target_bot_username"] == "SEKbaubot"
        assert "SEKbaubot" in message.answer.await_args.args[0]
        assert "bauuhrbot" not in message.answer.await_args.args[0]

    asyncio.run(run_test())


def test_owner_invite_acceptance_starts_minimal_onboarding(monkeypatch):
    async def run_test():
        token = "owner_inv_test"
        redis_stub = SimpleNamespace(
            get=AsyncMock(
                return_value=json.dumps(
                    {
                        "company_name": "Alpha Bau",
                        "target_bot_role": "shared_client",
                        "target_bot_username": "bauuhrbot",
                    }
                )
            ),
        )
        monkeypatch.setattr(chief_handler, "redis_client", redis_stub)
        monkeypatch.setattr(chief_handler.bot_config, "BOT_USERNAME", "bauuhrbot")
        monkeypatch.setattr(chief_handler.bot_config, "BOT_ROLE", "shared_client")

        state = FakeState()
        message = FakeMessage("new_owner")
        message.text = f"/start {token}"

        await chief_handler.cmd_start(
            message=message,
            state=state,
            session=FakeSession(),
            current_worker=None,
            locale="de",
        )

        redis_stub.get.assert_awaited_once_with(token)
        assert state.data["owner_invite_token"] == token
        assert state.data["owner_invite_data"]["company_name"] == "Alpha Bau"
        assert state.current_state == chief_handler.OwnerAlphaOnboardingStates.waiting_for_owner_name
        assert "vollstaendigen Namen" in message.answer.await_args.args[0]

    asyncio.run(run_test())


def test_owner_invite_acceptance_stays_on_shared_client_bot(monkeypatch):
    async def run_test():
        redis_stub = SimpleNamespace(
            get=AsyncMock(
                return_value=json.dumps(
                    {
                        "company_name": "Alpha Bau",
                        "target_bot_role": "shared_client",
                        "target_bot_username": "bauuhrbot",
                    }
                )
            )
        )
        monkeypatch.setattr(chief_handler, "redis_client", redis_stub)
        monkeypatch.setattr(chief_handler.bot_config, "BOT_USERNAME", "SEKbaubot")
        monkeypatch.setattr(chief_handler.bot_config, "BOT_ROLE", "dedicated_client")
        monkeypatch.setattr(chief_handler.bot_config, "DEDICATED_CLIENT_BOT_USERNAME", "SEKbaubot")
        monkeypatch.setattr(chief_handler.bot_config, "SHARED_CLIENT_BOT_USERNAME", "bauuhrbot")

        state = FakeState()
        message = FakeMessage("new_owner")
        message.text = "/start owner_inv_wrong_bot"

        await chief_handler.cmd_start(
            message=message,
            state=state,
            session=FakeSession(),
            current_worker=None,
            locale="de",
        )

        redis_stub.get.assert_awaited_once_with("owner_inv_wrong_bot")
        assert state.current_state is None
        assert "@bauuhrbot" in message.answer.await_args.args[0]

    asyncio.run(run_test())


def test_sek_owner_invite_acceptance_stays_on_dedicated_client_bot(monkeypatch):
    async def run_test():
        token = "owner_inv_sek"
        redis_stub = SimpleNamespace(
            get=AsyncMock(
                return_value=json.dumps(
                    {
                        "company_name": "Generalbau S.E.K. GmbH",
                        "target_bot_role": "dedicated_client",
                        "target_bot_username": "SEKbaubot",
                    }
                )
            )
        )
        monkeypatch.setattr(chief_handler, "redis_client", redis_stub)
        monkeypatch.setattr(chief_handler.bot_config, "BOT_USERNAME", "SEKbaubot")
        monkeypatch.setattr(chief_handler.bot_config, "BOT_ROLE", "dedicated_client")
        monkeypatch.setattr(chief_handler.bot_config, "DEDICATED_CLIENT_BOT_USERNAME", "SEKbaubot")
        monkeypatch.setattr(chief_handler.bot_config, "SHARED_CLIENT_BOT_USERNAME", "bauuhrbot")

        state = FakeState()
        message = FakeMessage("sek_owner")
        message.text = f"/start {token}"

        await chief_handler.cmd_start(
            message=message,
            state=state,
            session=FakeSession(),
            current_worker=None,
            locale="de",
        )

        redis_stub.get.assert_awaited_once_with(token)
        assert state.data["owner_invite_data"]["target_bot_role"] == "dedicated_client"
        assert state.current_state == chief_handler.OwnerAlphaOnboardingStates.waiting_for_owner_name

    asyncio.run(run_test())


def test_owner_company_name_requires_legal_form_choice():
    async def run_test():
        state = FakeState()
        await state.update_data(owner_invite_data={"company_name": "Alpha Bau"})
        message = FakeMessage("owner")
        message.text = "/skip"

        await chief_handler.process_owner_alpha_company_name(
            message=message,
            state=state,
            locale="de",
        )

        assert state.data["company_name"] == "Alpha Bau"
        assert state.current_state == chief_handler.OwnerAlphaOnboardingStates.waiting_for_company_legal_form
        assert "Rechtsform" in message.answer.await_args.args[0]
        assert message.answer.await_args.kwargs["reply_markup"] is not None

    asyncio.run(run_test())


def test_owner_legal_form_choice_moves_to_company_address():
    async def run_test():
        state = FakeState()
        callback = SimpleNamespace(
            data="legal_form_gmbh",
            message=SimpleNamespace(edit_text=AsyncMock(), answer=AsyncMock()),
            answer=AsyncMock(),
        )

        await chief_handler.process_owner_alpha_company_legal_form(
            callback=callback,
            state=state,
            locale="de",
        )

        assert state.data["company_legal_form"] == "gmbh"
        assert state.current_state == chief_handler.OwnerAlphaOnboardingStates.waiting_for_company_address
        callback.message.edit_text.assert_awaited_once()
        callback.message.answer.assert_awaited_once()
        assert "Firmenadresse" in callback.message.answer.await_args.args[0]

    asyncio.run(run_test())


def test_owner_alpha_onboarding_creates_owner_company_and_public_profile(monkeypatch):
    async def run_test(session):
        redis_stub = SimpleNamespace(delete=AsyncMock())
        monkeypatch.setattr(chief_handler, "redis_client", redis_stub)
        state = FakeState()
        await state.update_data(
            owner_invite_token="owner_inv_alpha",
            owner_name="Alpha Owner",
            company_name="Alpha Bau",
            company_legal_form="gmbh",
            company_address="Alpha Strasse 1",
        )
        message = FakeMessage("owner")
        message.text = "owner@example.test"

        await chief_handler.process_owner_alpha_company_email(
            message=message,
            state=state,
            session=session,
            locale="de",
        )

        company = (await session.execute(select(Company))).scalar_one()
        owner = (await session.execute(select(Worker))).scalar_one()
        profile = (await session.execute(select(CompanyPublicProfile))).scalar_one()

        assert company.name == "Alpha Bau"
        assert company.email == "owner@example.test"
        assert owner.company_id == company.id
        assert owner.access_role == WorkerAccessRole.COMPANY_OWNER.value
        assert owner.can_view_dashboard is True
        assert owner.time_tracking_enabled is False
        assert profile.company_id == company.id
        assert profile.company_name == "Alpha Bau"
        assert profile.slug == "alpha-bau"
        assert profile.subtitle == "Bauunternehmen - GmbH"
        assert "(GmbH)" in profile.about_text
        redis_stub.delete.assert_awaited_once_with("owner_inv_alpha")
        assert "Owner-Zugang ist aktiv" in message.answer.await_args.args[0]

    run_db_test(run_test)


def test_owner_add_site_creates_site_with_alpha_role(monkeypatch):
    async def run_test(session):
        company = Company(
            name="Alpha Bau",
            owner_telegram_id_enc="owner_enc",
            owner_telegram_id_hash="owner_hash",
        )
        session.add(company)
        await session.flush()

        state = FakeState()
        await state.update_data(site_name="Alpha Baustelle", site_address="Baustrasse 2")
        callback = SimpleNamespace(
            data="site_role_general_contractor",
            message=SimpleNamespace(edit_text=AsyncMock()),
            answer=AsyncMock(),
        )
        current_worker = SimpleNamespace(
            company_id=company.id,
            is_active=True,
            can_view_dashboard=True,
        )
        send_qr = AsyncMock()
        monkeypatch.setattr(chief_handler, "_send_site_qr", send_qr)

        await chief_handler.process_add_site_role(
            callback=callback,
            state=state,
            session=session,
            current_worker=current_worker,
            locale="de",
        )

        site = (await session.execute(select(Site))).scalar_one()
        assert site.company_id == company.id
        assert site.name == "Alpha Baustelle"
        assert site.address == "Baustrasse 2"
        assert site.description == "Rolle: Generalunternehmer (Alpha)"
        assert site.qr_token.startswith("site_")
        send_qr.assert_awaited_once()

    run_db_test(run_test)


def test_sek_owner_can_create_site_specific_subcontractor_company_invite(monkeypatch):
    async def run_test(session):
        redis_stub = SimpleNamespace(setex=AsyncMock())
        monkeypatch.setattr(chief_handler, "redis_client", redis_stub)
        monkeypatch.setattr(chief_handler.bot_config, "BOT_ROLE", "dedicated_client")
        monkeypatch.setattr(chief_handler.bot_config, "BOT_USERNAME", "SEKbaubot")
        monkeypatch.setattr(chief_handler.bot_config, "DEDICATED_CLIENT_BOT_USERNAME", "SEKbaubot")
        monkeypatch.setattr(chief_handler.bot_config, "PLATFORM_BOT_USERNAME", "gewerbebot")

        company = Company(
            name="Generalbau S.E.K. GmbH",
            owner_telegram_id_enc="owner_enc",
            owner_telegram_id_hash="owner_hash",
        )
        session.add(company)
        await session.flush()
        site = Site(
            company_id=company.id,
            name=chief_handler.SEK_ALPHA_SITE_NAME,
            qr_token="site_alpha",
            is_active=True,
        )
        owner = Worker(
            company_id=company.id,
            telegram_id_enc="owner_enc",
            telegram_id_hash="owner_hash",
            full_name_enc="owner_name",
            worker_type=WorkerType.FESTANGESTELLT,
            billing_type=BillingType.HOURLY,
            access_role=WorkerAccessRole.COMPANY_OWNER.value,
            can_view_dashboard=True,
            time_tracking_enabled=False,
            is_active=True,
        )
        session.add_all([site, owner])
        await session.flush()

        state = FakeState()
        message = FakeMessage("sek_owner")
        message.text = "/invite_subcontractor"

        await chief_handler.cmd_invite_subcontractor_company(
            message=message,
            state=state,
            session=session,
            current_worker=owner,
            locale="de",
        )

        redis_stub.setex.assert_awaited_once()
        token, ttl, raw_payload = redis_stub.setex.await_args.args
        payload = json.loads(raw_payload)
        assert token.startswith("partner_inv_")
        assert ttl == chief_handler.PARTNER_COMPANY_INVITE_TTL_SECONDS
        assert payload["invite_type"] == "subcontractor_company_site"
        assert payload["general_contractor_company_id"] == company.id
        assert payload["site_id"] == site.id
        assert payload["site_name"] == chief_handler.SEK_ALPHA_SITE_NAME
        assert payload["relationship_role"] == "subcontractor"
        assert payload["target_bot_role"] == "platform"
        assert payload["target_bot_username"] == "gewerbebot"
        assert "gewerbebot" in message.answer.await_args.args[0]
        assert chief_handler.SEK_ALPHA_SITE_NAME in message.answer.await_args.args[0]
        assert state.current_state is None

    run_db_test(run_test)


def test_platform_owner_accepts_partner_invite_with_minimal_gewerbe_name(monkeypatch):
    async def run_test(session):
        token = "partner_inv_alpha"
        redis_payload = {
            "invite_type": "subcontractor_company_site",
            "general_contractor_company_id": 1,
            "site_id": 1,
            "site_name": chief_handler.SEK_ALPHA_SITE_NAME,
            "relationship_role": "subcontractor",
            "target_bot_role": "platform",
            "target_bot_username": "gewerbebot",
            "created_by_worker_id": None,
        }
        redis_stub = SimpleNamespace(
            get=AsyncMock(return_value=json.dumps(redis_payload)),
            delete=AsyncMock(),
        )
        monkeypatch.setattr(chief_handler, "redis_client", redis_stub)
        monkeypatch.setattr(chief_handler.bot_config, "BOT_ROLE", "platform")
        monkeypatch.setattr(chief_handler.bot_config, "BOT_USERNAME", "gewerbebot")
        monkeypatch.setattr(chief_handler.bot_config, "PLATFORM_BOT_USERNAME", "gewerbebot")
        monkeypatch.setattr(chief_handler.bot_config, "PLATFORM_SUPERADMIN_USERNAMES", ["anoleksii"])

        sek_company = Company(
            name="Generalbau S.E.K. GmbH",
            owner_telegram_id_enc="sek_owner_enc",
            owner_telegram_id_hash="sek_owner_hash",
        )
        session.add(sek_company)
        await session.flush()
        site = Site(
            id=1,
            company_id=sek_company.id,
            name=chief_handler.SEK_ALPHA_SITE_NAME,
            qr_token="site_alpha",
            is_active=True,
        )
        session.add(site)
        await session.commit()

        state = FakeState()
        message = FakeMessage("AnOleksii")
        message.text = f"/start {token}"

        await chief_handler.cmd_start(
            message=message,
            state=state,
            session=session,
            current_worker=None,
            locale="de",
        )

        redis_stub.get.assert_awaited_once_with(token)
        assert state.current_state == chief_handler.PartnerCompanyInviteStates.waiting_for_company_name
        assert "eigenes Gewerbe" in message.answer.await_args.args[0]

        message.text = "AOV Gewerbe"
        await chief_handler.process_partner_company_invite_company_name(
            message=message,
            state=state,
            session=session,
            locale="de",
        )

        companies = (await session.execute(select(Company).order_by(Company.id))).scalars().all()
        partner_company = companies[1]
        owner = (
            await session.execute(
                select(Worker).where(
                    Worker.company_id == partner_company.id,
                    Worker.access_role == WorkerAccessRole.COMPANY_OWNER.value,
                )
            )
        ).scalar_one()
        partnership = (await session.execute(select(SitePartnerCompany))).scalar_one()
        sites = (await session.execute(select(Site))).scalars().all()

        assert partner_company.name == "AOV Gewerbe"
        assert partner_company.owner_telegram_id_hash == hash_string(str(message.from_user.id))
        assert owner.worker_type == WorkerType.GEWERBE
        assert owner.time_tracking_enabled is False
        assert owner.site_id is None
        assert partnership.site_id == site.id
        assert partnership.company_id == partner_company.id
        assert partnership.role == "subcontractor"
        assert len(sites) == 1
        redis_stub.delete.assert_awaited_once_with(token)
        assert state.current_state is None
        assert "kein neuer QR-Code" in message.answer.await_args.args[0]

    run_db_test(run_test)


def test_platform_owner_accepts_partner_invite_with_existing_own_company(monkeypatch):
    async def run_test(session):
        token = "partner_inv_existing"
        redis_payload = {
            "invite_type": "subcontractor_company_site",
            "general_contractor_company_id": 1,
            "site_id": 1,
            "site_name": chief_handler.SEK_ALPHA_SITE_NAME,
            "relationship_role": "subcontractor",
            "target_bot_role": "platform",
            "target_bot_username": "gewerbebot",
            "created_by_worker_id": None,
        }
        redis_stub = SimpleNamespace(
            get=AsyncMock(return_value=json.dumps(redis_payload)),
            delete=AsyncMock(),
        )
        monkeypatch.setattr(chief_handler, "redis_client", redis_stub)
        monkeypatch.setattr(chief_handler.bot_config, "BOT_ROLE", "platform")
        monkeypatch.setattr(chief_handler.bot_config, "BOT_USERNAME", "gewerbebot")
        monkeypatch.setattr(chief_handler.bot_config, "PLATFORM_SUPERADMIN_USERNAMES", ["anoleksii"])

        sek_company = Company(
            name="Generalbau S.E.K. GmbH",
            owner_telegram_id_enc="sek_owner_enc",
            owner_telegram_id_hash="sek_owner_hash",
        )
        own_company = Company(
            name="AOV Gewerbe",
            owner_telegram_id_enc="own_enc",
            owner_telegram_id_hash=hash_string("123456"),
        )
        session.add_all([sek_company, own_company])
        await session.flush()
        site = Site(
            id=1,
            company_id=sek_company.id,
            name=chief_handler.SEK_ALPHA_SITE_NAME,
            qr_token="site_alpha",
            is_active=True,
        )
        owner = Worker(
            company_id=own_company.id,
            telegram_id_enc="own_enc",
            telegram_id_hash=hash_string("123456"),
            full_name_enc="owner_name",
            worker_type=WorkerType.GEWERBE,
            billing_type=BillingType.HOURLY,
            access_role=WorkerAccessRole.COMPANY_OWNER.value,
            can_view_dashboard=True,
            time_tracking_enabled=False,
            is_active=True,
        )
        session.add_all([site, owner])
        await session.commit()

        state = FakeState()
        message = FakeMessage("AnOleksii")
        message.text = f"/start {token}"

        await chief_handler.cmd_start(
            message=message,
            state=state,
            session=session,
            current_worker=None,
            locale="de",
        )

        partnership = (await session.execute(select(SitePartnerCompany))).scalar_one()
        assert partnership.site_id == site.id
        assert partnership.company_id == own_company.id
        assert state.current_state is None
        redis_stub.delete.assert_awaited_once_with(token)
        assert "AOV Gewerbe" in message.answer.await_args.args[0]

    run_db_test(run_test)
