from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton


def get_worker_actions_kb(locale: str) -> ReplyKeyboardMarkup:
    if locale == "de":
        rows = [
            [KeyboardButton(text="⚠️ Problem"), KeyboardButton(text="📅 Kalender")],
        ]
    else:
        rows = [
            [KeyboardButton(text="⚠️ Проблема"), KeyboardButton(text="📅 Календар")],
        ]

    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
    )

def get_gdpr_kb(locale: str) -> InlineKeyboardMarkup:
    text_accept = "Ich stimme zu ✅" if locale == "de" else "Я згоден ✅"
    text_decline = "Ablehnen ❌" if locale == "de" else "Відхилити ❌"
    
    keys = [
        [InlineKeyboardButton(text=text_accept, callback_data="gdpr_accept")],
        [InlineKeyboardButton(text=text_decline, callback_data="gdpr_decline")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keys)

def get_language_kb() -> InlineKeyboardMarkup:
    keys = [
        [InlineKeyboardButton(text="Deutsch 🇩🇪", callback_data="lang_de"),
         InlineKeyboardButton(text="Українська 🇺🇦", callback_data="lang_uk")],
        [InlineKeyboardButton(text="Română 🇷🇴/🇲🇩", callback_data="lang_ro"),
         InlineKeyboardButton(text="Polski 🇵🇱", callback_data="lang_pl")],
        [InlineKeyboardButton(text="Türkçe 🇹🇷", callback_data="lang_tr"),
         InlineKeyboardButton(text="Русский 🇷🇺", callback_data="lang_ru")],
        [InlineKeyboardButton(text="English 🇬🇧", callback_data="lang_en"),
         InlineKeyboardButton(text="Български 🇧🇬", callback_data="lang_bg")],
        [InlineKeyboardButton(text="Srpski 🇷🇸", callback_data="lang_sr"),
         InlineKeyboardButton(text="Other 🌐", callback_data="lang_other")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keys)

def get_location_request_kb(locale: str) -> ReplyKeyboardMarkup:
    text = "Standort senden 📍" if locale == "de" else "Надіслати локацію 📍"
    
    # Needs a ReplyKeyboardMarkup to request location
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=text, request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    return kb


def get_problem_date_kb(locale: str) -> InlineKeyboardMarkup:
    if locale == "de":
        rows = [
            [InlineKeyboardButton(text="Heute", callback_data="problem_date_today")],
            [InlineKeyboardButton(text="Gestern", callback_data="problem_date_yesterday")],
            [InlineKeyboardButton(text="Ohne Datum", callback_data="problem_date_none")],
            [InlineKeyboardButton(text="Abbrechen", callback_data="problem_date_cancel")],
        ]
    else:
        rows = [
            [InlineKeyboardButton(text="Сьогодні", callback_data="problem_date_today")],
            [InlineKeyboardButton(text="Вчора", callback_data="problem_date_yesterday")],
            [InlineKeyboardButton(text="Без дати", callback_data="problem_date_none")],
            [InlineKeyboardButton(text="Скасувати", callback_data="problem_date_cancel")],
        ]

    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_calendar_date_kb(locale: str) -> InlineKeyboardMarkup:
    if locale == "de":
        rows = [
            [InlineKeyboardButton(text="Heute", callback_data="calendar_date_today")],
            [InlineKeyboardButton(text="Morgen", callback_data="calendar_date_tomorrow")],
            [InlineKeyboardButton(text="Gestern", callback_data="calendar_date_yesterday")],
            [InlineKeyboardButton(text="Datum waehlen", callback_data="calendar_date_custom")],
            [InlineKeyboardButton(text="Abbrechen", callback_data="calendar_date_cancel")],
        ]
    else:
        rows = [
            [InlineKeyboardButton(text="Сьогодні", callback_data="calendar_date_today")],
            [InlineKeyboardButton(text="Завтра", callback_data="calendar_date_tomorrow")],
            [InlineKeyboardButton(text="Вчора", callback_data="calendar_date_yesterday")],
            [InlineKeyboardButton(text="Вибрати дату", callback_data="calendar_date_custom")],
            [InlineKeyboardButton(text="Скасувати", callback_data="calendar_date_cancel")],
        ]

    return InlineKeyboardMarkup(inline_keyboard=rows)
