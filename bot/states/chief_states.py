from aiogram.fsm.state import State, StatesGroup

class ChiefRegistrationStates(StatesGroup):
    waiting_for_owner_phone = State()
    waiting_for_company_name = State()
    waiting_for_company_phone = State()
    waiting_for_company_email = State()
    waiting_for_first_site_name = State()

class PlatformOwnerInviteStates(StatesGroup):
    waiting_for_company_name = State()

class PartnerCompanyInviteStates(StatesGroup):
    waiting_for_company_name = State()

class OwnerAlphaOnboardingStates(StatesGroup):
    waiting_for_owner_name = State()
    waiting_for_company_name = State()
    waiting_for_company_legal_form = State()
    waiting_for_company_address = State()
    waiting_for_company_email = State()

class CompanyProfileEditStates(StatesGroup):
    waiting_for_value = State()
    waiting_for_legal_form = State()

class AddSiteStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_address = State()
    waiting_for_role = State()

class AddWorkerStates(StatesGroup):
    waiting_for_worker_type = State()
    waiting_for_billing_type = State()
    waiting_for_hourly_rate = State()
    waiting_for_contract_hours = State()
    waiting_for_name = State()
    waiting_for_objektmanager_flag = State()
    waiting_for_access_role = State()
    waiting_for_role_rights_confirmation = State()

class PeopleEditStates(StatesGroup):
    waiting_for_person_selection = State()
    editing_person = State()

class AssignPartnerSiteTeamStates(StatesGroup):
    waiting_for_selection = State()
