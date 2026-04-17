import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from db.models import (
    Company,
    EmploymentStatus,
    EmploymentType,
    EventType,
    LanguageSupport,
    Site,
    TimeEvent,
    Worker,
    WorkerAccessRole,
    WorkerType,
)
from db.calendar_service import get_events_for_worker_on_date
from db.security import encrypt_string, hash_string
from bot.states.worker_states import (
    CalendarViewStates,
    ReportProblemStates,
    TimeEventSelectionStates,
    WorkerOnboardingStates,
)
from bot.keyboards.worker_kb import (
    get_calendar_date_kb,
    get_gdpr_kb,
    get_language_kb,
    get_location_request_kb,
    get_problem_date_kb,
    get_worker_actions_kb,
)
from bot.i18n.translations import t
from bot.redis_cache import redis_client
from bot.utils.location import haversine
from bot.utils.scope import is_platform_identity_on_non_platform_bot, platform_context_only_text
from db.request_service import create_request

router = Router()


def _employment_type_from_invite(invite_data: dict, access_role: str) -> str:
    employment_type = invite_data.get("employment_type")
    allowed_values = {item.value for item in EmploymentType}
    if employment_type in allowed_values:
        return employment_type
    worker_type = invite_data.get("worker_type")
    if access_role == WorkerAccessRole.ACCOUNTANT.value:
        return EmploymentType.EXTERNAL_ACCOUNTANT.value
    if worker_type == WorkerType.MINIJOB.value:
        return EmploymentType.MINIJOB.value
    if worker_type in {WorkerType.GEWERBE.value, WorkerType.SUBUNTERNEHMER.value}:
        return EmploymentType.SELF_EMPLOYED.value
    return EmploymentType.EMPLOYEE_FULL_TIME.value


def _problem_today():
    return datetime.now(ZoneInfo("Europe/Berlin")).date()


def _calendar_today():
    return datetime.now(ZoneInfo("Europe/Berlin")).date()


def _problem_copy(key: str, locale: str) -> str:
    copies = {
        "choose_date": {
            "de": "Welches Datum betrifft das Problem?",
            "uk": "Якої дати стосується проблема?",
        },
        "ask_description": {
            "de": "Beschreiben Sie das Problem kurz.",
            "uk": "Коротко опишіть проблему.",
        },
        "empty_description": {
            "de": "Bitte geben Sie eine kurze Beschreibung ein.",
            "uk": "Будь ласка, введіть короткий опис.",
        },
        "created": {
            "de": "Problem wurde gemeldet.",
            "uk": "Проблему передано.",
        },
        "cancelled": {
            "de": "Meldung abgebrochen.",
            "uk": "Повідомлення скасовано.",
        },
    }
    return copies[key]["de" if locale == "de" else "uk"]


def _calendar_copy(key: str, locale: str, **kwargs) -> str:
    copies = {
        "choose_date": {
            "de": "Welchen Tag moechten Sie ansehen?",
            "uk": "Який день показати?",
        },
        "ask_manual_date": {
            "de": "Geben Sie das Datum im Format TT.MM.JJJJ ein.",
            "uk": "Введіть дату у форматі ДД.ММ.РРРР.",
        },
        "invalid_date": {
            "de": "Ungueltiges Datum. Bitte nutzen Sie TT.MM.JJJJ.",
            "uk": "Невірна дата. Введіть у форматі ДД.ММ.РРРР.",
        },
        "cancelled": {
            "de": "Kalenderansicht abgebrochen.",
            "uk": "Перегляд календаря скасовано.",
        },
        "no_events": {
            "de": "Fuer {date_label} ist nichts erfasst.",
            "uk": "На {date_label} нічого не зафіксовано.",
        },
        "events_header": {
            "de": "Kalender fuer {date_label}:",
            "uk": "Календар на {date_label}:",
        },
    }
    template = copies[key]["de" if locale == "de" else "uk"]
    return template.format(**kwargs)


