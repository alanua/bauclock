from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

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
         InlineKeyboardButton(text="Українська 🇺🇦", callback_data="lang_uk")]
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
