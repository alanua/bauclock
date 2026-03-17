from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from db.models import WorkerType

def get_worker_type_kb(locale: str) -> InlineKeyboardMarkup:
    # A simple keyboard to select the worker type
    keys = [
        [InlineKeyboardButton(text="Festangestellt", callback_data=f"wtype_{WorkerType.FESTANGESTELLT.value}")],
        [InlineKeyboardButton(text="Minijob", callback_data=f"wtype_{WorkerType.MINIJOB.value}")],
        [InlineKeyboardButton(text="Gewerbe", callback_data=f"wtype_{WorkerType.GEWERBE.value}")],
        [InlineKeyboardButton(text="Subunternehmer", callback_data=f"wtype_{WorkerType.SUBUNTERNEHMER.value}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keys)

def get_cancel_kb(locale: str) -> InlineKeyboardMarkup:
    text = "Abbrechen ❌" if locale == "de" else "Скасувати ❌"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data="cancel_action")]
    ])
