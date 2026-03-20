from datetime import datetime, timezone
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.models import Worker, Payment, PaymentStatus
from bot.keyboards.dashboard_kb import get_dashboard_main_kb, get_payment_action_kb
from bot.states.dashboard_states import DashboardStates

router = Router()

@router.message(Command("dashboard"))
async def cmd_dashboard(message: Message, state: FSMContext, current_worker: Worker, locale: str):
    if not current_worker or not current_worker.is_active:
        text = "Zugriff verweigert." if locale == "de" else "Доступ заборонено."
        await message.answer(text)
        return
        
    is_chief = current_worker.can_view_dashboard
    
    text = "Willkommen im SEK Zeiterfassung Dashboard!\nWählen Sie eine Option:" if locale == "de" else "Ласкаво просимо до SEK Zeiterfassung Dashboard!\nОберіть опцію:"
    await message.answer(text, reply_markup=get_dashboard_main_kb(is_chief, locale))

# ---------------------------------------------------------
# CHIEF DASHBOARD FLOWS
# ---------------------------------------------------------

@router.callback_query(F.data == "dash_workers")
async def process_dash_workers(callback: CallbackQuery, current_worker: Worker, session: AsyncSession, locale: str):
    if not current_worker.can_view_dashboard:
        await callback.answer("Zugriff verweigert.", show_alert=True)
        return
        
    stmt = select(Worker).where(Worker.company_id == current_worker.company_id, Worker.is_active == True)
    workers = (await session.execute(stmt)).scalars().all()
    
    text = "Ihre aktiven Mitarbeiter:\n\n" if locale == "de" else "Ваші активні працівники:\n\n"
    for w in workers:
        # PII needs to be decrypted in a real display, but for now we show IDs or we would use the decrypt_string
        from db.security import decrypt_string
        name = decrypt_string(w.full_name_enc)
        rate = f"€{w.hourly_rate}/h" if w.hourly_rate else "Fest"
        text += f"- {name} ({w.worker_type.value}) - {rate}\n"
        
    await callback.message.edit_text(text, reply_markup=get_dashboard_main_kb(True, locale))
    await callback.answer()

@router.callback_query(F.data == "dash_payments")
async def process_dash_payments(callback: CallbackQuery, current_worker: Worker, session: AsyncSession, locale: str):
    if not current_worker.can_view_dashboard:
        await callback.answer("Zugriff verweigert.", show_alert=True)
        return
        
    # Fetch all pending payments for the company (Requires join)
    stmt = select(Payment, Worker).join(Worker, Payment.worker_id == Worker.id).where(
        Worker.company_id == current_worker.company_id,
        Payment.status == PaymentStatus.PENDING
    )
    results = (await session.execute(stmt)).all()
    
    if not results:
        text = "Keine ausstehenden Zahlungen." if locale == "de" else "Очікуючі платежі відсутні."
        await callback.message.edit_text(text, reply_markup=get_dashboard_main_kb(True, locale))
        return

    text = "Ausstehende Zahlungen:\n\n" if locale == "de" else "Очікуючі платежі:\n\n"
    from db.security import decrypt_string
    
    for payment, worker in results:
        name = decrypt_string(worker.full_name_enc)
        start_str = payment.period_start.strftime('%d.%m.%Y')
        end_str = payment.period_end.strftime('%d.%m.%Y')
        text += f"ID: {payment.id} | {name} | {start_str}-{end_str} | {payment.hours_paid}h | €{payment.amount_paid:.2f}\n"

    await callback.message.edit_text(text, reply_markup=get_dashboard_main_kb(True, locale))
    await callback.answer()

@router.callback_query(F.data == "dash_export")
async def process_dash_export(callback: CallbackQuery, current_worker: Worker, locale: str):
    if not current_worker.can_view_dashboard:
        await callback.answer("Zugriff verweigert.", show_alert=True)
        return
        
    from bot.config import settings
    host = settings.APP_URL 
    export_url = f"{host}/export/datev?company_id={current_worker.company_id}"
    
    text = f"Laden Sie Ihren DATEV Export hier herunter:\n{export_url}" if locale == "de" else f"Завантажте DATEV експорт тут:\n{export_url}"
    await callback.message.edit_text(text, reply_markup=get_dashboard_main_kb(True, locale))
    await callback.answer()


