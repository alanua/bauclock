from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_dashboard_main_kb(is_chief: bool, locale: str) -> InlineKeyboardMarkup:
    keys = []
    
    if is_chief:
        text_workers = "Mitarbeiter verwalten 👥" if locale == "de" else "Працівники 👥"
        text_payments = "Zahlungen verwalten 💰" if locale == "de" else "Платежі 💰"
        text_export = "DATEV Export 📊" if locale == "de" else "DATEV Експорт 📊"
        keys.append([InlineKeyboardButton(text=text_workers, callback_data="dash_workers")])
        keys.append([InlineKeyboardButton(text=text_payments, callback_data="dash_payments")])
        keys.append([InlineKeyboardButton(text=text_export, callback_data="dash_export")])
    else:
        text_history = "Meine Arbeitszeiten ⏱️" if locale == "de" else "Мої години ⏱️"
        text_payslips = "Meine Zahlungen 💰" if locale == "de" else "Мої платежі 💰"
        keys.append([InlineKeyboardButton(text=text_history, callback_data="dash_my_hours")])
        keys.append([InlineKeyboardButton(text=text_payslips, callback_data="dash_my_payments")])
        
    return InlineKeyboardMarkup(inline_keyboard=keys)

def get_payment_action_kb(payment_id: int, locale: str) -> InlineKeyboardMarkup:
    text_confirm = "Bestätigen ✅" if locale == "de" else "Підтвердити ✅"
    text_dispute = "Reklamieren ❌" if locale == "de" else "Відхилити ❌"
    
    keys = [
        [InlineKeyboardButton(text=text_confirm, callback_data=f"pay_confirm_{payment_id}")],
        [InlineKeyboardButton(text=text_dispute, callback_data=f"pay_dispute_{payment_id}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keys)
