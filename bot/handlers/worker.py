import json
from datetime import datetime, timezone
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from db.models import Company, Site, Worker, TimeEvent, EventType
from db.security import encrypt_string, hash_string
from bot.states.worker_states import WorkerOnboardingStates
from bot.keyboards.worker_kb import get_gdpr_kb, get_language_kb, get_location_request_kb
from bot.redis_cache import redis_client
from bot.utils.location import haversine

router = Router()

# ---------------------------------------------------------
# INVITE ACCEPTANCE / ONBOARDING
# ---------------------------------------------------------

@router.message(Command("start"), F.text.startswith("/start inv_"))
async def cmd_start_invite(message: Message, state: FSMContext, session: AsyncSession, current_worker: Worker, locale: str):
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
    
    text = (
        "Willkommen bei SEK Zeiterfassung!\n\n"
        "Um fortzufahren, müssen wir Ihre Telegram ID und Ihren Namen verarbeiten. "
        "Diese Daten werden nach AES-256 Standard verschlüsselt in unserer Datenbank in Deutschland gespeichert. "
        "Die GPS-Daten Ihres Geräts werden nur im Moment des Einscannens eines QR-Codes zur "
        "Standortverifizierung erhoben und **nicht** dauerhaft getrackt.\n\n"
        "Stimmen Sie der Verarbeitung gemäß DSGVO zu?"
    ) if locale == "de" else (
        "Ласкаво просимо до SEK Zeiterfassung!\n\n"
        "Щоб продовжити, ми повинні обробляти ваш Telegram ID та ім'я. "
        "Ці дані шифруються за стандартом AES-256. "
        "Дані GPS використовуються лише під час сканування QR-коду.\n\n"
        "Чи погоджуєтеся ви з обробкою згідно з GDPR?"
    )
    
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
    
    text = "Bitte wählen Sie Ihre bevorzugte Sprache:" if locale == "de" else "Будь ласка, оберіть мову:"
    await callback.message.answer(text, reply_markup=get_language_kb())
    await state.set_state(WorkerOnboardingStates.waiting_for_language)

@router.callback_query(WorkerOnboardingStates.waiting_for_language, F.data.startswith("lang_"))
async def process_language(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    lang_val = callback.data.split("_")[1] # "de" or "uk"
    
    data = await state.get_data()
    invite_data = data.get("invite_data")
    token = data.get("token")
    
    tg_id_str = str(callback.from_user.id)
    
    new_worker = Worker(
        company_id=invite_data["company_id"],
        telegram_id_enc=encrypt_string(tg_id_str),
        telegram_id_hash=hash_string(tg_id_str),
        full_name_enc=encrypt_string(invite_data["name"]),
        worker_type=invite_data["worker_type"],
        billing_type="HOURLY" if invite_data["worker_type"] != "SUBUNTERNEHMER" else "FIXED",
        hourly_rate=invite_data["hourly_rate"],
        contract_hours_month=invite_data["contract_hours"],
        language=lang_val,
        can_view_dashboard=False,
        is_active=True,
        gdpr_consent_at=datetime.now(timezone.utc),
        created_by=invite_data["created_by"]    
    )
    
    session.add(new_worker)
    await session.commit()
    
    # Invalidate token
    await redis_client.delete(token)
    await state.clear()
    
    # Reload locale in memory for final message
    text = "Erfolgreich registriert! Sie können nun QR-Codes auf der Baustelle scannen." if lang_val == "de" else "Успішно зареєстровано! Тепер ви можете сканувати QR-коди на об'єкті."
    await callback.message.edit_text(text)

# ---------------------------------------------------------
# QR CHECK-IN FLOW & FSM STATE TRANSITIONS
# ---------------------------------------------------------

@router.message(Command("start"), F.text.startswith("/start site_"))
async def cmd_start_site(message: Message, state: FSMContext, session: AsyncSession, current_worker: Worker, locale: str):
    # Verify the site exists and is active
    stmt = select(Site).where(Site.qr_token == qr_token, Site.is_active == True)
    site = (await session.execute(stmt)).scalar_one_or_none()
    
    if not site:
        text = "Dieser QR-Code ist ungültig oder die Baustelle wurde deaktiviert." if locale == "de" else "Цей QR-код недійсний або об'єкт деактивовано."
        await message.answer(text)
        return

    # Handle unknown user (not registered in DB)
    if not current_worker or not current_worker.is_active:
        # Fetch company info
        company = await session.get(Company, site.company_id)
        
        # Neutral and professional message in DE and UK
        text_de = (
            f"ℹ️ Baustelle: {site.name}\n"
            f"📍 {site.address or 'Keine Adresse hinterlegt'}\n"
            f"🏗 {company.name}\n"
            f"📞 {company.phone or 'Keine Telefonnummer hinterlegt'}"
        )
        text_uk = (
            f"ℹ️ Об'єкт: {site.name}\n"
            f"📍 {site.address or 'Адреса відсутня'}\n"
            f"🏗 {company.name}\n"
            f"📞 {company.phone or 'Телефон відсутній'}"
        )
        
        await message.answer(text_de)
        await message.answer(text_uk)
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
        
        res_text = f"Check-out erfolgreich! Schönen Feierabend. 🌅\n" if locale == "de" else "Чек-аут успішний! Гарного вечора. 🌅\n"
        
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
        labels = {
            EventType.CHECKIN.value: ("Check-in erfolgreich! 👷‍♂️", "Чек-ін успішний! 👷‍♂️"),
            EventType.PAUSE_START.value: ("Pause gestartet ☕", "Пауза розпочата ☕"),
            EventType.PAUSE_END.value: ("Pause beendet. Zurück an die Arbeit! 🔨", "Пауза завершена. До роботи! 🔨")
        }
        res_text = labels[pending_event][0] if locale == "de" else labels[pending_event][1]
    
    from aiogram.types import ReplyKeyboardRemove
    await message.answer(res_text, reply_markup=ReplyKeyboardRemove())
    await state.clear()
    
    # Update current_worker site mapping
    if pending_event == EventType.CHECKIN.value:
        current_worker.site_id = site.id
        session.add(current_worker)
        await session.commit()