# ---------------------------------------------------------
# WORKER DASHBOARD FLOWS & PAYMENT CONFIRMATION
# ---------------------------------------------------------

@router.callback_query(F.data == "dash_my_hours")
async def process_my_hours(callback: CallbackQuery, current_worker: Worker, session: AsyncSession, locale: str):
    from datetime import timedelta
    from sqlalchemy import func
    from db.models import TimeEvent, EventType
    
    today = datetime.now(timezone.utc).date()
    start_of_week = today - timedelta(days=today.weekday())
    start_of_month = today.replace(day=1)
    
    # Helper to calculate total hours since a date
    async def get_hours(start_d):
        stmt = select(TimeEvent).where(
            TimeEvent.worker_id == current_worker.id,
            func.date(TimeEvent.timestamp) >= start_d
        ).order_by(TimeEvent.timestamp.asc())
        events = (await session.execute(stmt)).scalars().all()
        
        days_map = {}
        for e in events:
            d = e.timestamp.date()
            if d not in days_map: days_map[d] = []
            days_map[d].append(e)
            
        total_m = 0
        for d, evs in days_map.items():
            checkin_time = None
            pause_start_time = None
            for e in evs:
                if e.event_type == EventType.CHECKIN: 
                    checkin_time = e.timestamp
                elif e.event_type == EventType.PAUSE_START:
                    pause_start_time = e.timestamp
                    if checkin_time:
                        total_m += (e.timestamp - checkin_time).total_seconds() / 60
                        checkin_time = None
                elif e.event_type == EventType.PAUSE_END:
                    checkin_time = e.timestamp
                    pause_start_time = None
                elif e.event_type == EventType.CHECKOUT:
                    if checkin_time:
                        total_m += (e.timestamp - checkin_time).total_seconds() / 60
                        checkin_time = None
                    pause_start_time = None
        return total_m / 60.0

    total_w = await get_hours(start_of_week)
    total_m = await get_hours(start_of_month)
    
    rate = current_worker.hourly_rate or 0.0
    
    if current_worker.worker_type.value == "FESTANGESTELLT":
        con_w = current_worker.contract_hours_week or 0.0
        con_m = con_w * 4.0
        
        green_w_h = min(total_w, con_w)
        red_w_h = max(0.0, total_w - con_w)
        
        green_m_h = min(total_m, con_m)
        red_m_h = max(0.0, total_m - con_m)
    else:
        stmt_w = select(func.sum(Payment.hours_paid)).where(
            Payment.worker_id == current_worker.id,
            Payment.period_start >= start_of_week
        )
        paid_w = (await session.execute(stmt_w)).scalar() or 0.0
        
        stmt_m = select(func.sum(Payment.hours_paid)).where(
            Payment.worker_id == current_worker.id,
            Payment.period_start >= start_of_month
        )
        paid_m = (await session.execute(stmt_m)).scalar() or 0.0
        
        green_w_h = min(total_w, paid_w) 
        red_w_h = max(0.0, total_w - paid_w)
        
        green_m_h = min(total_m, paid_m)
        red_m_h = max(0.0, total_m - paid_m)

    green_w_eur = green_w_h * rate
    red_w_eur = red_w_h * rate
    green_m_eur = green_m_h * rate
    red_m_eur = red_m_h * rate
    
    if locale == "de":
        text = (
            f"Diese Woche: 🟢 {int(green_w_h)}h €{green_w_eur:.2f} / 🔴 {int(red_w_h)}h €{red_w_eur:.2f}\n"
            f"Dieser Monat: 🟢 {int(green_m_h)}h €{green_m_eur:.2f} / 🔴 {int(red_m_h)}h €{red_m_eur:.2f}"
        )
    else:
        text = (
            f"Цього тижня: 🟢 {int(green_w_h)}г €{green_w_eur:.2f} / 🔴 {int(red_w_h)}г €{red_w_eur:.2f}\n"
            f"Цього місяця: 🟢 {int(green_m_h)}г €{green_m_eur:.2f} / 🔴 {int(red_m_h)}г €{red_m_eur:.2f}"
        )

    await callback.message.edit_text(text, reply_markup=get_dashboard_main_kb(current_worker.can_view_dashboard, locale))
    await callback.answer()

