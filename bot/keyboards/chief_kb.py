from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from db.models import WorkerAccessRole, WorkerType


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


def get_person_access_role_kb(locale: str) -> InlineKeyboardMarkup:
    cancel_text = "Abbrechen" if locale == "de" else "Cancel"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Worker" if locale == "de" else "Worker",
                callback_data=f"person_role_{WorkerAccessRole.WORKER.value}",
            )
        ],
        [
            InlineKeyboardButton(
                text="Objektmanager" if locale == "de" else "Object manager",
                callback_data=f"person_role_{WorkerAccessRole.OBJEKTMANAGER.value}",
            )
        ],
        [
            InlineKeyboardButton(
                text="Accountant" if locale == "de" else "Accountant",
                callback_data=f"person_role_{WorkerAccessRole.ACCOUNTANT.value}",
            )
        ],
        [InlineKeyboardButton(text=cancel_text, callback_data="cancel_action")],
    ])


def get_role_rights_confirm_kb(locale: str, *, expanded: bool = False) -> InlineKeyboardMarkup:
    toggle_text = "Rechte ausblenden" if expanded and locale == "de" else "Rechte anzeigen"
    if locale != "de":
        toggle_text = "Hide rights" if expanded else "Show rights"
    confirm_text = "Einladung erstellen" if locale == "de" else "Create invite"
    cancel_text = "Abbrechen" if locale == "de" else "Cancel"
    toggle_data = "role_rights_hide" if expanded else "role_rights_show"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle_text, callback_data=toggle_data)],
        [InlineKeyboardButton(text=confirm_text, callback_data="role_rights_confirm")],
        [InlineKeyboardButton(text=cancel_text, callback_data="cancel_action")],
    ])


def get_site_role_kb(locale: str) -> InlineKeyboardMarkup:
    role_text = "Generalunternehmer" if locale == "de" else "General contractor"
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


def get_company_profile_edit_kb(locale: str) -> InlineKeyboardMarkup:
    done_text = "Fertig" if locale == "de" else "Done"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Name", callback_data="company_profile_edit_name")],
        [InlineKeyboardButton(text="Rechtsform" if locale == "de" else "Legal form", callback_data="company_profile_edit_legal_form")],
        [InlineKeyboardButton(text="Adresse" if locale == "de" else "Address", callback_data="company_profile_edit_address")],
        [InlineKeyboardButton(text="E-Mail", callback_data="company_profile_edit_email")],
        [InlineKeyboardButton(text="Untertitel" if locale == "de" else "Subtitle", callback_data="company_profile_edit_subtitle")],
        [InlineKeyboardButton(text="Kurztext" if locale == "de" else "About", callback_data="company_profile_edit_about")],
        [InlineKeyboardButton(text=done_text, callback_data="company_profile_done")],
    ])