def _calendar_event_type_label(event_type: str, locale: str) -> str:
    labels = {
        "vacation": {
            "de": "Urlaub",
            "uk": "Відпустка",
        },
        "sick_leave": {
            "de": "Krankmeldung",
            "uk": "Лікарняний",
        },
        "public_holiday": {
            "de": "Feiertag",
            "uk": "Свято",
        },
        "non_working_day": {
            "de": "Freier Tag",
            "uk": "Неробочий день",
        },
    }
    locale_key = "de" if locale == "de" else "uk"
    return labels.get(event_type, {}).get(locale_key, event_type)


def _format_calendar_date(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def _format_calendar_range(date_from: date, date_to: date) -> str:
    start = _format_calendar_date(date_from)
    end = _format_calendar_date(date_to)
    return start if start == end else f"{start} - {end}"


def _is_calendar_cancel_text(text: str | None) -> bool:
    normalized = (text or "").strip().lower()
    return normalized in {"/cancel", "cancel", "abbrechen", "скасувати"}


def _render_calendar_events(target_date: date, events, locale: str) -> str:
    date_label = _format_calendar_date(target_date)
    if not events:
        return _calendar_copy("no_events", locale, date_label=date_label)

    lines = [_calendar_copy("events_header", locale, date_label=date_label)]
    for event in events:
        line = (
            f"• {_calendar_event_type_label(event.event_type, locale)}: "
            f"{_format_calendar_range(event.date_from, event.date_to)}"
        )
        if event.comment:
            line = f"{line}\n  {event.comment}"
        lines.append(line)
    return "\n".join(lines)


async def _calendar_result_text(
    session: AsyncSession,
    current_worker: Worker,
    target_date: date,
    locale: str,
) -> str:
    events = await get_events_for_worker_on_date(
        session,
        worker=current_worker,
        target_date=target_date,
    )
    return _render_calendar_events(target_date, events, locale)


def _time_tracking_disabled_text(locale: str) -> str:
    return t("time_tracking_disabled", locale)


TIME_EVENT_ACTIONS = {
    "Ankunft": EventType.CHECKIN,
    "Arrival": EventType.CHECKIN,
    "Pause starten": EventType.PAUSE_START,
    "Start break": EventType.PAUSE_START,
    "Pause beenden": EventType.PAUSE_END,
    "End break": EventType.PAUSE_END,
    "Feierabend": EventType.CHECKOUT,
    "Exit": EventType.CHECKOUT,
}


def _parse_site_qr_token(text: str | None) -> str:
    parts = (text or "").strip().split(maxsplit=1)
    if len(parts) != 2:
        return ""
    token = parts[1].strip()
    return token if token.startswith("site_") else ""


async def _public_site_text(session: AsyncSession, site: Site) -> str:
    company = await session.get(Company, site.company_id)
    company_name = company.name if company else "Generalbau S.E.K. GmbH"
    lines = [company_name, "", site.name]
    if site.address:
        lines.extend(["", site.address])
    if site.description:
        lines.extend(["", site.description])
    return "\n".join(lines)


def _event_label(event_type: EventType, locale: str) -> str:
    labels = {
        EventType.CHECKIN: {"de": "Ankunft", "other": "Arrival"},
        EventType.PAUSE_START: {"de": "Pause starten", "other": "Start break"},
        EventType.PAUSE_END: {"de": "Pause beenden", "other": "End break"},
        EventType.CHECKOUT: {"de": "Feierabend", "other": "Exit"},
    }
    key = "de" if locale == "de" else "other"
    return labels[event_type][key]


# ---------------------------------------------------------
# INVITE ACCEPTANCE / ONBOARDING
# ---------------------------------------------------------

@router.message(Command("start"), F.text.startswith("/start inv_"))
async def cmd_start_invite(message: Message, state: FSMContext, session: AsyncSession, current_worker: Worker, locale: str):
    if is_platform_identity_on_non_platform_bot(getattr(message.from_user, "username", None)):
        await state.clear()
        await message.answer(platform_context_only_text(locale))
        return

    token = message.text.split(maxsplit=1)[1]
    
    # 1. Verify token in Redis
    invite_json = await redis_client.get(token)
    if not invite_json:
        text = "Dieser Einladungslink ist ungültig oder abgelaufen." if locale == "de" else "Це посилання на запрошення недійсне або прострочене."
        await message.answer(text)
        return
        
    invite_data = json.loads(invite_json)
    
    # 2. Handle duplicate telegram_id (Worker already in DB)
    if current_worker:
        text = "Sie sind bereits als Mitarbeiter registriert!" if locale == "de" else "Ви вже зареєстровані!"
        await message.answer(text)
        return
        
    # 3. Present GDPR Consent
    await state.update_data(invite_data=invite_data, token=token)
    
    from bot.i18n.translations import t
    text = f"{t('welcome', locale)}\n\n{t('gdpr_text', locale)}"
    
    await message.answer(text, reply_markup=get_gdpr_kb(locale))
    await state.set_state(WorkerOnboardingStates.waiting_for_gdpr_consent)

@router.callback_query(WorkerOnboardingStates.waiting_for_gdpr_consent, F.data.in_(["gdpr_accept", "gdpr_decline"]))
async def process_gdpr(callback: CallbackQuery, state: FSMContext, session: AsyncSession, locale: str):
    if callback.data == "gdpr_decline":
        await state.clear()
        text = "Registrierung abgebrochen. Sie können SEK Zeiterfassung ohne Zustimmung nicht nutzen." if locale == "de" else "Реєстрацію скасовано."
        await callback.message.edit_text(text)
        return
        
    await callback.message.edit_reply_markup(reply_markup=None)
    
    user_lang = callback.from_user.language_code
    if user_lang and user_lang in [l.value for l in LanguageSupport]:
        await handle_language_selection(callback, state, session, user_lang)
    else:
        text = "Bitte wählen Sie Ihre bevorzugte Sprache:" if locale == "de" else "Будь ласка, оберіть мову:"
        await callback.message.answer(text, reply_markup=get_language_kb())
        await state.set_state(WorkerOnboardingStates.waiting_for_language)

@router.callback_query(WorkerOnboardingStates.waiting_for_language, F.data.startswith("lang_"))
async def process_language(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    lang_val = callback.data.split("_")[1] # "de" or "uk", etc.
    await handle_language_selection(callback, state, session, lang_val)

async def handle_language_selection(callback: CallbackQuery, state: FSMContext, session: AsyncSession, lang_val: str):
    
    data = await state.get_data()
    invite_data = data.get("invite_data")
    token = data.get("token")
    
    tg_id_str = str(callback.from_user.id)
    
    access_role = (
        WorkerAccessRole.SUBCONTRACTOR.value
        if invite_data["worker_type"] == WorkerType.SUBUNTERNEHMER.value
        else invite_data.get("access_role", WorkerAccessRole.WORKER.value)
    )
    can_view_dashboard = bool(invite_data.get("can_view_dashboard", False))
    employment_status = invite_data.get("employment_status")
    if employment_status not in {item.value for item in EmploymentStatus}:
        employment_status = EmploymentStatus.ACTIVE.value

    new_worker = Worker(
        company_id=invite_data["company_id"],
        telegram_id_enc=encrypt_string(tg_id_str),
        telegram_id_hash=hash_string(tg_id_str),
        full_name_enc=encrypt_string(invite_data["name"]),
        worker_type=invite_data["worker_type"],
        billing_type="HOURLY" if invite_data["worker_type"] != "SUBUNTERNEHMER" else "FIXED",
        hourly_rate=invite_data["hourly_rate"],
        contract_hours_week=invite_data["contract_hours"],
        language=lang_val,
        access_role=access_role,
        can_view_dashboard=can_view_dashboard,
        time_tracking_enabled=True,
        employment_type=_employment_type_from_invite(invite_data, access_role),
        employment_status=employment_status,
        started_at=datetime.now(timezone.utc),
        is_active=True,
        gdpr_consent_at=datetime.now(timezone.utc),
        created_by=invite_data["created_by"]    
    )
    
    session.add(new_worker)
    await session.commit()
    
    # Invalidate token
    await redis_client.delete(token)
    await state.clear()
    
    from bot.i18n.translations import t
    text = t("register_complete", lang_val)
    if callback.message.reply_markup:
        await callback.message.edit_text(text)
        menu_text = "Nutzen Sie das Menue unten." if lang_val == "de" else "Користуйтеся меню нижче."
        await callback.message.answer(menu_text, reply_markup=get_worker_actions_kb(lang_val))
    else:
        await callback.message.answer(text, reply_markup=get_worker_actions_kb(lang_val))

@router.message(Command("language"))
async def cmd_language(message: Message, session: AsyncSession, current_worker: Worker):
    if not current_worker:
        return
    await message.answer("Select your language:", reply_markup=get_language_kb())

@router.callback_query(F.data.startswith("lang_"))
async def change_language(callback: CallbackQuery, session: AsyncSession, current_worker: Worker):
    if not current_worker:
        return
    lang_val = callback.data.split("_")[1]
    current_worker.language = LanguageSupport(lang_val)
    session.add(current_worker)
    await session.commit()
    await callback.message.edit_text(f"Language updated to {lang_val}.")


@router.message(F.text.in_(list(TIME_EVENT_ACTIONS.keys())))
async def start_time_event_action(message: Message, state: FSMContext, current_worker: Worker, locale: str):
    if not current_worker or not current_worker.is_active:
        return

    if not current_worker.time_tracking_enabled:
        await state.clear()
        await message.answer(_time_tracking_disabled_text(locale))
        return

    next_event = TIME_EVENT_ACTIONS.get((message.text or "").strip())
    if not next_event:
        return

    await state.clear()
    await state.update_data(pending_event=next_event.value)
    await state.set_state(TimeEventSelectionStates.waiting_for_site_qr)
    text = t("time_action_scan_prompt", locale).format(action=_event_label(next_event, locale))
    await message.answer(text)


@router.message(F.text == "⚠️ Проблема")
async def start_report_problem(message: Message, state: FSMContext, current_worker: Worker, locale: str):
    if not current_worker or not current_worker.is_active:
        return

    await state.clear()
    await message.answer(
        _problem_copy("choose_date", locale),
        reply_markup=get_problem_date_kb(locale),
    )
    await state.set_state(ReportProblemStates.waiting_for_date)


@router.callback_query(ReportProblemStates.waiting_for_date, F.data.startswith("problem_date_"))
async def choose_report_problem_date(callback: CallbackQuery, state: FSMContext, locale: str):
    date_mode = callback.data.removeprefix("problem_date_")
    if date_mode == "cancel":
        await state.clear()
        await callback.message.edit_text(_problem_copy("cancelled", locale))
        await callback.answer()
        return

    related_date = None
    if date_mode == "today":
        related_date = _problem_today()
    elif date_mode == "yesterday":
        related_date = _problem_today() - timedelta(days=1)

    await state.update_data(related_date=related_date)
    await callback.message.edit_text(_problem_copy("ask_description", locale))
    await callback.answer()
    await state.set_state(ReportProblemStates.waiting_for_description)


@router.message(ReportProblemStates.waiting_for_description)
async def submit_report_problem(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    current_worker: Worker,
    locale: str,
):
    if not current_worker or not current_worker.is_active:
        await state.clear()
        return

    description = (message.text or "").strip()
    if not description:
        await message.answer(_problem_copy("empty_description", locale))
        return

    data = await state.get_data()
    await create_request(
        session,
        creator_worker=current_worker,
        company_id=current_worker.company_id,
        target_worker_id=current_worker.id,
        related_date=data.get("related_date"),
        text=description,
    )
    await state.clear()
    await message.answer(_problem_copy("created", locale))


@router.message(F.text == "📅 Календар")
async def start_calendar_view(message: Message, state: FSMContext, current_worker: Worker, locale: str):
    if not current_worker or not current_worker.is_active:
        return

    await state.clear()
    await message.answer(
        _calendar_copy("choose_date", locale),
        reply_markup=get_calendar_date_kb(locale),
    )
    await state.set_state(CalendarViewStates.waiting_for_date_choice)


@router.callback_query(CalendarViewStates.waiting_for_date_choice, F.data.startswith("calendar_date_"))
async def choose_calendar_view_date(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    current_worker: Worker,
    locale: str,
):
    date_mode = callback.data.removeprefix("calendar_date_")
    if date_mode == "cancel":
        await state.clear()
        await callback.message.edit_text(_calendar_copy("cancelled", locale))
        await callback.answer()
        return

    if not current_worker or not current_worker.is_active:
        await state.clear()
        await callback.answer()
        return

    if date_mode == "custom":
        await callback.message.edit_text(_calendar_copy("ask_manual_date", locale))
        await callback.answer()
        await state.set_state(CalendarViewStates.waiting_for_manual_date)
        return

    target_date = _calendar_today()
    if date_mode == "tomorrow":
        target_date = _calendar_today() + timedelta(days=1)
    elif date_mode == "yesterday":
        target_date = _calendar_today() - timedelta(days=1)

    await state.clear()
    await callback.message.edit_text(
        await _calendar_result_text(session, current_worker, target_date, locale)
    )
    await callback.answer()


@router.message(CalendarViewStates.waiting_for_manual_date)
async def submit_calendar_manual_date(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    current_worker: Worker,
    locale: str,
):
    if not current_worker or not current_worker.is_active:
        await state.clear()
        return

    if _is_calendar_cancel_text(message.text):
        await state.clear()
        await message.answer(_calendar_copy("cancelled", locale))
        return

    try:
        target_date = datetime.strptime((message.text or "").strip(), "%d.%m.%Y").date()
    except ValueError:
        await message.answer(_calendar_copy("invalid_date", locale))
        return

    await state.clear()
    await message.answer(
        await _calendar_result_text(session, current_worker, target_date, locale)
    )

# ---------------------------------------------------------
# QR CHECK-IN FLOW & FSM STATE TRANSITIONS
# ---------------------------------------------------------

@router.message(Command("start"), F.text.startswith("/start site_"))
async def cmd_start_site(message: Message, state: FSMContext, session: AsyncSession, current_worker: Worker, locale: str):
    qr_token = _parse_site_qr_token(message.text)
    if not qr_token:
        return

    # Verify the site exists and is active
    stmt = select(Site).where(Site.qr_token == qr_token, Site.is_active == True)
    site = (await session.execute(stmt)).scalar_one_or_none()
    
    if not site:
        text = t("site_qr_invalid", locale)
        await message.answer(text)
        return

    state_data = await state.get_data()
    pending_event = state_data.get("pending_event")

    if not current_worker or not current_worker.is_active or not pending_event:
        await state.clear()
        await message.answer(await _public_site_text(session, site))
        return

    # Handle unknown user (not registered in DB)
    if not current_worker or not current_worker.is_active:
        await message.answer(
            "🏗 Generalbau S.E.K. GmbH\n"
            "Wir bauen Zukunft – Stein auf Stein.\n\n"
            "Generalbau · Trockenbau · Putz & Maler · Dämmung\n\n"
            "📍 Am Industriegelände 3\n"
            "14772 Brandenburg an der Havel\n"
            "🌐 generalbau-sek.de"
        )
        return

    if not current_worker.time_tracking_enabled:
        await message.answer(_time_tracking_disabled_text(locale))
        return

        
    # Check rate limits (Max 10 scans per worker per day)
    today = datetime.now(timezone.utc).date()
    scan_count_stmt = select(func.count(TimeEvent.id)).where(
        TimeEvent.worker_id == current_worker.id,
        func.date(TimeEvent.timestamp) == today
    )
    scan_count = (await session.execute(scan_count_stmt)).scalar() or 0
    if scan_count >= 10:
        text = "Maximales Scan-Limit für heute erreicht (10 scans)." if locale == "de" else "Досягнуто ліміт сканувань на сьогодні (10 сканувань)."
        await message.answer(text)
        return
        
    try:
        next_event = EventType(pending_event)
    except ValueError:
        await state.clear()
        await message.answer(await _public_site_text(session, site))
        return

    await state.update_data(pending_event=next_event.value, site_id=site.id)
    text = (
        f"Baustelle: {site.name}\n"
        f"Aktion: {_event_label(next_event, locale)}\n\n"
        "Bitte senden Sie uns Ihren GPS-Standort zur Verifizierung (Button unten)."
        if locale == "de"
        else f"Site: {site.name}\n"
        f"Action: {_event_label(next_event, locale)}\n\n"
        "Please send your GPS location for verification using the button below."
    )
    await message.answer(text, reply_markup=get_location_request_kb(locale))
    return

    # Determine next state transition based on today's logs for this worker
    # Fetch today's last event to see current state
    last_event_stmt = select(TimeEvent).where(
        TimeEvent.worker_id == current_worker.id,
        func.date(TimeEvent.timestamp) == today
    ).order_by(TimeEvent.timestamp.desc()).limit(1)
    
    last_event = (await session.execute(last_event_stmt)).scalar_one_or_none()
    
    # Current FSM Machine rules:
    # 1. No event -> CHECKIN (If a checkin already exists, we must prevent duplicate complete CHECKIN)
    # 2. CHECKIN -> PAUSE_START
    # 3. PAUSE_START -> PAUSE_END
    # 4. PAUSE_END -> CHECKOUT (or back to PAUSE_START depending on logic, but currently simplifed to Check-out or Pause)
    # 5. CHECKOUT -> Deny (Already departed)
    
    if not last_event:
        next_event = EventType.CHECKIN
        prompt = f"Baustelle: {site.name}\nMöchten Sie jetzt Einchecken?" if locale == "de" else f"Об'єкт: {site.name}\nБажаєте зробити Chekin зараз?"
    elif last_event.event_type == EventType.CHECKIN or last_event.event_type == EventType.PAUSE_END:
        # Check if they want to Pause or Checkout.
        # For simplicity, we can offer both via InlineKeyboard, but if relying purely on QR state:
        # We need a state intercept. Let's ask them what they want to do.
        await request_action_choice(message, state, site, last_event.event_type, locale)
        return
    elif last_event.event_type == EventType.PAUSE_START:
        next_event = EventType.PAUSE_END
        prompt = "Möchten Sie Ihre Pause jetzt beenden?" if locale == "de" else "Бажаєте завершити паузу зараз?"
    elif last_event.event_type == EventType.CHECKOUT:
        text = "Sie haben sich heute bereits abgemeldet." if locale == "de" else "Ви вже відмітились про завершення роботи сьогодні."
        await message.answer(text)
        return

    # Store context to handle the GPS request
    await state.update_data(pending_event=next_event.value, site_id=site.id)
    
    text = f"{prompt}\n\nBitte senden Sie uns Ihren GPS-Standort zur Verifizierung (Button unten)." if locale == "de" else f"{prompt}\n\nБудь ласка, надішліть свою GPS-локацію для перевірки (кнопка нижче)."
    await message.answer(text, reply_markup=get_location_request_kb(locale))

async def request_action_choice(message: Message, state: FSMContext, site: Site, last_event_type: EventType, locale: str):
    """Offers the choice between Pause and Checkout if they are currently working."""
    text_pause = "Pause starten ⏸" if locale == "de" else "Почати паузу ⏸"
    text_checkout = "Feierabend (Checkout) 🛑" if locale == "de" else "Кінець роботи 🛑"
    
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    keys = [
        [InlineKeyboardButton(text=text_pause, callback_data=f"qr_action_{EventType.PAUSE_START.value}_{site.id}")],
        [InlineKeyboardButton(text=text_checkout, callback_data=f"qr_action_{EventType.CHECKOUT.value}_{site.id}")]
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=keys)
    
    text = f"Baustelle: {site.name}\nAktueller Status: Am arbeiten 🟢\n\nWas möchten Sie tun?" if locale == "de" else f"Об'єкт: {site.name}\nСтатус: Працює 🟢\n\nЩо ви хочете зробити?"
    await message.answer(text, reply_markup=kb)

@router.callback_query(F.data.startswith("qr_action_"))
async def process_action_choice(callback: CallbackQuery, state: FSMContext, locale: str):
    parts = callback.data.split("_")
    next_event_val = parts[2]
    site_id = parts[3]
    
    await state.update_data(pending_event=next_event_val, site_id=int(site_id))
    
    text = "Bitte senden Sie uns Ihren GPS-Standort zur Verifizierung (Button unten)." if locale == "de" else "Будь ласка, надішліть свою GPS-локацію для перевірки (кнопка нижче)."
    
    # Delete the inline keyboard and send the reply keyboard
    await callback.message.delete()
    await callback.message.answer(text, reply_markup=get_location_request_kb(locale))

# ---------------------------------------------------------
# GPS VALIDATION & EVENT COMMIT
# ---------------------------------------------------------

@router.message(F.location)
async def process_location(message: Message, state: FSMContext, session: AsyncSession, current_worker: Worker, locale: str):
    data = await state.get_data()
    pending_event = data.get("pending_event")
    site_id = data.get("site_id")
    
    if not pending_event or not site_id:
        # Probably sent a location randomly
        return

    if not current_worker or not current_worker.is_active or not current_worker.time_tracking_enabled:
        from aiogram.types import ReplyKeyboardRemove
        await message.answer(_time_tracking_disabled_text(locale), reply_markup=ReplyKeyboardRemove())
        await state.clear()
        return
        
    lat = message.location.latitude
    lon = message.location.longitude
    accuracy = message.location.horizontal_accuracy if hasattr(message.location, 'horizontal_accuracy') else None
    
    # 1. Fetch site to validate distance
    site = await session.get(Site, site_id)
    is_suspicious = False
    
    # Validate GPS if site has a radius configured
    if site.lat and site.lon and site.radius_m:
        distance = haversine(site.lat, site.lon, lat, lon)
        if distance > site.radius_m:
            # We mark as suspicious but typically reject. Business logic here: REJECT.
            text = (
                f"Sie sind zu weit von der Baustelle entfernt ({int(distance)}m > {int(site.radius_m)}m).\n"
                "Aktion abgelehnt."
            ) if locale == "de" else (
                f"Ви занадто далеко від об'єкта ({int(distance)}м > {int(site.radius_m)}м).\n"
                "Відхилено."
            )
            from aiogram.types import ReplyKeyboardRemove
            await message.answer(text, reply_markup=ReplyKeyboardRemove())
            await state.clear()
            return

    # 2. Prevent duplicate CHECKIN (double check inside transaction window to be safe)
    if pending_event == EventType.CHECKIN.value:
        today = datetime.now(timezone.utc).date()
        checkin_stmt = select(TimeEvent).where(
            TimeEvent.worker_id == current_worker.id,
            func.date(TimeEvent.timestamp) == today,
            TimeEvent.event_type == EventType.CHECKIN
        )
        existing_checkin = (await session.execute(checkin_stmt)).scalar_one_or_none()
        if existing_checkin:
            text = "Sie haben heute bereits eingecheckt." if locale == "de" else "Ви вже відмітились про початок роботи сьогодні."
            from aiogram.types import ReplyKeyboardRemove
            await message.answer(text, reply_markup=ReplyKeyboardRemove())
            await state.clear()
            return
            
    # 3. Create Event
    event = TimeEvent(
        worker_id=current_worker.id,
        site_id=site.id,
        event_type=EventType(pending_event),
        lat=lat,
        lon=lon,
        gps_accuracy_m=accuracy,
        is_suspicious=is_suspicious
    )
    session.add(event)
    await session.commit()
    
    # 4. Respond
    
    res_text = ""
    if pending_event == EventType.CHECKOUT.value:
        # Calculate daily summary
        today = datetime.now(timezone.utc).date()
        daily_events_stmt = select(TimeEvent).where(
            TimeEvent.worker_id == current_worker.id,
            func.date(TimeEvent.timestamp) == today
        ).order_by(TimeEvent.timestamp.asc())
        
        events = (await session.execute(daily_events_stmt)).scalars().all()
        
        total_work_minutes = 0
        total_pause_minutes = 0
        
        checkin_time = None
        pause_start_time = None
        
        for e in events:
            if e.event_type == EventType.CHECKIN:
                checkin_time = e.timestamp
            elif e.event_type == EventType.PAUSE_START:
                pause_start_time = e.timestamp
                if checkin_time:
                    total_work_minutes += (e.timestamp - checkin_time).total_seconds() / 60
                    checkin_time = None
            elif e.event_type == EventType.PAUSE_END:
                if pause_start_time:
                    total_pause_minutes += (e.timestamp - pause_start_time).total_seconds() / 60
                    pause_start_time = None
                checkin_time = e.timestamp
            elif e.event_type == EventType.CHECKOUT:
                if checkin_time:
                    total_work_minutes += (e.timestamp - checkin_time).total_seconds() / 60
                    checkin_time = None
                if pause_start_time:
                    # They checked out while on pause, end the pause here too
                    total_pause_minutes += (e.timestamp - pause_start_time).total_seconds() / 60
                    pause_start_time = None
                    
        total_work_minutes = int(total_work_minutes)
        total_pause_minutes = int(total_pause_minutes)
        
        work_h = total_work_minutes // 60
        work_m = total_work_minutes % 60
        
        res_text = f"{t('checkout_summary', locale)}\n"
        
        hourly_rate = current_worker.hourly_rate or 0.0
        earnings = (total_work_minutes / 60) * hourly_rate
        
        if locale == "de":
            res_text += f"\nArbeitszeit: {work_h}h {work_m}min | Pause: {total_pause_minutes}min"
            if hourly_rate > 0:
                res_text += f" | Verdient: €{earnings:.2f}"
            res_text += "\n\nTobias (Objektbetreuer) ist über Ihren Checkout informiert."
        else:
            res_text += f"\nРобочий час: {work_h}г {work_m}хв | Пауза: {total_pause_minutes}хв"
            if hourly_rate > 0:
                res_text += f" | Зароблено: €{earnings:.2f}"
    else:
        from bot.i18n.translations import t
        labels = {
            EventType.CHECKIN.value: t("checkin_success", locale),
            EventType.PAUSE_START.value: t("pause_start", locale),
            EventType.PAUSE_END.value: t("pause_end", locale)
        }
        res_text = labels[pending_event]
    
    from aiogram.types import ReplyKeyboardRemove
    await message.answer(res_text, reply_markup=ReplyKeyboardRemove())
    await state.clear()
    
    # Update current_worker site mapping
    if pending_event == EventType.CHECKIN.value:
        current_worker.site_id = site.id
        session.add(current_worker)
        await session.commit()
