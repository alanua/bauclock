import json
import re
import urllib.parse
import uuid
from html import escape

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from access.legacy_policy import can_access_dashboard
from bot.config import settings as bot_config
from bot.keyboards.chief_kb import (
    LEGAL_FORM_OPTIONS,
    get_cancel_kb,
    get_company_legal_form_kb,
    get_objektmanager_flag_kb,
    get_site_role_kb,
    get_worker_type_kb,
)
from bot.redis_cache import redis_client
from bot.states.chief_states import (
    AddSiteStates,
    AddWorkerStates,
    ChiefRegistrationStates,
    OwnerAlphaOnboardingStates,
    PartnerCompanyInviteStates,
    PlatformOwnerInviteStates,
)
from bot.utils.access import normalize_phone, normalize_username
from bot.utils.owner_worker import ensure_company_owner_worker
from bot.utils.pdf import generate_site_pdf
from bot.utils.qr import generate_qr_code
from bot.utils.scope import is_platform_identity_on_non_platform_bot, platform_context_only_text
from db.models import (
    BillingType,
    Company,
    CompanyPublicProfile,
    Site,
    SitePartnerCompany,
    Worker,
    WorkerAccessRole,
    WorkerType,
)
from db.security import encrypt_string, hash_string

router = Router()
SEK_ALPHA_SITE_NAME = "Consum-Quartier, Steinstraße 22/23 in 14776 Brandenburg"
PARTNER_COMPANY_INVITE_TTL_SECONDS = 86400 * 7


def _as_text(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value or "")


def _message_username(message: Message) -> str:
    return normalize_username(getattr(message.from_user, "username", "") or "")


def _is_platform_superadmin(message: Message) -> bool:
    return (
        bot_config.is_platform_bot
        and _message_username(message) in bot_config.PLATFORM_SUPERADMIN_USERNAMES
    )


def _is_shared_client_bot() -> bool:
    current_bot = normalize_username(bot_config.BOT_USERNAME)
    shared_bot = normalize_username(bot_config.SHARED_CLIENT_BOT_USERNAME)
    return bot_config.BOT_ROLE == "shared_client" or (
        bool(current_bot) and current_bot == shared_bot
    )


def _is_dedicated_client_bot() -> bool:
    current_bot = normalize_username(bot_config.BOT_USERNAME)
    dedicated_bot = normalize_username(bot_config.DEDICATED_CLIENT_BOT_USERNAME)
    return bot_config.BOT_ROLE == "dedicated_client" or (
        bool(current_bot) and current_bot == dedicated_bot
    )


def _is_sek_company_name(company_name: str) -> bool:
    compact = re.sub(r"[^a-z0-9]+", "", (company_name or "").casefold())
    return compact in {"sek", "sekgmbh"} or compact.startswith("sek") or "generalbausek" in compact


def _owner_invite_target(company_name: str) -> tuple[str, str]:
    if _is_sek_company_name(company_name):
        return "dedicated_client", bot_config.DEDICATED_CLIENT_BOT_USERNAME.lstrip("@")
    return "shared_client", bot_config.SHARED_CLIENT_BOT_USERNAME.lstrip("@")


def _owner_invite_target_from_payload(invite_data: dict) -> tuple[str, str]:
    role = str(invite_data.get("target_bot_role") or "shared_client")
    username = str(invite_data.get("target_bot_username") or "").strip().lstrip("@")
    if role == "dedicated_client":
        return role, username or bot_config.DEDICATED_CLIENT_BOT_USERNAME.lstrip("@")
    return "shared_client", username or bot_config.SHARED_CLIENT_BOT_USERNAME.lstrip("@")


def _skip_value(text: str | None) -> bool:
    return (text or "").strip().lower() in {"/skip", "skip", "-"}


def _legal_form_label(value: str | None) -> str:
    labels = dict(LEGAL_FORM_OPTIONS)
    return labels.get(str(value or ""), "Sonstiges")


