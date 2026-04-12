from aiogram.fsm.state import State, StatesGroup

class WorkerOnboardingStates(StatesGroup):
    waiting_for_gdpr_consent = State()
    waiting_for_language = State()


class ReportProblemStates(StatesGroup):
    waiting_for_date = State()
    waiting_for_description = State()


class CalendarViewStates(StatesGroup):
    waiting_for_date_choice = State()
    waiting_for_manual_date = State()


class TimeEventSelectionStates(StatesGroup):
    waiting_for_site_qr = State()
