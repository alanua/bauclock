from types import SimpleNamespace

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
