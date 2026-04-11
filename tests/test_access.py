from types import SimpleNamespace

from access.legacy_policy import (
    can_access_dashboard,
    can_manage_payments,
    can_manage_rates,
    can_manage_workers,
    can_view_admin_features,
    legacy_dashboard_role,
)
from api.services.dashboard_access import get_dashboard_role
from bot.utils.access import normalize_phone, normalize_username, normalize_usernames
from db.dashboard_tokens import dashboard_token_key


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


def test_dashboard_role():
    assert get_dashboard_role(SimpleNamespace(created_by=None)) == "OWNER"
    assert get_dashboard_role(SimpleNamespace(created_by=7)) == "SUPERVISOR"


def test_legacy_dashboard_role():
    assert legacy_dashboard_role(SimpleNamespace(created_by=None)) == "OWNER"
    assert legacy_dashboard_role(SimpleNamespace(created_by=7)) == "SUPERVISOR"


def test_can_access_dashboard_requires_active_dashboard_worker():
    assert can_access_dashboard(SimpleNamespace(is_active=True, can_view_dashboard=True)) is True
    assert can_access_dashboard(SimpleNamespace(is_active=False, can_view_dashboard=True)) is False
    assert can_access_dashboard(SimpleNamespace(is_active=True, can_view_dashboard=False)) is False
    assert can_access_dashboard(None) is False


def test_legacy_admin_helpers_preserve_dashboard_flag_semantics():
    dashboard_worker = SimpleNamespace(is_active=False, can_view_dashboard=True)
    plain_worker = SimpleNamespace(is_active=True, can_view_dashboard=False)

    helpers = [
        can_manage_workers,
        can_manage_rates,
        can_manage_payments,
        can_view_admin_features,
    ]

    for helper in helpers:
        assert helper(dashboard_worker) is True
        assert helper(plain_worker) is False
        assert helper(None) is False
