from __future__ import annotations

from typing import Any


COMPANY_OWNER_ROLE = "company_owner"
OBJEKTMANAGER_ROLE = "objektmanager"
ACCOUNTANT_ROLE = "accountant"
WORKER_ROLE = "worker"

_DASHBOARD_ROLES = {
    COMPANY_OWNER_ROLE,
    OBJEKTMANAGER_ROLE,
    ACCOUNTANT_ROLE,
}


def _has_dashboard_flag(worker: Any) -> bool:
    return bool(worker and getattr(worker, "can_view_dashboard", False))


def dashboard_access_role(worker: Any) -> str:
    if not worker:
        return WORKER_ROLE
    role = str(getattr(worker, "access_role", "") or "").strip().casefold()
    if role and role != WORKER_ROLE:
        return role
    if _has_dashboard_flag(worker) and getattr(worker, "created_by", None) is None:
        return COMPANY_OWNER_ROLE
    return role or WORKER_ROLE


def can_access_dashboard(worker: Any) -> bool:
    return bool(
        worker
        and getattr(worker, "is_active", False)
        and _has_dashboard_flag(worker)
        and dashboard_access_role(worker) in _DASHBOARD_ROLES
    )


def can_view_admin_features(worker: Any) -> bool:
    return can_access_dashboard(worker)


def can_manage_workers(worker: Any) -> bool:
    return bool(can_access_dashboard(worker) and dashboard_access_role(worker) == COMPANY_OWNER_ROLE)


def can_manage_rates(worker: Any) -> bool:
    return can_manage_workers(worker)


def can_manage_payments(worker: Any) -> bool:
    return bool(
        can_access_dashboard(worker)
        and dashboard_access_role(worker) in {COMPANY_OWNER_ROLE, ACCOUNTANT_ROLE}
    )


def can_manage_calendar(worker: Any) -> bool:
    return bool(
        can_access_dashboard(worker)
        and dashboard_access_role(worker) in {COMPANY_OWNER_ROLE, OBJEKTMANAGER_ROLE}
    )


def can_manage_company_profile(worker: Any) -> bool:
    return can_manage_workers(worker)


def visible_site_id(worker: Any) -> int | None:
    if dashboard_access_role(worker) == OBJEKTMANAGER_ROLE:
        return getattr(worker, "site_id", None)
    return None


def legacy_dashboard_role(worker: Any) -> str:
    role = dashboard_access_role(worker)
    if role == COMPANY_OWNER_ROLE:
        return "OWNER"
    if role == ACCOUNTANT_ROLE:
        return "ACCOUNTANT"
    if role == OBJEKTMANAGER_ROLE:
        return "SUPERVISOR"
    return "WORKER"
