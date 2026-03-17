from aiogram.fsm.state import State, StatesGroup

class ChiefRegistrationStates(StatesGroup):
    waiting_for_company_name = State()
    waiting_for_company_phone = State()
    waiting_for_company_email = State()
    waiting_for_first_site_name = State()

class AddWorkerStates(StatesGroup):
    waiting_for_worker_type = State()
    waiting_for_billing_type = State()
    waiting_for_hourly_rate = State()
    waiting_for_contract_hours = State()
    waiting_for_name = State()