def _slug_base(company_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", company_name.lower()).strip("-")
    return slug[:48].strip("-") or "company"


async def _unique_company_slug(session: AsyncSession, company_name: str) -> str:
    base = _slug_base(company_name)
    slug = base
    suffix = 2
    while True:
        existing = await session.scalar(
            select(CompanyPublicProfile.id).where(CompanyPublicProfile.slug == slug)
        )
        if not existing:
            return slug
        suffix_text = f"-{suffix}"
        slug = f"{base[:64 - len(suffix_text)]}{suffix_text}"
        suffix += 1


def _owner_next_steps_text(company: Company, profile_slug: str | None, locale: str) -> str:
    public_url = f"{bot_config.APP_URL.rstrip('/')}/c/{profile_slug}" if profile_slug else ""
    lines = [
        f"Willkommen bei BauClock, {company.name}.",
        "",
        "Ihr Owner-Zugang ist aktiv.",
        "",
        "Empfohlene naechste Schritte:",
        "1. /add_worker - erste Person anlegen",
        "2. /add_site - erste Baustelle mit QR anlegen",
        "3. /dashboard - Management Home oeffnen",
    ]
    if locale != "de":
        lines = [
            f"Welcome to BauClock, {company.name}.",
            "",
            "Your owner access is active.",
            "",
            "Next steps:",
            "1. /add_worker - create the first person",
            "2. /add_site - create the first site and QR",
            "3. /dashboard - open management home",
        ]
    if public_url:
        lines.extend(["", f"Oeffentliche Firmenseite: {public_url}" if locale == "de" else f"Public company page: {public_url}"])
    return "\n".join(lines)


def _site_description_for_role(role: str) -> str:
    label = {"general_contractor": "Generalunternehmer"}.get(role, role)
    return f"Rolle: {label} (Alpha)"


def _safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_") or "bauclock"


async def _get_alpha_sek_site(session: AsyncSession, company_id: int) -> Site | None:
    return await session.scalar(
        select(Site).where(
            Site.company_id == company_id,
            Site.is_active.is_(True),
            Site.name == SEK_ALPHA_SITE_NAME,
        )
    )


async def _send_site_qr(message: Message, company: Company, site: Site, locale: str) -> None:
    bot_info = await message.bot.get_me()
    bot_username = getattr(bot_info, "username", None) or bot_config.BOT_USERNAME
    tg_link = f"https://t.me/{bot_username}?start={site.qr_token}"
    safe_name = _safe_filename(site.name)

    qr_bio = generate_qr_code(tg_link)
    qr_file = BufferedInputFile(qr_bio.getvalue(), filename=f"qr_{safe_name}.png")
    pdf_bytes = generate_site_pdf(tg_link, company.name, site.name, site.address or "")
    pdf_file = BufferedInputFile(pdf_bytes, filename=f"BauClock_Aushang_{safe_name}.pdf")

    text = (
        f"Baustelle '{site.name}' erstellt.\n\n"
        "Der QR-Code ist fuer den Bot-Zeiterfassungsfluss bereit: Ankunft, Pause, Feierabend."
        if locale == "de"
        else f"Site '{site.name}' created.\n\nThe QR code is ready for the bot time flow."
    )
    pdf_caption = "Druckfertiges A4-PDF fuer die Baustelle." if locale == "de" else "Print-ready A4 PDF for the site."
    await message.answer_photo(qr_file, caption=text)
    await message.answer_document(pdf_file, caption=pdf_caption)


async def _create_owner_invite(message: Message, company_name: str, locale: str) -> None:
    clean_company_name = (company_name or "").strip()
    if not clean_company_name:
        await message.answer("Bitte einen Firmennamen angeben." if locale == "de" else "Please provide a company name.")
        return

    target_bot_role, target_bot_username = _owner_invite_target(clean_company_name)
    token = f"owner_inv_{uuid.uuid4().hex[:24]}"
    invite_data = {
        "company_name": clean_company_name,
        "created_by_username": _message_username(message),
        "target_bot_role": target_bot_role,
        "target_bot_username": target_bot_username,
    }
    await redis_client.setex(token, 86400 * 7, json.dumps(invite_data))

    invite_link = f"https://t.me/{target_bot_username}?start={token}"
    safe_company_name = escape(clean_company_name)
    safe_invite_link = escape(invite_link)
    text = (
        f"Owner-Einladung fuer {safe_company_name} erstellt.\n\n"
        f"{safe_invite_link}\n\n"
        "Gueltig: 7 Tage. Der Link ist einmalig fuer den ersten Company Owner."
        if locale == "de"
        else f"Owner invite for {safe_company_name} created.\n\n{safe_invite_link}\n\nValid: 7 days."
    )
    await message.answer(text)


async def _create_subcontractor_company_invite(
    message: Message,
    current_worker: Worker | None,
    session: AsyncSession,
    locale: str,
) -> None:
    if not current_worker or not can_access_dashboard(current_worker):
        await message.answer("Keine Berechtigung." if locale == "de" else "Access denied.")
        return
    if not _is_dedicated_client_bot():
        dedicated_bot_username = bot_config.DEDICATED_CLIENT_BOT_USERNAME.lstrip("@")
        await message.answer(
            f"Bitte diese Einladung in @{dedicated_bot_username} erstellen."
            if locale == "de"
            else f"Please create this invite in @{dedicated_bot_username}."
        )
        return

    site = await _get_alpha_sek_site(session, current_worker.company_id)
    if not site:
        await message.answer(
            "Die Alpha-Baustelle wurde nicht gefunden. Bitte zuerst die SEK-Baustelle pruefen."
            if locale == "de"
            else "The alpha site was not found. Please check the SEK site first."
        )
        return

    token = f"partner_inv_{uuid.uuid4().hex[:24]}"
    platform_bot_username = bot_config.PLATFORM_BOT_USERNAME.lstrip("@")
    invite_data = {
        "invite_type": "subcontractor_company_site",
        "general_contractor_company_id": current_worker.company_id,
        "site_id": site.id,
        "site_name": site.name,
        "relationship_role": "subcontractor",
        "target_bot_role": "platform",
        "target_bot_username": platform_bot_username,
        "created_by_worker_id": current_worker.id,
    }
    await redis_client.setex(token, PARTNER_COMPANY_INVITE_TTL_SECONDS, json.dumps(invite_data))

    invite_link = f"https://t.me/{platform_bot_username}?start={token}"
    safe_site_name = escape(site.name)
    safe_invite_link = escape(invite_link)
    text = (
        "Subunternehmer-Firmeneinladung erstellt.\n\n"
        f"Baustelle: {safe_site_name}\n"
        "Rolle: Subunternehmer\n\n"
        f"{safe_invite_link}\n\n"
        "Gueltig: 7 Tage. Der Link ist fuer den Beitritt einer Firma zu dieser Baustelle."
        if locale == "de"
        else (
            "Subcontractor company invite created.\n\n"
            f"Site: {safe_site_name}\n"
            "Role: subcontractor\n\n"
            f"{safe_invite_link}\n\n"
            "Valid: 7 days. This link joins one company to this site."
        )
    )
    await message.answer(text)


async def _get_owned_partner_company(
    session: AsyncSession,
    *,
    owner_telegram_id_hash: str,
    excluded_company_id: int | None,
) -> Company | None:
    stmt = select(Company).where(Company.owner_telegram_id_hash == owner_telegram_id_hash)
    if excluded_company_id is not None:
        stmt = stmt.where(Company.id != excluded_company_id)
    return await session.scalar(stmt.order_by(Company.id))


async def _ensure_partner_company_owner_worker(
    message: Message,
    session: AsyncSession,
    company: Company,
) -> Worker:
    return await ensure_company_owner_worker(message.from_user, session, company)


async def _create_owned_gewerbe_company(
    message: Message,
    session: AsyncSession,
    company_name: str,
) -> tuple[Company, Worker]:
    tg_id_str = str(message.from_user.id)
    company = Company(
        name=company_name,
        owner_telegram_id_enc=encrypt_string(tg_id_str),
        owner_telegram_id_hash=hash_string(tg_id_str),
    )
    session.add(company)
    await session.flush()

    owner = Worker(
        company_id=company.id,
        telegram_id_enc=encrypt_string(tg_id_str),
        telegram_id_hash=hash_string(tg_id_str),
        full_name_enc=encrypt_string(getattr(message.from_user, "full_name", None) or "Gewerbe Owner"),
        worker_type=WorkerType.GEWERBE,
        billing_type=BillingType.HOURLY,
        access_role=WorkerAccessRole.COMPANY_OWNER.value,
        can_view_dashboard=True,
        time_tracking_enabled=False,
        is_active=True,
        created_by=None,
    )
    session.add(owner)
    await session.flush()
    return company, owner


async def _accept_partner_company_invite(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    *,
    token: str,
    invite_data: dict,
    partner_company: Company,
    owner_worker: Worker,
    locale: str,
) -> None:
    site = await session.get(Site, invite_data.get("site_id"))
    if not site or not site.is_active:
        await state.clear()
        await message.answer(
            "Diese Baustellen-Einladung ist nicht mehr gueltig."
            if locale == "de"
            else "This site invite is no longer valid."
        )
        return

    existing = await session.scalar(
        select(SitePartnerCompany).where(
            SitePartnerCompany.site_id == site.id,
            SitePartnerCompany.company_id == partner_company.id,
            SitePartnerCompany.role == "subcontractor",
            SitePartnerCompany.is_active.is_(True),
        )
    )
    if not existing:
        session.add(
            SitePartnerCompany(
                site_id=site.id,
                company_id=partner_company.id,
                role="subcontractor",
                invited_by_worker_id=invite_data.get("created_by_worker_id"),
                accepted_by_worker_id=owner_worker.id,
                is_active=True,
            )
        )
        await session.flush()

    await redis_client.delete(token)
    await session.commit()
    await state.clear()
    await message.answer(
        f"{partner_company.name} ist jetzt als Subunternehmer mit {site.name} verbunden.\n\n"
        "Es wird kein neuer QR-Code erstellt. Ihr Gewerbe nutzt den bestehenden SEK-Baustellen-QR."
        if locale == "de"
        else (
            f"{partner_company.name} is now connected to {site.name} as subcontractor.\n\n"
            "No new QR code is created. Your company uses the existing SEK site QR."
        )
    )


async def _start_partner_company_invite_acceptance(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    token: str,
    locale: str,
) -> None:
    if not bot_config.is_platform_bot:
        platform_bot_username = bot_config.PLATFORM_BOT_USERNAME.lstrip("@")
        await message.answer(
            f"Bitte oeffnen Sie diese Gewerbe-Einladung in @{platform_bot_username}."
            if locale == "de"
            else f"Please open this company invite in @{platform_bot_username}."
        )
        return
    if not _is_platform_superadmin(message):
        await state.clear()
        await message.answer("Keine Berechtigung." if locale == "de" else "Access denied.")
        return

    invite_json = await redis_client.get(token)
    if not invite_json:
        await state.clear()
        await message.answer(
            "Diese Gewerbe-Einladung ist ungueltig oder abgelaufen."
            if locale == "de"
            else "This company invite is invalid or expired."
        )
        return

    invite_data = json.loads(_as_text(invite_json))
    if invite_data.get("invite_type") != "subcontractor_company_site":
        await state.clear()
        await message.answer(
            "Diese Gewerbe-Einladung kann nicht verarbeitet werden."
            if locale == "de"
            else "This company invite cannot be processed."
        )
        return

    tg_hash = hash_string(str(message.from_user.id))
    partner_company = await _get_owned_partner_company(
        session,
        owner_telegram_id_hash=tg_hash,
        excluded_company_id=invite_data.get("general_contractor_company_id"),
    )
    if partner_company:
        owner_worker = await _ensure_partner_company_owner_worker(message, session, partner_company)
        await _accept_partner_company_invite(
            message,
            state,
            session,
            token=token,
            invite_data=invite_data,
            partner_company=partner_company,
            owner_worker=owner_worker,
            locale=locale,
        )
        return

    await state.update_data(partner_invite_token=token, partner_invite_data=invite_data)
    await message.answer(
        "Wie heisst Ihr eigenes Gewerbe, das als Subunternehmer beitreten soll?"
        if locale == "de"
        else "What is the name of your own company joining as subcontractor?"
    )
    await state.set_state(PartnerCompanyInviteStates.waiting_for_company_name)


async def _start_owner_invite_acceptance(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    current_worker: Worker | None,
    token: str,
    locale: str,
) -> None:
    invite_json = await redis_client.get(token)
    if not invite_json:
        await message.answer(
            "Dieser Owner-Einladungslink ist ungueltig oder abgelaufen."
            if locale == "de"
            else "This owner invite is invalid or expired."
        )
        return

    invite_data = json.loads(_as_text(invite_json))
    target_bot_role, target_bot_username = _owner_invite_target_from_payload(invite_data)
    opened_in_target_bot = (
        _is_dedicated_client_bot()
        if target_bot_role == "dedicated_client"
        else _is_shared_client_bot()
    )
    if not opened_in_target_bot:
        await message.answer(
            f"Bitte oeffnen Sie diese Owner-Einladung in @{target_bot_username}."
            if locale == "de"
            else f"Please open this owner invite in @{target_bot_username}."
        )
        return

    if current_worker:
        await message.answer(
            "Sie sind bereits in BauClock registriert. Oeffnen Sie /dashboard fuer Ihren Bereich."
            if locale == "de"
            else "You are already registered in BauClock. Open /dashboard."
        )
        return

    tg_hash = hash_string(str(message.from_user.id))
    existing_company = await session.scalar(
        select(Company.id).where(Company.owner_telegram_id_hash == tg_hash)
    )
    if existing_company:
        await message.answer(
            "Ihr Owner-Zugang existiert bereits. Bitte starten Sie erneut mit /start."
            if locale == "de"
            else "Your owner access already exists. Please start again with /start."
        )
        return

    await state.update_data(owner_invite_token=token, owner_invite_data=invite_data)
    await message.answer(
        "Willkommen bei BauClock. Bitte senden Sie zuerst Ihren vollstaendigen Namen."
        if locale == "de"
        else "Welcome to BauClock. Please send your full name first."
    )
    await state.set_state(OwnerAlphaOnboardingStates.waiting_for_owner_name)


@router.callback_query(F.data == "cancel_action")
async def cancel_action(callback: CallbackQuery, state: FSMContext, locale: str):
    await state.clear()
    await callback.message.edit_text("Aktion abgebrochen." if locale == "de" else "Action cancelled.")
    await callback.answer()


@router.message(Command("start"))
async def cmd_start(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    current_worker: Worker | None,
    locale: str,
):
    parts = (message.text or "").split(maxsplit=1)
    if is_platform_identity_on_non_platform_bot(getattr(message.from_user, "username", None)):
        await state.clear()
        await message.answer(platform_context_only_text(locale))
        return

    if len(parts) == 2:
        token = parts[1].strip()
        if token.startswith("owner_inv_"):
            await _start_owner_invite_acceptance(message, state, session, current_worker, token, locale)
            return
        if token.startswith("partner_inv_"):
            await _start_partner_company_invite_acceptance(message, state, session, token, locale)
            return
        if token.startswith("site_") or token.startswith("inv_"):
            return

    if current_worker:
        text = (
            "Willkommen zurueck bei BauClock. Nutzen Sie /dashboard fuer die Uebersicht oder /add_worker fuer Mitarbeiter."
            if locale == "de"
            else "Welcome back to BauClock. Use /dashboard or /add_worker."
        )
        await message.answer(text)
        return

    tg_hash = hash_string(str(message.from_user.id))
    company = await session.scalar(select(Company).where(Company.owner_telegram_id_hash == tg_hash))
    if company:
        await ensure_company_owner_worker(message.from_user, session, company)
        await message.answer(
            f"Willkommen zurueck, Owner von {company.name}!"
            if locale == "de"
            else f"Welcome back, owner of {company.name}!"
        )
        return

    if _is_platform_superadmin(message):
        text = (
            "BauClock Plattformzugang ist aktiv.\n\n"
            "Owner-Einladung erstellen:\n"
            "/owner_invite Firmenname\n\n"
            "Oder Mini App oeffnen fuer den geschuetzten Bereich."
            if locale == "de"
            else "BauClock platform access is active.\n\nCreate an owner invite:\n/owner_invite Company name\n\nOr open the Mini App."
        )
        await message.answer(text)
        return

    normalized_username = _message_username(message)
    if normalized_username in bot_config.ADMIN_USERNAMES:
        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Telefonnummer teilen", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        await message.answer(
            f"Willkommen, {message.from_user.username or message.from_user.full_name}! Admin-Zugang erkannt.\n\n"
            "Bitte verifizieren Sie sich mit Ihrer Telefonnummer:",
            reply_markup=keyboard,
        )
        await state.set_state(ChiefRegistrationStates.waiting_for_owner_phone)
        return

    await message.answer(
        "Generalbau S.E.K. GmbH\n"
        "Wir bauen Zukunft - Stein auf Stein.\n\n"
        "Generalbau - Trockenbau - Putz & Maler - Daemmung\n\n"
        "Am Industriegelaende 3\n"
        "14772 Brandenburg an der Havel\n"
        "generalbau-sek.de"
    )


