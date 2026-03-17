from aiogram.fsm.state import State, StatesGroup

class DashboardStates(StatesGroup):
    waiting_for_payment_dispute = State()
