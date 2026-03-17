import uuid
import json
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.models import Company, Site, Worker, WorkerType, BillingType
from db.security import encrypt_string, hash_string
from bot.states.chief_states import ChiefRegistrationStates, AddWorkerStates
from bot.keyboards.chief_kb import get_worker_type_kb, get_cancel_kb
from bot.redis_cache import redis_client
from bot.config import settings as bot_config
from bot.utils.qr import generate_qr_code
from bot.utils.pdf import generate_site_pdf
from aiogram.types import BufferedInputFile

router = Router()

@router.callback_query(F.data == "cancel_action")
async def cancel_action(callback: CallbackQuery, state: FSMContext, locale: str):
    await state.clear()
    text = "Aktion abgebrochen." if locale == "de" else "Дію скасовано."
    await callback.message.edit_text(text)
    await callback.answer()

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext, session: AsyncSession, current_worker: Worker, locale: str):
    """
    Handles /start. Routes deep links (site_*, inv_*) to worker.py eventually.
    Initiates Chief Registration if new user without args.
    """
    args = message.text.split(maxsplit=1)
    
    if len(args) == 2:
        token = args[1]
        # In a real setup, we might re-route these from here, or let them fall through if handled generally
        # We will handle these in worker.py which intercepts deep links
        # But if it falls here, we just hint:
        if token.startswith("site_") or token.startswith("inv_"):
            return # Let worker.py handle it! We should ensure worker.py router intercepts this, or we import and call it

    # If already a worker:
    if current_worker:
        text = "Willkommen zurück bei SEK Zeiterfassung! Nutzen Sie /dashboard für eine Übersicht oder /add_worker um Mitarbeiter hinzuzufügen." if locale == "de" else "Ласкаво просимо назад! Використовуйте /dashboard або /add_worker."
        await message.answer(text)
        return

    # Check if this user is already a company owner who somehow doesn't have a Worker record
    tg_hash = hash_string(str(message.from_user.id))
    stmt = select(Company).where(Company.owner_telegram_id_hash == tg_hash)
    result = await session.execute(stmt)
    company = result.scalar_one_or_none()

    if company:
        text = f"Willkommen zurück, Chef von {company.name}!" if locale == "de" else f"Вітаємо, керівник {company.name}!"
        await message.answer(text)
        return

    # Start Chief Registration
    text = (
        "Willkommen bei SEK Zeiterfassung! Ich bin Ihr Assistent für die digitale Zeiterfassung.\n\n"
        "Waldemar (Inhaber) hat hier volle Kontrolle (OWNER).\n"
        "Bitte geben Sie zuerst den Namen Ihres Unternehmens ein:"
    ) if locale == "de" else (
        "Ласкаво просимо до SEK Zeiterfassung! Я ваш помічник для цифрового обліку часу.\n\n"
        "Будь ласка, введіть назву вашої компанії:"
    )
    await message.answer(text)
    await state.set_state(ChiefRegistrationStates.waiting_for_company_name)

@router.message(ChiefRegistrationStates.waiting_for_company_name)
async def process_company_name(message: Message, state: FSMContext, session: AsyncSession, locale: str):
    company_name = message.text.strip()
    await state.update_data(company_name=company_name)
    
    text = (
        "Bitte geben Sie die Telefonnummer Ihres Unternehmens ein (oder /skip):"
    ) if locale == "de" else (
        "Будь ласка, введіть номер телефону вашої компанії (або /skip):"
    )
    await message.answer(text)
    await state.set_state(ChiefRegistrationStates.waiting_for_company_phone)

@router.message(ChiefRegistrationStates.waiting_for_company_phone)
async def process_company_phone(message: Message, state: FSMContext, session: AsyncSession, locale: str):
    phone = message.text.strip()
    if phone != "/skip":
        await state.update_data(phone=phone)
    
    text = (
        "Bitte geben Sie die E-Mail-Adresse Ihres Unternehmens ein (oder /skip):"
    ) if locale == "de" else (
        "Будь ласка, введіть електронну адресу вашої компанії (або /skip):"
    )
    await message.answer(text)
    await state.set_state(ChiefRegistrationStates.waiting_for_company_email)