@router.message(Command("owner_invite"))
async def cmd_owner_invite(message: Message, state: FSMContext, locale: str):
    if not _is_platform_superadmin(message):
        await message.answer("Keine Berechtigung." if locale == "de" else "Access denied.")
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) == 2 and parts[1].strip():
        await _create_owner_invite(message, parts[1].strip(), locale)
        await state.clear()
        return

    await message.answer(
        "Fuer welche Firma soll der erste Owner eingeladen werden?"
        if locale == "de"
        else "Which company should receive the first owner invite?"
    )
    await state.set_state(PlatformOwnerInviteStates.waiting_for_company_name)


@router.message(Command("invite_subcontractor"))
async def cmd_invite_subcontractor_company(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    current_worker: Worker | None,
    locale: str,
):
    await state.clear()
    await _create_subcontractor_company_invite(message, current_worker, session, locale)


@router.message(PlatformOwnerInviteStates.waiting_for_company_name)
async def process_owner_invite_company_name(message: Message, state: FSMContext, locale: str):
    if not _is_platform_superadmin(message):
        await state.clear()
        await message.answer("Keine Berechtigung." if locale == "de" else "Access denied.")
        return

    await _create_owner_invite(message, (message.text or "").strip(), locale)
    await state.clear()


@router.message(PartnerCompanyInviteStates.waiting_for_company_name)
async def process_partner_company_invite_company_name(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    locale: str,
):
    if not bot_config.is_platform_bot or not _is_platform_superadmin(message):
        await state.clear()
        await message.answer("Keine Berechtigung." if locale == "de" else "Access denied.")
        return

    company_name = (message.text or "").strip()
    if not company_name or company_name.startswith("/"):
        await message.answer(
            "Bitte senden Sie den Namen Ihres Gewerbes."
            if locale == "de"
            else "Please send your company name."
        )
        return

    data = await state.get_data()
    token = data.get("partner_invite_token")
    invite_data = data.get("partner_invite_data") or {}
    if not token or invite_data.get("invite_type") != "subcontractor_company_site":
        await state.clear()
        await message.answer(
            "Diese Gewerbe-Einladung ist nicht mehr bereit. Bitte den Link erneut oeffnen."
            if locale == "de"
            else "This company invite is no longer ready. Please open the link again."
        )
        return

    partner_company, owner_worker = await _create_owned_gewerbe_company(message, session, company_name)
    await _accept_partner_company_invite(
        message,
        state,
        session,
        token=token,
        invite_data=invite_data,
        partner_company=partner_company,
        owner_worker=owner_worker,
        locale=locale,
    )


