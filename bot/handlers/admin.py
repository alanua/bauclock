from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from access.legacy_policy import (
    can_manage_payments,
    can_manage_rates,
    can_manage_workers,
    can_view_admin_features,
)
from api.services.audit_logger import log_audit_event, model_snapshot
from api.services.audited_changes import apply_audited_worker_update
from bot.keyboards.chief_kb import get_cancel_kb
from db.models import Payment, Worker


router = Router()


class AdminStates(StatesGroup):
    waiting_for_worker_selection = State()
    waiting_for_action = State()
    waiting_for_new_rate = State()


def get_admin_action_kb(worker_id: int, current_worker: Worker, locale: str) -> InlineKeyboardMarkup:
    keys = []
    if can_manage_workers(current_worker):
        keys.append(
            [
                InlineKeyboardButton(
                    text="Deaktivieren" if locale == "de" else "Deactivate",
                    callback_data=f"adm_deact_{worker_id}",
                )
            ]
        )
    if can_manage_rates(current_worker):
        keys.append(
            [
                InlineKeyboardButton(
                    text="Lohn bearbeiten" if locale == "de" else "Edit rate",
                    callback_data=f"adm_edit_{worker_id}",
                )
            ]
        )
    if can_manage_payments(current_worker):
        keys.append(
            [
                InlineKeyboardButton(
                    text="Zahlungshistorie" if locale == "de" else "Payment history",
                    callback_data=f"adm_hist_{worker_id}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=keys)


@router.message(Command("admin"))
async def cmd_admin(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    current_worker: Worker,
    locale: str,
):
    if not can_view_admin_features(current_worker) or not (
        can_manage_workers(current_worker) or can_manage_payments(current_worker)
    ):
        await message.answer("Zugriff verweigert." if locale == "de" else "Access denied.")
        return

    stmt = select(Worker).where(
        Worker.company_id == current_worker.company_id,
        Worker.is_active.is_(True),
    )
    workers = (await session.execute(stmt.order_by(Worker.id.asc()))).scalars().all()

    from db.security import decrypt_string

    keys = []
    for worker in workers:
        if worker.id == current_worker.id:
            continue
        name = decrypt_string(worker.full_name_enc)
        keys.append([InlineKeyboardButton(text=name, callback_data=f"adm_sel_{worker.id}")])

    if not keys:
        await message.answer(
            "Keine aktiven Mitarbeiter gefunden." if locale == "de" else "No active workers found."
        )
        return

    text = "Waehlen Sie einen Mitarbeiter aus:" if locale == "de" else "Select a worker:"
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keys))


@router.callback_query(F.data.startswith("adm_sel_"))
async def admin_worker_selected(
    callback: CallbackQuery,
    session: AsyncSession,
    current_worker: Worker,
    locale: str,
):
    if not can_view_admin_features(current_worker) or not (
        can_manage_workers(current_worker) or can_manage_payments(current_worker)
    ):
        return

    target_id = int(callback.data.split("_")[2])
    target = await session.get(Worker, target_id)
    if not target or target.company_id != current_worker.company_id:
        return

    from db.security import decrypt_string

    name = decrypt_string(target.full_name_enc)
    rate = target.hourly_rate or 0.0
    text = (
        f"Mitarbeiter: {name}\nTyp: {target.worker_type.value}\nLohn: EUR {rate:.2f}/h\n\nAktion waehlen:"
        if locale == "de"
        else f"Worker: {name}\nType: {target.worker_type.value}\nRate: EUR {rate:.2f}/h\n\nChoose an action:"
    )
    await callback.message.edit_text(
        text,
        reply_markup=get_admin_action_kb(target_id, current_worker, locale),
    )


@router.callback_query(F.data.startswith("adm_deact_"))
async def admin_deactivate(
    callback: CallbackQuery,
    session: AsyncSession,
    current_worker: Worker,
    locale: str,
):
    if not can_manage_workers(current_worker):
        return

    target_id = int(callback.data.split("_")[2])
    target = await session.get(Worker, target_id)
    if target and target.company_id == current_worker.company_id:
        old_snapshot = model_snapshot(target, "is_active")
        target.is_active = False
        session.add(target)
        await log_audit_event(
            session,
            entity_type="worker",
            entity_id=target.id,
            action="worker_deactivated",
            old_value=old_snapshot,
            new_value=model_snapshot(target, "is_active"),
            performed_by_worker_id=current_worker.id,
            company_id=current_worker.company_id,
        )
        await session.commit()
        await callback.message.edit_text(
            "Mitarbeiter deaktiviert." if locale == "de" else "Worker deactivated."
        )


@router.callback_query(F.data.startswith("adm_edit_"))
async def admin_edit_rate(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    current_worker: Worker,
    locale: str,
):
    if not can_manage_rates(current_worker):
        return

    target_id = int(callback.data.split("_")[2])
    await state.update_data(edit_worker_id=target_id)
    text = (
        "Bitte neuen Stundenlohn eingeben:"
        if locale == "de"
        else "Please enter the new hourly rate:"
    )
    await callback.message.edit_text(text, reply_markup=get_cancel_kb(locale))
    await state.set_state(AdminStates.waiting_for_new_rate)


@router.message(AdminStates.waiting_for_new_rate)
async def process_new_rate(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    current_worker: Worker,
    locale: str,
):
    if not can_manage_rates(current_worker):
        await state.clear()
        await message.answer("Zugriff verweigert." if locale == "de" else "Access denied.")
        return

    try:
        new_rate = float((message.text or "").replace(",", "."))
    except ValueError:
        await message.answer("Ungueltige Zahl." if locale == "de" else "Invalid number.")
        return

    data = await state.get_data()
    target = await session.get(Worker, data["edit_worker_id"])
    if target and target.company_id == current_worker.company_id:
        await apply_audited_worker_update(
            session,
            worker=target,
            action="worker_hourly_rate_updated",
            performed_by_worker_id=current_worker.id,
            company_id=current_worker.company_id,
            hourly_rate=new_rate,
        )
        await session.commit()
        await message.answer(
            f"Stundenlohn aktualisiert auf EUR {new_rate:.2f}"
            if locale == "de"
            else f"Hourly rate updated to EUR {new_rate:.2f}"
        )

    await state.clear()


@router.callback_query(F.data.startswith("adm_hist_"))
async def admin_history(
    callback: CallbackQuery,
    session: AsyncSession,
    current_worker: Worker,
    locale: str,
):
    if not can_manage_payments(current_worker):
        return

    target_id = int(callback.data.split("_")[2])
    target = await session.get(Worker, target_id)
    if not target or target.company_id != current_worker.company_id:
        return

    stmt = (
        select(Payment)
        .where(Payment.worker_id == target_id)
        .order_by(Payment.period_end.desc())
        .limit(5)
    )
    payments = (await session.execute(stmt)).scalars().all()

    text = "Letzte 5 Zahlungen:\n\n" if locale == "de" else "Last 5 payments:\n\n"
    for payment in payments:
        start_str = payment.period_start.strftime("%d.%m")
        end_str = payment.period_end.strftime("%d.%m.%Y")
        text += f"[{payment.status.value}] {start_str}-{end_str}: {payment.hours_paid}h -> EUR {payment.amount_paid:.2f}\n"

    if not payments:
        text = "Keine Historie vorhanden." if locale == "de" else "No history available."

    await callback.message.edit_text(text)
