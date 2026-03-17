from aiogram.fsm.state import State, StatesGroup

class WorkerOnboardingStates(StatesGroup):
    waiting_for_gdpr_consent = State()
    waiting_for_language = State()