@router.message(OwnerAlphaOnboardingStates.waiting_for_owner_name)
async def process_owner_alpha_name(message: Message, state: FSMContext, locale: str):
    owner_name = (message.text or "").strip()
    if not owner_name or owner_name.startswith("/"):
        await message.answer("Bitte senden Sie Ihren vollstaendigen Namen." if locale == "de" else "Please send your full name.")
        return

    data = await state.get_data()
    invite_data = data.get("owner_invite_data") or {}
    invite_company_name = invite_data.get("company_name") or "Ihre Firma"
    await state.update_data(owner_name=owner_name)
    await message.answer(
        f"Wie soll die Firma heissen?\n\nVorschlag aus Einladung: {invite_company_name}\nMit /skip uebernehmen."
        if locale == "de"
        else f"What is the company name?\n\nInvite suggestion: {invite_company_name}\nSend /skip to use it."
    )
    await state.set_state(OwnerAlphaOnboardingStates.waiting_for_company_name)


@router.message(OwnerAlphaOnboardingStates.waiting_for_company_name)
async def process_owner_alpha_company_name(message: Message, state: FSMContext, locale: str):
    data = await state.get_data()
    invite_data = data.get("owner_invite_data") or {}
    suggested_name = invite_data.get("company_name") or ""
    company_name = suggested_name if _skip_value(message.text) else (message.text or "").strip()
    if not company_name:
        await message.answer("Bitte einen Firmennamen senden oder /skip nutzen." if locale == "de" else "Please send a company name or use /skip.")
        return

    await state.update_data(company_name=company_name)
    await message.answer(
        "Welche Rechtsform hat die Firma?"
        if locale == "de"
        else "What is the company's legal form?",
        reply_markup=get_company_legal_form_kb(locale),
    )
    await state.set_state(OwnerAlphaOnboardingStates.waiting_for_company_legal_form)