@router.callback_query(F.data == "dash_my_payments")
async def process_my_payments(callback: CallbackQuery, current_worker: Worker, session: AsyncSession, locale: str):
    stmt = select(Payment).where(
        Payment.worker_id == current_worker.id,
        Payment.status == PaymentStatus.PENDING
    )
    payments = (await session.execute(stmt)).scalars().all()
    
    if not payments:
        text = "Sie haben keine offenen Zahlungsfreigaben." if locale == "de" else "У вас немає очікуючих платежів."
        await callback.message.edit_text(text, reply_markup=get_dashboard_main_kb(False, locale))
        return
        
    # Just show the first pending payment for simplicity in this flow
    p = payments[0]
    start_str = p.period_start.strftime('%d.%m.%Y')
    end_str = p.period_end.strftime('%d.%m.%Y')
    
    text = (
        f"Zahlungsfreigabe für den Zeitraum {start_str} - {end_str}:\n\n"
        f"Erfasste Stunden: {p.hours_paid}h\n"
        f"Auszahlungsbetrag: €{p.amount_paid:.2f}\n\n"
        f"Stimmen diese Angaben?"
    ) if locale == "de" else (
        f"Платіж за період {start_str} - {end_str}:\n\n"
        f"Години: {p.hours_paid}г\n"
        f"Сума: €{p.amount_paid:.2f}\n\n"
        f"Ці дані вірні?"
    )
    
    await callback.message.edit_text(text, reply_markup=get_payment_action_kb(p.id, locale))
    await callback.answer()

@router.callback_query(F.data.startswith("pay_confirm_"))
async def process_payment_confirm(callback: CallbackQuery, current_worker: Worker, session: AsyncSession, locale: str):
    payment_id = int(callback.data.split("_")[2])
    
    payment = await session.get(Payment, payment_id)
    if not payment or payment.worker_id != current_worker.id:
        await callback.answer("Fehler." if locale == "de" else "Помилка.")
        return
        
    payment.status = PaymentStatus.CONFIRMED
    payment.confirmed_at = datetime.now(timezone.utc)
    session.add(payment)
    await session.commit()
    
    from bot.i18n.translations import t
    text = t("payment_confirmed", locale)
    await callback.message.edit_text(text, reply_markup=get_dashboard_main_kb(False, locale))
    await callback.answer()

@router.callback_query(F.data.startswith("pay_dispute_"))
async def process_payment_dispute(callback: CallbackQuery, state: FSMContext, current_worker: Worker, session: AsyncSession, locale: str):
    payment_id = int(callback.data.split("_")[2])
    
    payment = await session.get(Payment, payment_id)
    if not payment or payment.worker_id != current_worker.id:
        await callback.answer("Fehler." if locale == "de" else "Помилка.")
        return
        
    payment.status = PaymentStatus.DISPUTED
    session.add(payment)
    await session.commit()
    
    await state.update_data(disputed_payment_id=payment.id)
    
    from bot.i18n.translations import t
    text = t("payment_disputed", locale)
    await callback.message.edit_text(text)
    await state.set_state(DashboardStates.waiting_for_payment_dispute)
    
@router.message(DashboardStates.waiting_for_payment_dispute)
async def process_dispute_reason(message: Message, state: FSMContext, session: AsyncSession, current_worker: Worker, locale: str):
    reason = message.text.strip()
    data = await state.get_data()
    payment_id = data.get("disputed_payment_id")
    
    # Notify all chiefs
    stmt_chief = select(Worker).where(
        Worker.company_id == current_worker.company_id,
        Worker.can_view_dashboard == True,
        Worker.is_active == True
    )
    chiefs = (await session.execute(stmt_chief)).scalars().all()
    
    from db.security import decrypt_string
    worker_name = decrypt_string(current_worker.full_name_enc)
    
    for chief in chiefs:
        try:
            chief_tg_id = int(decrypt_string(chief.telegram_id_enc))
            await message.bot.send_message(chief_tg_id, f"Worker {worker_name} disputed payment #{payment_id}: {reason}")
        except Exception as e:
            pass
            
    text = "Ihre Reklamation wurde an Waldemar (Owner) weitergeleitet. Er wird sich bei Ihnen melden." if locale == "de" else "Вашу скаргу передано керівнику. Він зв'яжеться з вами."
    await message.answer(text, reply_markup=get_dashboard_main_kb(current_worker.can_view_dashboard, locale))
    await state.clear()
