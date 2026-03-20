from enum import Enum
from db.models import LanguageSupport

TRANSLATIONS = {
    "welcome": {
        "de": "Willkommen bei SEK Zeiterfassung!",
        "uk": "Ласкаво просимо до SEK Zeiterfassung!",
        "ro": "Bun venit la SEK Zeiterfassung!",
        "pl": "Witamy w SEK Zeiterfassung!",
        "tr": "SEK Zeiterfassung'a hoş geldiniz!",
        "ru": "Добро пожаловать в SEK Zeiterfassung!",
        "en": "Welcome to SEK Zeiterfassung!",
        "bg": "Добре дошли в SEK Zeiterfassung!",
        "sr": "Dobrodošli u SEK Zeiterfassung!",
        "other": "Welcome to SEK Zeiterfassung!"
    },
    "gdpr_text": {
        "de": "Um fortzufahren, müssen wir Ihre Telegram ID und Ihren Namen verarbeiten. Diese Daten werden nach AES-256 Standard verschlüsselt in unserer Datenbank in Deutschland gespeichert. Die GPS-Daten Ihres Geräts werden nur im Moment des Einscannens eines QR-Codes zur Standortverifizierung erhoben und nicht dauerhaft getrackt. Stimmen Sie der Verarbeitung gemäß DSGVO zu?",
        "uk": "Щоб продовжити, ми повинні обробляти ваш Telegram ID та ім'я. Ці дані шифруються за стандартом AES-256. Дані GPS використовуються лише під час сканування QR-коду. Чи погоджуєтеся ви з обробкою згідно з GDPR?",
        "ro": "Pentru a continua, trebuie să procesăm ID-ul tău Telegram și numele tău. Aceste date sunt stocate criptat AES-256. Datele GPS sunt colectate doar în momentul scanării unui cod QR. Ești de acord cu procesarea conform GDPR?",
        "pl": "Aby kontynuować, musimy przetwarzać Twój identyfikator Telegram i imię. Dane te są szyfrowane AES-256. Dane GPS są pobierane tylko podczas skanowania kodu QR. Czy wyrażasz zgodę na przetwarzanie zgodnie z RODO?",
        "tr": "Devam etmek için Telegram ID'nizi ve adınızı işlememiz gerekiyor. Bu veriler AES-256 ile şifrelenir. GPS verileri yalnızca QR kod taraması sırasında alınır. GDPR uyarınca işlemeyi onaylıyor musunuz?",
        "ru": "Для продолжения мы должны обрабатывать ваш Telegram ID и имя. Эти данные зашифрованы по стандарту AES-256. Данные GPS собираются только во время сканирования QR-кода. Вы согласны на обработку согласно GDPR?",
        "en": "To continue, we need to process your Telegram ID and name. This data is encrypted using AES-256. GPS data is only collected when scanning a QR code. Do you agree to the processing in accordance with GDPR?",
        "bg": "За да продължите, трябва да обработим вашия Telegram ID и име. Тези данни са криптирани с AES-256. GPS данните се събират само при сканиране на QR код. Съгласни ли сте с обработката съгласно GDPR?",
        "sr": "Da biste nastavili, moramo da obradimo vaš Telegram ID i ime. Ovi podaci su šifrovani AES-256. GPS podaci se prikupljaju samo prilikom skeniranja QR koda. Da li se slažete sa obradom u skladu sa GDPR?",
        "other": "To continue, we need to process your Telegram ID and name. This data is encrypted using AES-256. GPS data is only collected when scanning a QR code. Do you agree to the processing in accordance with GDPR?"
    },
    "checkin_success": {
        "de": "Check-in erfolgreich! 👷‍♂️",
        "uk": "Чек-ін успішний! 👷‍♂️",
        "ro": "Check-in reușit! 👷‍♂️",
        "pl": "Odprawa zakończona sukcesem! 👷‍♂️",
        "tr": "Check-in başarılı! 👷‍♂️",
        "ru": "Чекин успешен! 👷‍♂️",
        "en": "Check-in successful! 👷‍♂️",
        "bg": "Успешно чекиране! 👷‍♂️",
        "sr": "Uspešna prijava! 👷‍♂️",
        "other": "Check-in successful! 👷‍♂️"
    },
    "pause_start": {
        "de": "Pause gestartet ☕",
        "uk": "Пауза розпочата ☕",
        "ro": "Pauza a început ☕",
        "pl": "Przerwa rozpoczęta ☕",
        "tr": "Mola başladı ☕",
        "ru": "Пауза начата ☕",
        "en": "Pause started ☕",
        "bg": "Паузата започна ☕",
        "sr": "Pauza je počela ☕",
        "other": "Pause started ☕"
    },
    "pause_end": {
        "de": "Pause beendet. Zurück an die Arbeit! 🔨",
        "uk": "Пауза завершена. До роботи! 🔨",
        "ro": "Pauza s-a terminat. Înapoi la muncă! 🔨",
        "pl": "Koniec przerwy. Wracaj do pracy! 🔨",
        "tr": "Mola bitti. İşe dönün! 🔨",
        "ru": "Пауза завершена. За работу! 🔨",
        "en": "Pause ended. Back to work! 🔨",
        "bg": "Край на паузата. Обратно на работа! 🔨",
        "sr": "Pauza je završena. Nazad na posao! 🔨",
        "other": "Pause ended. Back to work! 🔨"
    },
    "checkout_summary": {
        "de": "Check-out erfolgreich! Schönen Feierabend. 🌅",
        "uk": "Чек-аут успішний! Гарного вечора. 🌅",
        "ro": "Check-out reușit! O seară frumoasă. 🌅",
        "pl": "Wymeldowanie udane! Miłego wieczoru. 🌅",
        "tr": "Çıkış başarılı! İyi akşamlar. 🌅",
        "ru": "Чекаут успешен! Хорошего вечера. 🌅",
        "en": "Check-out successful! Have a great evening. 🌅",
        "bg": "Успешно отписване! Приятна вечер. 🌅",
        "sr": "Uspešna odjava! Prijatno veče. 🌅",
        "other": "Check-out successful! Have a great evening. 🌅"
    },
    "register_complete": {
        "de": "Erfolgreich registriert! Sie können nun QR-Codes auf der Baustelle scannen.",
        "uk": "Успішно зареєстровано! Тепер ви можете сканувати QR-коди на об'єкті.",
        "ro": "Înregistrare reușită! Acum poți scana coduri QR pe șantier.",
        "pl": "Rejestracja pomyślna! Teraz możesz skanować kody QR na budowie.",
        "tr": "Başarıyla kaydedildi! Artık şantiyedeki QR kodları tarayabilirsiniz.",
        "ru": "Успешно зарегистрировано! Теперь вы можете сканировать QR-коды на объекте.",
        "en": "Registered successfully! You can now scan QR codes on site.",
        "bg": "Успешна регистрация! Вече можете да сканирате QR кодове на обекта.",
        "sr": "Uspešno registrovano! Sada možete skenirati QR kodove na gradilištu.",
        "other": "Registered successfully! You can now scan QR codes on site."
    },
    "arbzg_warning": {
        "de": "Achtung: ArbZG Limit erreicht!",
        "uk": "Увага: Досягнуто ліміт ArbZG!",
        "ro": "Atenție: Limita ArbZG atinsă!",
        "pl": "Uwaga: Osiągnięto limit ArbZG!",
        "tr": "Dikkat: ArbZG limitine ulaşıldı!",
        "ru": "Внимание: Достигнут лимит ArbZG!",
        "en": "Warning: ArbZG limit reached!",
        "bg": "Внимание: Достигнат е лимитът на ArbZG!",
        "sr": "Upozorenje: Dostignut ArbZG limit!",
        "other": "Warning: ArbZG limit reached!"
    },
    "payment_request": {
        "de": "Zahlung angefragt.",
        "uk": "Запит на оплату.",
        "ro": "Plată solicitată.",
        "pl": "Płatność zażądana.",
        "tr": "Ödeme talep edildi.",
        "ru": "Оплата запрошена.",
        "en": "Payment requested.",
        "bg": "Заявено плащане.",
        "sr": "Plaćanje je zatraženo.",
        "other": "Payment requested."
    },
    "payment_confirmed": {
        "de": "Zahlung bestätigt.",
        "uk": "Оплату підтверджено.",
        "ro": "Plată confirmată.",
        "pl": "Płatność potwierdzona.",
        "tr": "Ödeme onaylandı.",
        "ru": "Оплата подтверждена.",
        "en": "Payment confirmed.",
        "bg": "Плащането е потвърдено.",
        "sr": "Plaćanje je potvrđeno.",
        "other": "Payment confirmed."
    },
    "payment_disputed": {
        "de": "Zahlung reklamiert.",
        "uk": "Оплату оскаржено.",
        "ro": "Plată contestată.",
        "pl": "Płatność kwestionowana.",
        "tr": "Ödeme itiraz edildi.",
        "ru": "Оплата оспорена.",
        "en": "Payment disputed.",
        "bg": "Оспорвано плащане.",
        "sr": "Plaćanje osporeno.",
        "other": "Payment disputed."
    },
    "day_not_closed": {
        "de": "Tag nicht geschlossen.",
        "uk": "День не закрито.",
        "ro": "Zi neînchisă.",
        "pl": "Dzień niezakończony.",
        "tr": "Gün kapanmadı.",
        "ru": "День не закрыт.",
        "en": "Day not closed.",
        "bg": "Денят не е приключен.",
        "sr": "Dan nije završen.",
        "other": "Day not closed."
    }
}

def t(key: str, locale: str) -> str:
    # default to "de" if locale not found or if not present in translation dict
    return TRANSLATIONS.get(key, {}).get(locale, TRANSLATIONS.get(key, {}).get("de", key))