@router.callback_query(OwnerAlphaOnboardingStates.waiting_for_company_legal_form, F.data.startswith("legal_form_"))
async def process_owner_alpha_company_legal_form(callback: CallbackQuery, state: FSMContext, locale: str):
    legal_form = callback.data.removeprefix("legal_form_")
    allowed_values = {value for value, _label in LEGAL_FORM_OPTIONS}
    if legal_form not in allowed_values:
        await callback.answer()
        await callback.message.answer(
            "Bitte waehlen Sie eine Rechtsform aus der Liste."
            if locale == "de"
            else "Please choose a legal form from the list."
        )
        return

    await state.update_data(company_legal_form=legal_form)
    await callback.message.edit_text(
        f"Rechtsform: {_legal_form_label(legal_form)}"
        if locale == "de"
        else f"Legal form: {_legal_form_label(legal_form)}"
    )
    await callback.message.answer(
        "Bitte senden Sie die Firmenadresse fuer die oeffentliche Seite (oder /skip)."
        if locale == "de"
        else "Please send the company address for the public page (or /skip)."
    )
    await callback.answer()
    await state.set_state(OwnerAlphaOnboardingStates.waiting_for_company_address)


@router.message(OwnerAlphaOnboardingStates.waiting_for_company_address)
async def process_owner_alpha_company_address(message: Message, state: FSMContext, locale: str):
    company_address = "Adresse folgt" if _skip_value(message.text) else (message.text or "").strip()
    if not company_address:
        await message.answer("Bitte eine Adresse senden oder /skip nutzen." if locale == "de" else "Please send an address or use /skip.")
        return

    await state.update_data(company_address=company_address)
    await message.answer(
        "Bitte senden Sie die Firmen-E-Mail fuer die oeffentliche Seite (oder /skip)."
        if locale == "de"
        else "Please send the company email for the public page (or /skip)."
    )
    await state.set_state(OwnerAlphaOnboardingStates.waiting_for_company_email)


