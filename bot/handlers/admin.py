from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from access.legacy_policy import (
    can_manage_payments,
    can_manage_rates,
    can_manage_workers,
    can_view_admin_features,
)
from db.models import Worker, Payment, WorkerType
from bot.keyboards.chief_kb import get_cancel_kb

router = Router()

class AdminStates(StatesGroup):
    waiting_for_worker_selection = State()
    waiting_for_action = State()
    waiting_for_new_rate = State()

def get_admin_action_kb(worker_id: int, locale: str) -> InlineKeyboardMarkup:
    keys = [
        [InlineKeyboardButton(text="Deaktivieren ❌" if locale == "de" else "Деактивувати ❌", callback_data=f"adm_deact_{worker_id}")],
        [InlineKeyboardButton(text="Lohn/Typ bearbeiten ✏️" if locale == "de" else "Змінити ставку ✏️", callback_data=f"adm_edit_{worker_id}")],
        [InlineKeyboardButton(text="Zahlungshistorie 💰" if locale == "de" else "Історія платежів 💰", callback_data=f"adm_hist_{worker_id}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keys)

@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext, session: AsyncSession, current_worker: Worker, locale: str):
    if not can_view_admin_features(current_worker):
        await message.answer("Zugriff verweigert." if locale == "de" else "Доступ заборонено.")
        return
        
    stmt = select(Worker).where(Worker.company_id == current_worker.company_id, Worker.is_active == True)
    workers = (await session.execute(stmt)).scalars().all()
    
    from db.security import decrypt_string
    keys = []
    for w in workers:
        if w.id == current_worker.id:
            continue
        name = decrypt_string(w.full_name_enc)
        keys.append([InlineKeyboardButton(text=name, callback_data=f"adm_sel_{w.id}")])
    
    if not keys:
        await message.answer("Keine aktiven Mitarbeiter gefunden." if locale == "de" else "Активних працівників не знайдено.")
        return
        
    text = "Wählen Sie einen Mitarbeiter aus:" if locale == "de" else "Оберіть працівника:"
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keys))

@router.callback_query(F.data.startswith("adm_sel_"))
async def admin_worker_selected(callback: CallbackQuery, session: AsyncSession, current_worker: Worker, locale: str):
    if not can_view_admin_features(current_worker):
        return
        
    target_id = int(callback.data.split("_")[2])
    target = await session.get(Worker, target_id)
    
    if not target or target.company_id != current_worker.company_id:
        return
        
    from db.security import decrypt_string
    name = decrypt_string(target.full_name_enc)
    rate = target.hourly_rate or 0.0
    
    text = f"Mitarbeiter: {name}\nTyp: {target.worker_type.value}\nLohn: €{rate:.2f}/h\n\nAktion wählen:" if locale == "de" else f"Працівник: {name}\nТип: {target.worker_type.value}\nСтавка: €{rate:.2f}/г\n\nОберіть дію:"
    await callback.message.edit_text(text, reply_markup=get_admin_action_kb(target_id, locale))

@router.callback_query(F.data.startswith("adm_deact_"))
async def admin_deactivate(callback: CallbackQuery, session: AsyncSession, current_worker: Worker, locale: str):
    if not can_manage_workers(current_worker): return
    target_id = int(callback.data.split("_")[2])
    target = await session.get(Worker, target_id)
    
    if target and target.company_id == current_worker.company_id:
        target.is_active = False
        session.add(target)
        await session.commit()
        await callback.message.edit_text("Mitarbeiter deaktiviert." if locale == "de" else "Працівника деактивовано.")

@router.callback_query(F.data.startswith("adm_edit_"))
async def admin_edit_rate(callback: CallbackQuery, state: FSMContext, session: AsyncSession, current_worker: Worker, locale: str):
    if not can_manage_rates(current_worker): return
    target_id = int(callback.data.split("_")[2])
    
    await state.update_data(edit_worker_id=target_id)
    text = "Bitte neuen Stundenlohn (z.B. 16.50) eingeben:" if locale == "de" else "Введіть нову погодинну ставку (напр. 16.50):"
    await callback.message.edit_text(text, reply_markup=get_cancel_kb(locale))
    await state.set_state(AdminStates.waiting_for_new_rate)

@router.message(AdminStates.waiting_for_new_rate)
async def process_new_rate(message: Message, state: FSMContext, session: AsyncSession, current_worker: Worker, locale: str):
    try:
        new_rate = float(message.text.replace(",", "."))
    except ValueError:
        await message.answer("Ungültige Zahl." if locale == "de" else "Недійсне число.")
        return
        
    data = await state.get_data()
    target = await session.get(Worker, data["edit_worker_id"])
    
    if target and target.company_id == current_worker.company_id:
        target.hourly_rate = new_rate
        session.add(target)
        await session.commit()
        await message.answer(f"Stundenlohn aktualisiert auf €{new_rate:.2f}" if locale == "de" else f"Ставку оновлено до €{new_rate:.2f}")
    
    await state.clear()

@router.callback_query(F.data.startswith("adm_hist_"))
async def admin_history(callback: CallbackQuery, session: AsyncSession, current_worker: Worker, locale: str):
    if not can_manage_payments(current_worker): return
    target_id = int(callback.data.split("_")[2])
    
    stmt = select(Payment).where(Payment.worker_id == target_id).order_by(Payment.period_end.desc()).limit(5)
    payments = (await session.execute(stmt)).scalars().all()
    
    text = "Letzte 5 Zahlungen:\n\n" if locale == "de" else "Останні 5 платежів:\n\n"
    for p in payments:
        start_str = p.period_start.strftime('%d.%m')
        end_str = p.period_end.strftime('%d.%m.%Y')
        text += f"[{p.status.value}] {start_str}-{end_str}: {p.hours_paid}h -> €{p.amount_paid:.2f}\n"
        
    if not payments:
        text = "Keine Historie vorhanden." if locale == "de" else "Історія відсутня."
        
    await callback.message.edit_text(text)
