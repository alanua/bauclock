from __future__ import annotations

from typing import Any


def _has_dashboard_flag(worker: Any) -> bool:
    return bool(worker and getattr(worker, "can_view_dashboard", False))


def can_access_dashboard(worker: Any) -> bool:
    return bool(worker and getattr(worker, "is_active", False) and _has_dashboard_flag(worker))


def can_view_admin_features(worker: Any) -> bool:
    # Legacy bot admin handlers only checked can_view_dashboard, not is_active.
    return _has_dashboard_flag(worker)


def can_manage_workers(worker: Any) -> bool:
    return can_view_admin_features(worker)


def can_manage_rates(worker: Any) -> bool:
    return can_view_admin_features(worker)


def can_manage_payments(worker: Any) -> bool:
    return can_view_admin_features(worker)


def legacy_dashboard_role(worker: Any) -> str:
    return "OWNER" if worker.created_by is None else "SUPERVISOR"