@router.message(OwnerAlphaOnboardingStates.waiting_for_company_email)
async def process_owner_alpha_company_email(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    locale: str,
):
    data = await state.get_data()
    owner_name = (data.get("owner_name") or "").strip()
    company_name = (data.get("company_name") or "").strip()
    company_legal_form = data.get("company_legal_form")
    legal_form_label = _legal_form_label(company_legal_form)
    company_address = (data.get("company_address") or "Adresse folgt").strip()
    company_email = None if _skip_value(message.text) else (message.text or "").strip() or None
    token = data.get("owner_invite_token")

    if not owner_name or not company_name:
        await state.clear()
        await message.answer(
            "Onboarding konnte nicht abgeschlossen werden. Bitte starten Sie den Invite-Link erneut."
            if locale == "de"
            else "Onboarding could not be completed. Please open the invite link again."
        )
        return

    if not company_legal_form:
        await message.answer(
            "Bitte waehlen Sie zuerst die Rechtsform der Firma."
            if locale == "de"
            else "Please choose the company legal form first.",
            reply_markup=get_company_legal_form_kb(locale),
        )
        await state.set_state(OwnerAlphaOnboardingStates.waiting_for_company_legal_form)
        return

    tg_id_str = str(message.from_user.id)
    company = Company(
        name=company_name,
        email=company_email,
        owner_telegram_id_enc=encrypt_string(tg_id_str),
        owner_telegram_id_hash=hash_string(tg_id_str),
    )
    session.add(company)
    await session.flush()

    owner = Worker(
        company_id=company.id,
        telegram_id_enc=encrypt_string(tg_id_str),
        telegram_id_hash=hash_string(tg_id_str),
        full_name_enc=encrypt_string(owner_name),
        worker_type=WorkerType.FESTANGESTELLT,
        billing_type=BillingType.HOURLY,
        hourly_rate=0,
        contract_hours_week=0,
        access_role=WorkerAccessRole.COMPANY_OWNER.value,
        can_view_dashboard=True,
        time_tracking_enabled=False,
        is_active=True,
        created_by=None,
    )
    session.add(owner)

    profile_slug = await _unique_company_slug(session, company_name)
    public_profile = CompanyPublicProfile(
        company_id=company.id,
        slug=profile_slug,
        company_name=company_name,
        subtitle=f"Bauunternehmen - {legal_form_label}",
        about_text=f"{company_name} ({legal_form_label}) nutzt BauClock fuer Zeiterfassung und Baustellenkoordination.",
        address=company_address,
        email=company_email,
        is_active=True,
    )
    session.add(public_profile)
    await session.commit()

    if token:
        await redis_client.delete(token)
    await state.clear()
    await message.answer(_owner_next_steps_text(company, profile_slug, locale))