@router.message(ChiefRegistrationStates.waiting_for_company_email)
async def process_company_email(message: Message, state: FSMContext, session: AsyncSession, locale: str):
    email = message.text.strip()
    if email != "/skip":
        await state.update_data(email=email)
        
    data = await state.get_data()
    company_name = data.get("company_name")
    
    tg_id_str = str(message.from_user.id)
    new_company = Company(
        name=company_name,
        phone=data.get("phone"),
        email=data.get("email"),
        owner_telegram_id_enc=encrypt_string(tg_id_str),
        owner_telegram_id_hash=hash_string(tg_id_str)
    )
    session.add(new_company)
    await session.flush() # flush to generate new_company.id
    
    # Create the Chief as a Festangestellt Worker with Dashboard access (OWNER role)
    chief_worker = Worker(
        company_id=new_company.id,
        telegram_id_enc=encrypt_string(tg_id_str),
        telegram_id_hash=hash_string(tg_id_str),
        full_name_enc=encrypt_string(message.from_user.full_name or "Chief/Owner"),
        worker_type=WorkerType.FESTANGESTELLT,
        billing_type=BillingType.HOURLY,
        can_view_dashboard=True,
        is_active=True,
        created_by=None  # The chief creates themselves
    )
    session.add(chief_worker)
    await session.commit()
    
    await state.update_data(company_id=new_company.id)
    
    text = f"Unternehmen '{company_name}' registriert! Wie heißt Ihre erste Baustelle?" if locale == "de" else f"Компанію '{company_name}' зареєстровано! Як називається ваш перший об'єкт?"
    await message.answer(text)
    await state.set_state(ChiefRegistrationStates.waiting_for_first_site_name)

@router.message(ChiefRegistrationStates.waiting_for_first_site_name)
async def process_site_name(message: Message, state: FSMContext, session: AsyncSession, locale: str):
    site_name = message.text.strip()
    data = await state.get_data()
    company_id = data.get("company_id")
    
    # Fetch company for PDF info
    company = await session.get(Company, company_id)
    
    qr_token = f"site_{uuid.uuid4().hex[:16]}"
    
    new_site = Site(
        company_id=company_id,
        name=site_name,
        qr_token=qr_token,
        is_active=True
    )
    session.add(new_site)
    await session.commit()
    
    bot_info = await message.bot.get_me()
    # Real link will be handled via FastAPI redirect
    # But for now, using Telegram deep link for direct bot access
    qr_link = f"{bot_config.APP_URL}/s/{qr_token}"
    tg_link = f"https://t.me/{bot_config.BOT_USERNAME}?start={qr_token}"
    
    # 1. Generate QR Code Photo
    qr_bio = generate_qr_code(tg_link)
    qr_file = BufferedInputFile(qr_bio.getvalue(), filename=f"qr_{site_name}.png")
    
    # 2. Generate Print-ready PDF
    pdf_bio = generate_site_pdf(company.name, site_name, "", tg_link)
    pdf_file = BufferedInputFile(pdf_bio.getvalue(), filename=f"SEK_Aushang_{site_name}.pdf")

    text = (
        f"Baustelle '{site_name}' erstellt!\n\n"
        f"Hier ist der QR-Code für den Check-in vor Ort.\n\n"
        f"Waldemar (Owner), Torsten (Bauleiter) und Tobias (Objektbetreuer) "
        f"können nun mit der Verwaltung beginnen."
    ) if locale == "de" else (
        f"Об'єкт '{site_name}' створено!\n\nОсь QR-код для чекіну."
    )
    
    await message.answer_photo(qr_file, caption=text)
    await message.answer_document(pdf_file, caption="Druckfertiges A4-PDF für die Baustelle.")
    
    await state.clear()

# --- Add Worker Flow ---

@router.message(Command("add_worker"))
async def cmd_add_worker(message: Message, state: FSMContext, current_worker: Worker, locale: str):
    # Only Chief (Owner/Waldemar) or Bauleiter (Torsten) can add workers
    if not current_worker or current_worker.can_view_dashboard is False:
        text = "Keine Berechtigung. Nur für Owner (Waldemar) oder Bauleiter (Torsten)." if locale == "de" else "Немає доступу."
        await message.answer(text)
        return
        
    text = "Bitte wählen Sie die Art der Anstellung:" if locale == "de" else "Будь ласка, оберіть тип працевлаштування:"
    await message.answer(text, reply_markup=get_worker_type_kb(locale))
    await state.set_state(AddWorkerStates.waiting_for_worker_type)

