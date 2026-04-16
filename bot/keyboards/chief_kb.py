from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from db.models import WorkerType


LEGAL_FORM_OPTIONS = [
    ("gewerbe", "Gewerbe"),
    ("gmbh", "GmbH"),
    ("ug", "UG"),
    ("gbr", "GbR"),
    ("einzelunternehmen", "Einzelunternehmen"),
    ("sonstiges", "Sonstiges"),
]


def get_worker_type_kb(locale: str) -> InlineKeyboardMarkup:
    keys = [
        [InlineKeyboardButton(text="Festangestellt", callback_data=f"wtype_{WorkerType.FESTANGESTELLT.value}")],
        [InlineKeyboardButton(text="Minijob", callback_data=f"wtype_{WorkerType.MINIJOB.value}")],
        [InlineKeyboardButton(text="Gewerbe", callback_data=f"wtype_{WorkerType.GEWERBE.value}")],
        [InlineKeyboardButton(text="Subunternehmer", callback_data=f"wtype_{WorkerType.SUBUNTERNEHMER.value}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keys)


def get_cancel_kb(locale: str) -> InlineKeyboardMarkup:
    text = "Abbrechen" if locale == "de" else "Cancel"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data="cancel_action")]
    ])


def get_objektmanager_flag_kb(locale: str) -> InlineKeyboardMarkup:
    yes_text = "Ja, Dashboard-Zugang geben" if locale == "de" else "Yes, give dashboard access"
    no_text = "Nein, nur Arbeiter" if locale == "de" else "No, worker only"
    cancel_text = "Abbrechen" if locale == "de" else "Cancel"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=yes_text, callback_data="objmgr_yes")],
        [InlineKeyboardButton(text=no_text, callback_data="objmgr_no")],
        [InlineKeyboardButton(text=cancel_text, callback_data="cancel_action")],
    ])


def get_site_role_kb(locale: str) -> InlineKeyboardMarkup:
    role_text = "Generalunternehmer (Alpha)" if locale == "de" else "General contractor (alpha)"
    cancel_text = "Abbrechen" if locale == "de" else "Cancel"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=role_text, callback_data="site_role_general_contractor")],
        [InlineKeyboardButton(text=cancel_text, callback_data="cancel_action")],
    ])


def get_company_legal_form_kb(locale: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=f"legal_form_{value}")]
        for value, label in LEGAL_FORM_OPTIONS
    ])
