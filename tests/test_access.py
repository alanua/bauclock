from types import SimpleNamespace

from access.legacy_policy import (
    can_access_dashboard,
    can_manage_calendar,
    can_manage_company_profile,
    can_manage_payments,
    can_manage_rates,
    can_manage_workers,
    can_view_admin_features,
    dashboard_access_role,
    legacy_dashboard_role,
    visible_site_id,
)
from api.services.dashboard_access import get_dashboard_role
from bot.utils.access import normalize_phone, normalize_username, normalize_usernames
from db.dashboard_tokens import build_dashboard_token_payload, dashboard_token_key, parse_dashboard_token_payload


def test_normalize_username():
    assert normalize_username("@AnOleksii") == "anoleksii"
    assert normalize_username(" Torsten ") == "torsten"


def test_normalize_usernames_filters_empty_values():
    usernames = normalize_usernames(["@AnOleksii", "", "  ", "Torsten"])
    assert usernames == ["anoleksii", "torsten"]


def test_normalize_phone():
    assert normalize_phone("+49 176 8072-79824") == "49176807279824"


def test_dashboard_token_key():
    assert dashboard_token_key("abc123") == "dash_token:abc123"


def test_dashboard_token_payload_roundtrip():
    payload = build_dashboard_token_payload(worker_id=7, company_id=11)
    assert parse_dashboard_token_payload(payload) == {"worker_id": 7, "company_id": 11}


def test_dashboard_role():
    assert get_dashboard_role(SimpleNamespace(access_role="company_owner", created_by=None)) == "OWNER"
    assert get_dashboard_role(SimpleNamespace(access_role="objektmanager", created_by=7)) == "SUPERVISOR"


def test_legacy_dashboard_role():
    assert legacy_dashboard_role(SimpleNamespace(access_role="company_owner", created_by=None)) == "OWNER"
    assert legacy_dashboard_role(SimpleNamespace(access_role="objektmanager", created_by=7)) == "SUPERVISOR"


def test_worker_dashboard_flag_only_promotes_legacy_created_by_null_owner():
    legacy_owner = SimpleNamespace(
        is_active=True,
        can_view_dashboard=True,
        access_role="worker",
        created_by=None,
    )
    created_worker = SimpleNamespace(
        is_active=True,
        can_view_dashboard=True,
        access_role="worker",
        created_by=7,
    )

    assert dashboard_access_role(legacy_owner) == "company_owner"
    assert legacy_dashboard_role(legacy_owner) == "OWNER"
    assert can_access_dashboard(legacy_owner) is True
    assert can_manage_workers(legacy_owner) is True
    assert can_manage_rates(legacy_owner) is True

    assert dashboard_access_role(created_worker) == "worker"
    assert legacy_dashboard_role(created_worker) == "WORKER"
    assert can_access_dashboard(created_worker) is False
    assert can_view_admin_features(created_worker) is False
    assert can_manage_workers(created_worker) is False
    assert can_manage_rates(created_worker) is False
    assert can_manage_company_profile(created_worker) is False


def test_can_access_dashboard_requires_active_dashboard_worker():
    assert can_access_dashboard(SimpleNamespace(is_active=True, can_view_dashboard=True, access_role="company_owner")) is True
    assert can_access_dashboard(SimpleNamespace(is_active=False, can_view_dashboard=True, access_role="company_owner")) is False
    assert can_access_dashboard(SimpleNamespace(is_active=True, can_view_dashboard=False, access_role="company_owner")) is False
    assert can_access_dashboard(None) is False


def test_admin_helpers_are_role_scoped():
    owner = SimpleNamespace(is_active=True, can_view_dashboard=True, access_role="company_owner")
    accountant = SimpleNamespace(is_active=True, can_view_dashboard=True, access_role="accountant")
    objektmanager = SimpleNamespace(
        is_active=True,
        can_view_dashboard=True,
        access_role="objektmanager",
        site_id=13,
    )
    plain_worker = SimpleNamespace(is_active=True, can_view_dashboard=False, access_role="worker")

    assert can_manage_workers(owner) is True
    assert can_manage_rates(owner) is True
    assert can_manage_payments(owner) is True
    assert can_manage_calendar(owner) is True
    assert can_manage_company_profile(owner) is True
    assert can_view_admin_features(owner) is True

    assert can_manage_workers(accountant) is False
    assert can_manage_rates(accountant) is False
    assert can_manage_payments(accountant) is True
    assert can_manage_calendar(accountant) is False
    assert can_manage_company_profile(accountant) is False
    assert can_view_admin_features(accountant) is True
    assert visible_site_id(accountant) is None

    assert can_manage_workers(objektmanager) is False
    assert can_manage_rates(objektmanager) is False
    assert can_manage_payments(objektmanager) is False
    assert can_manage_calendar(objektmanager) is True
    assert can_manage_company_profile(objektmanager) is False
    assert can_view_admin_features(objektmanager) is True
    assert visible_site_id(objektmanager) == 13

    assert can_manage_workers(plain_worker) is False
    assert can_manage_rates(plain_worker) is False
    assert can_manage_payments(plain_worker) is False
    assert can_view_admin_features(plain_worker) is False