@router.callback_query(AddWorkerStates.waiting_for_worker_type, F.data.startswith("wtype_"))
async def process_worker_type(callback: CallbackQuery, state: FSMContext, locale: str):
    wtype = callback.data.split("_")[1]
    await state.update_data(worker_type=wtype)
    
    text = "Wie lautet der vollständige Name des Mitarbeiters?" if locale == "de" else "Як повне ім'я працівника?"
    await callback.message.edit_text(text, reply_markup=get_cancel_kb(locale))
    await state.set_state(AddWorkerStates.waiting_for_name)

@router.message(AddWorkerStates.waiting_for_name)
async def process_worker_name(message: Message, state: FSMContext, locale: str):
    name = message.text.strip()
    await state.update_data(name=name)
    
    text = "Wie hoch ist der Stundenlohn (in Euro)? Z.B. 15.50" if locale == "de" else "Яка погодинна ставка (в Євро)? Напр. 15.50"
    await message.answer(text, reply_markup=get_cancel_kb(locale))
    await state.set_state(AddWorkerStates.waiting_for_hourly_rate)

@router.message(AddWorkerStates.waiting_for_hourly_rate)
async def process_worker_rate(message: Message, state: FSMContext, current_worker: Worker, locale: str):
    try:
        rate = float(message.text.replace(",", "."))
    except ValueError:
        text = "Bitte geben Sie eine gültige Zahl ein." if locale == "de" else "Будь ласка, введіть дійсне число."
        await message.answer(text)
        return
        
    await state.update_data(rate=rate)
    
    data = await state.get_data()
    wtype = data.get("worker_type")
    
    if wtype in [WorkerType.FESTANGESTELLT.value, WorkerType.MINIJOB.value]:
        text = "Wie viele Vertragsstunden pro Monat hat der Mitarbeiter?" if locale == "de" else "Скільки контрактних годин на місяць?"
        await message.answer(text, reply_markup=get_cancel_kb(locale))
        await state.set_state(AddWorkerStates.waiting_for_contract_hours)
    else:
        # Generate invite directly for non-fixed hour workers
        await generate_invite_link(message, state, current_worker, locale)

@router.message(AddWorkerStates.waiting_for_contract_hours)
async def process_worker_contract_hours(message: Message, state: FSMContext, current_worker: Worker, locale: str):
    try:
        hours = float(message.text.replace(",", "."))
    except ValueError:
        text = "Bitte geben Sie eine gültige Zahl ein." if locale == "de" else "Будь ласка, введіть дійсне число."
        await message.answer(text)
        return
        
    await state.update_data(contract_hours=hours)
    await generate_invite_link(message, state, current_worker, locale)

async def generate_invite_link(message: Message, state: FSMContext, current_worker: Worker, locale: str):
    data = await state.get_data()
    token = f"inv_{uuid.uuid4().hex[:16]}"
    
    # Store pending worker info in Redis for 7 days
    invite_data = {
        "company_id": current_worker.company_id,
        "name": data.get("name"),
        "worker_type": data.get("worker_type"),
        "hourly_rate": data.get("rate"),
        "contract_hours": data.get("contract_hours", 0.0),
        "created_by": current_worker.id
    }
    
    await redis_client.setex(token, 86400 * 7, json.dumps(invite_data))
    
    bot_info = await message.bot.get_me()
    inv_link = f"https://t.me/{bot_info.username}?start={token}"
    
    text = (
        f"Mitarbeiter {data.get('name')} vorbereitet!\n\n"
        f"Bitte senden Sie diesen Einladungslink an den Mitarbeiter:\n{inv_link}"
    ) if locale == "de" else (
        f"Працівника {data.get('name')} підготовлено!\n\nНадішліть це посилання:\n{inv_link}"
    )
    
    await message.answer(text)
    await state.clear()