@router.message(ChiefRegistrationStates.waiting_for_owner_phone, F.contact)
async def process_owner_phone(message: Message, state: FSMContext, locale: str):
    username = normalize_username(message.from_user.username)
    if username not in bot_config.ADMIN_USERNAMES:
        await state.clear()
        await message.answer("Keine Berechtigung.", reply_markup=ReplyKeyboardRemove())
        return

    contact = message.contact
    if not contact or (contact.user_id and contact.user_id != message.from_user.id):
        await message.answer("Bitte teilen Sie Ihre eigene Telefonnummer.")
        return

    owner_phone = normalize_phone(bot_config.OWNER_PHONE)
    shared_phone = normalize_phone(contact.phone_number)
    if not shared_phone or shared_phone != owner_phone:
        await state.clear()
        await message.answer("Verifizierung fehlgeschlagen.", reply_markup=ReplyKeyboardRemove())
        return

    await message.answer(
        "Verifizierung erfolgreich. Bitte geben Sie den Namen Ihres Unternehmens ein:",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.set_state(ChiefRegistrationStates.waiting_for_company_name)


@router.message(ChiefRegistrationStates.waiting_for_owner_phone)
async def process_owner_phone_invalid(message: Message, locale: str):
    await message.answer("Bitte teilen Sie Ihre Telefonnummer ueber den Button.")


@router.message(ChiefRegistrationStates.waiting_for_company_name)
async def process_company_name(message: Message, state: FSMContext, session: AsyncSession, locale: str):
    company_name = (message.text or "").strip()
    if not company_name:
        await message.answer("Bitte geben Sie den Namen Ihres Unternehmens ein:")
        return
    await state.update_data(company_name=company_name)
    await message.answer("Bitte geben Sie die Telefonnummer Ihres Unternehmens ein (oder /skip):")
    await state.set_state(ChiefRegistrationStates.waiting_for_company_phone)


@router.message(ChiefRegistrationStates.waiting_for_company_phone)
async def process_company_phone(message: Message, state: FSMContext, session: AsyncSession, locale: str):
    if not _skip_value(message.text):
        await state.update_data(phone=(message.text or "").strip())
    await message.answer("Bitte geben Sie die E-Mail-Adresse Ihres Unternehmens ein (oder /skip):")
    await state.set_state(ChiefRegistrationStates.waiting_for_company_email)


@router.message(ChiefRegistrationStates.waiting_for_company_email)
async def process_company_email(message: Message, state: FSMContext, session: AsyncSession, locale: str):
    if not _skip_value(message.text):
        await state.update_data(email=(message.text or "").strip())

    data = await state.get_data()
    company_name = data.get("company_name")
    tg_id_str = str(message.from_user.id)
    company = Company(
        name=company_name,
        phone=data.get("phone"),
        email=data.get("email"),
        owner_telegram_id_enc=encrypt_string(tg_id_str),
        owner_telegram_id_hash=hash_string(tg_id_str),
    )
    session.add(company)
    await session.flush()

    chief_worker = Worker(
        company_id=company.id,
        telegram_id_enc=encrypt_string(tg_id_str),
        telegram_id_hash=hash_string(tg_id_str),
        full_name_enc=encrypt_string(message.from_user.full_name or "Chief/Owner"),
        worker_type=WorkerType.FESTANGESTELLT,
        billing_type=BillingType.HOURLY,
        access_role=WorkerAccessRole.COMPANY_OWNER.value,
        can_view_dashboard=True,
        time_tracking_enabled=False,
        is_active=True,
        created_by=None,
    )
    session.add(chief_worker)
    await session.commit()

    await state.update_data(company_id=company.id)
    await message.answer(f"Unternehmen '{company_name}' registriert. Wie heisst Ihre erste Baustelle?")
    await state.set_state(ChiefRegistrationStates.waiting_for_first_site_name)


@router.message(ChiefRegistrationStates.waiting_for_first_site_name)
async def process_site_name(message: Message, state: FSMContext, session: AsyncSession, locale: str):
    site_name = (message.text or "").strip()
    data = await state.get_data()
    company = await session.get(Company, data.get("company_id"))
    if not company or not site_name:
        await state.clear()
        await message.answer("Baustelle konnte nicht erstellt werden. Bitte starten Sie erneut.")
        return

    site = Site(
        company_id=company.id,
        name=site_name,
        qr_token=f"site_{uuid.uuid4().hex[:16]}",
        is_active=True,
    )
    session.add(site)
    await session.commit()
    await _send_site_qr(message, company, site, locale)
    await state.clear()


@router.message(Command("add_site"))
async def cmd_add_site(message: Message, state: FSMContext, current_worker: Worker | None, locale: str):
    if not can_access_dashboard(current_worker):
        await message.answer("Keine Berechtigung." if locale == "de" else "Access denied.")
        return

    await state.clear()
    await message.answer("Wie heisst die Baustelle?" if locale == "de" else "What is the site name?")
    await state.set_state(AddSiteStates.waiting_for_name)


@router.message(AddSiteStates.waiting_for_name)
async def process_add_site_name(message: Message, state: FSMContext, locale: str):
    site_name = (message.text or "").strip()
    if not site_name or site_name.startswith("/"):
        await message.answer("Bitte einen Baustellennamen senden." if locale == "de" else "Please send a site name.")
        return

    await state.update_data(site_name=site_name)
    await message.answer("Adresse der Baustelle senden (oder /skip)." if locale == "de" else "Send the site address (or /skip).")
    await state.set_state(AddSiteStates.waiting_for_address)


@router.message(AddSiteStates.waiting_for_address)
async def process_add_site_address(message: Message, state: FSMContext, locale: str):
    site_address = "" if _skip_value(message.text) else (message.text or "").strip()
    await state.update_data(site_address=site_address)
    await message.answer(
        "Welche Rolle hat Ihre Firma auf dieser Baustelle?"
        if locale == "de"
        else "Which role does your company have on this site?",
        reply_markup=get_site_role_kb(locale),
    )
    await state.set_state(AddSiteStates.waiting_for_role)


@router.callback_query(AddSiteStates.waiting_for_role, F.data.startswith("site_role_"))
async def process_add_site_role(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    current_worker: Worker | None,
    locale: str,
):
    if not can_access_dashboard(current_worker):
        await state.clear()
        await callback.message.edit_text("Keine Berechtigung." if locale == "de" else "Access denied.")
        await callback.answer()
        return

    data = await state.get_data()
    site_name = (data.get("site_name") or "").strip()
    site_address = (data.get("site_address") or "").strip() or None
    role = callback.data.removeprefix("site_role_")
    if not site_name:
        await state.clear()
        await callback.message.edit_text("Baustelle konnte nicht erstellt werden. Bitte /add_site erneut starten.")
        await callback.answer()
        return

    company = await session.get(Company, current_worker.company_id)
    site = Site(
        company_id=current_worker.company_id,
        name=site_name,
        address=site_address,
        description=_site_description_for_role(role),
        qr_token=f"site_{uuid.uuid4().hex[:16]}",
        is_active=True,
    )
    session.add(site)
    await session.commit()

    await callback.message.edit_text(
        f"Baustelle '{site.name}' wird angelegt. QR folgt."
        if locale == "de"
        else f"Site '{site.name}' created. QR follows."
    )
    if company:
        await _send_site_qr(callback.message, company, site, locale)
    await callback.answer()
    await state.clear()


@router.message(Command("add_worker"))
async def cmd_add_worker(message: Message, state: FSMContext, current_worker: Worker | None, locale: str):
    if not can_access_dashboard(current_worker):
        await message.answer("Keine Berechtigung." if locale == "de" else "Access denied.")
        return

    await message.answer(
        "Bitte waehlen Sie die Art der Anstellung:"
        if locale == "de"
        else "Please choose the worker type:",
        reply_markup=get_worker_type_kb(locale),
    )
    await state.set_state(AddWorkerStates.waiting_for_worker_type)


@router.callback_query(AddWorkerStates.waiting_for_worker_type, F.data.startswith("wtype_"))
async def process_worker_type(callback: CallbackQuery, state: FSMContext, locale: str):
    worker_type = callback.data.removeprefix("wtype_")
    await state.update_data(worker_type=worker_type)
    await callback.message.edit_text(
        "Wie lautet der vollstaendige Name des Mitarbeiters?"
        if locale == "de"
        else "What is the worker's full name?",
        reply_markup=get_cancel_kb(locale),
    )
    await callback.answer()
    await state.set_state(AddWorkerStates.waiting_for_name)


@router.message(AddWorkerStates.waiting_for_name)
async def process_worker_name(message: Message, state: FSMContext, locale: str):
    name = (message.text or "").strip()
    if not name or name.startswith("/"):
        await message.answer("Bitte einen Namen senden." if locale == "de" else "Please send a name.")
        return
    await state.update_data(name=name)
    await message.answer(
        "Wie hoch ist der Stundenlohn in Euro? Beispiel: 15.50"
        if locale == "de"
        else "What is the hourly rate in EUR? Example: 15.50",
        reply_markup=get_cancel_kb(locale),
    )
    await state.set_state(AddWorkerStates.waiting_for_hourly_rate)


@router.message(AddWorkerStates.waiting_for_hourly_rate)
async def process_worker_rate(message: Message, state: FSMContext, current_worker: Worker | None, locale: str):
    try:
        rate = float((message.text or "").replace(",", "."))
    except ValueError:
        await message.answer("Bitte geben Sie eine gueltige Zahl ein." if locale == "de" else "Please enter a valid number.")
        return

    await state.update_data(rate=rate)
    data = await state.get_data()
    worker_type = data.get("worker_type")

    if worker_type in [WorkerType.FESTANGESTELLT.value, WorkerType.MINIJOB.value]:
        await message.answer(
            "Wie viele Vertragsstunden pro Woche hat der Mitarbeiter?"
            if locale == "de"
            else "How many contract hours per week?",
            reply_markup=get_cancel_kb(locale),
        )
        await state.set_state(AddWorkerStates.waiting_for_contract_hours)
    elif worker_type == WorkerType.SUBUNTERNEHMER.value:
        await generate_invite_link(message, state, current_worker, locale)
    else:
        await ask_objektmanager_flag(message, state, locale)


@router.message(AddWorkerStates.waiting_for_contract_hours)
async def process_worker_contract_hours(message: Message, state: FSMContext, current_worker: Worker | None, locale: str):
    try:
        hours_float = float((message.text or "").strip().replace(",", "."))
        if not hours_float.is_integer():
            raise ValueError
        hours = int(hours_float)
    except ValueError:
        await message.answer("Bitte geben Sie eine gueltige ganze Zahl ein." if locale == "de" else "Please enter a valid whole number.")
        return

    await state.update_data(contract_hours=hours)
    await ask_objektmanager_flag(message, state, locale)


async def ask_objektmanager_flag(message: Message, state: FSMContext, locale: str):
    await message.answer(
        "Soll diese Person auch Objektmanager mit Dashboard-Zugang sein?"
        if locale == "de"
        else "Should this person also be an object manager with dashboard access?",
        reply_markup=get_objektmanager_flag_kb(locale),
    )
    await state.set_state(AddWorkerStates.waiting_for_objektmanager_flag)


@router.callback_query(AddWorkerStates.waiting_for_objektmanager_flag, F.data.in_(["objmgr_yes", "objmgr_no"]))
async def process_objektmanager_flag(
    callback: CallbackQuery,
    state: FSMContext,
    current_worker: Worker | None,
    locale: str,
):
    is_objektmanager = callback.data == "objmgr_yes"
    await state.update_data(
        access_role=WorkerAccessRole.OBJEKTMANAGER.value if is_objektmanager else WorkerAccessRole.WORKER.value,
        can_view_dashboard=is_objektmanager,
    )
    if locale == "de":
        text = "Objektmanager-Zugang wird vorbereitet." if is_objektmanager else "Einladung wird vorbereitet."
    else:
        text = "Invite is being prepared."
    await callback.message.edit_text(text)
    await callback.answer()
    await generate_invite_link(callback.message, state, current_worker, locale)


async def generate_invite_link(message: Message, state: FSMContext, current_worker: Worker | None, locale: str):
    if not current_worker:
        await state.clear()
        await message.answer("Keine Berechtigung." if locale == "de" else "Access denied.")
        return

    data = await state.get_data()
    token = f"inv_{uuid.uuid4().hex[:16]}"
    invite_data = {
        "company_id": current_worker.company_id,
        "name": data.get("name"),
        "worker_type": data.get("worker_type"),
        "hourly_rate": data.get("rate"),
        "contract_hours": data.get("contract_hours", 0),
        "created_by": current_worker.id,
        "access_role": data.get("access_role", WorkerAccessRole.WORKER.value),
        "can_view_dashboard": bool(data.get("can_view_dashboard", False)),
    }

    await redis_client.setex(token, 86400 * 7, json.dumps(invite_data))
    bot_info = await message.bot.get_me()
    invite_link = f"https://t.me/{bot_info.username}?start={token}"

    wa_text = urllib.parse.quote(f"Einladung BauClock: {invite_link}")
    wa_link = f"https://wa.me/?text={wa_text}"
    qr_bio = generate_qr_code(invite_link)
    qr_file = BufferedInputFile(qr_bio.getvalue(), filename=f"qr_invite_{token}.png")

    safe_name = escape(str(data.get("name") or ""))
    safe_invite_link = escape(invite_link)
    safe_wa_link = escape(wa_link, quote=True)
    role_note = ""
    if invite_data["can_view_dashboard"]:
        role_note = "\nDashboard-Zugang: Objektmanager" if locale == "de" else "\nDashboard access: object manager"

    if locale == "de":
        text = (
            f"Einladung fuer {safe_name} erstellt{role_note}\n\n"
            "QR-Code zum Scannen:\n\n"
            "Oder Link teilen:\n"
            f"{safe_invite_link}\n\n"
            "Gueltig: 7 Tage\n\n"
            f"Teilen per: <a href=\"{safe_wa_link}\">WhatsApp</a> - E-Mail - SMS"
        )
    else:
        text = (
            f"Invite for {safe_name} created{role_note}\n\n"
            "QR code for scanning:\n\n"
            "Or share this link:\n"
            f"{safe_invite_link}\n\n"
            "Valid: 7 days\n\n"
            f"Share via: <a href=\"{safe_wa_link}\">WhatsApp</a> - E-Mail - SMS"
        )

    await message.answer_photo(photo=qr_file, caption=text, parse_mode=ParseMode.HTML)
    await state.clear()
