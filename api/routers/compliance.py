from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from access.legacy_policy import dashboard_access_role
from api.redis_client import redis_client
from api.services.arbzg_reporting import build_company_arbzg_day_report
from api.services.arbzg_reviews import (
    list_arbzg_findings,
    open_arbzg_finding,
    serialize_arbzg_finding,
    set_arbzg_finding_state,
)
from api.services.dashboard_access import DashboardAccessError, get_dashboard_worker
from api.services.legal_acceptance import get_legal_acceptance_overview
from api.services.retention import run_retention_cycle
from db.database import get_db
from db.models import Worker
from db.security import decrypt_string


router = APIRouter()


class ArbzgFindingOpenRequest(BaseModel):
    worker_id: int
    target_date: date
    finding_code: str
    severity: str = "warning"


class ArbzgFindingStateUpdateRequest(BaseModel):
    state: str
    reason: str | None = None


def _compliance_access_denied() -> HTTPException:
    return HTTPException(status_code=403, detail="Forbidden")


def _compliance_bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=400, detail=detail)


def _require_compliance_company_scope(actor_worker: Worker, company_id: int | None) -> int:
    scoped_company_id = actor_worker.company_id
    if company_id is not None and company_id != scoped_company_id:
        raise DashboardAccessError("compliance_company_scope_denied")
    if dashboard_access_role(actor_worker) not in {"company_owner", "accountant"}:
        raise DashboardAccessError("compliance_access_denied")
    return int(scoped_company_id)


async def _worker_names_by_id(
    db: AsyncSession,
    *,
    company_id: int,
    worker_ids: list[int],
) -> dict[int, str]:
    if not worker_ids:
        return {}
    workers = (
        await db.execute(
            select(Worker).where(
                Worker.company_id == company_id,
                Worker.id.in_(worker_ids),
            )
        )
    ).scalars().all()
    return {
        int(worker.id): decrypt_string(worker.full_name_enc)
        for worker in workers
    }


@router.get("/compliance/legal-overview")
async def compliance_legal_overview(
    token: str | None = Query(default=None),
    company_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    try:
        actor_worker = await get_dashboard_worker(token, db, redis_client)
        scoped_company_id = _require_compliance_company_scope(actor_worker, company_id)
        overview = await get_legal_acceptance_overview(db, company_id=scoped_company_id)
    except DashboardAccessError as exc:
        raise _compliance_access_denied() from exc

    incomplete_worker_ids = [
        int(item["worker_id"])
        for item in overview["incomplete_workers"]
    ]
    names_by_id = await _worker_names_by_id(
        db,
        company_id=scoped_company_id,
        worker_ids=incomplete_worker_ids,
    )
    incomplete_workers = [
        {
            **item,
            "name": names_by_id.get(int(item["worker_id"]), f"worker-{int(item['worker_id'])}"),
        }
        for item in overview["incomplete_workers"]
    ]
    return {
        "company_id": scoped_company_id,
        "company_documents_complete": overview["company_documents_complete"],
        "company_documents": overview["company_document_states"],
        "worker_notice_completion": overview["worker_notice_completion"],
        "gps_site_presence_requirement_counts": overview["gps_site_presence_requirement_counts"],
        "worker_notice_states": overview["worker_notice_states"],
        "incomplete_workers": incomplete_workers,
    }


@router.get("/compliance/retention-report")
async def compliance_retention_report(
    token: str | None = Query(default=None),
    company_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    try:
        actor_worker = await get_dashboard_worker(token, db, redis_client)
        scoped_company_id = _require_compliance_company_scope(actor_worker, company_id)
    except DashboardAccessError as exc:
        raise _compliance_access_denied() from exc

    return await run_retention_cycle(
        db,
        company_id=scoped_company_id,
        destructive=False,
        redis_client=redis_client,
    )


@router.get("/compliance/arbzg-report")
async def compliance_arbzg_report(
    token: str | None = Query(default=None),
    company_id: int | None = Query(default=None),
    target_day: date = Query(...),
    db: AsyncSession = Depends(get_db),
):
    try:
        actor_worker = await get_dashboard_worker(token, db, redis_client)
        scoped_company_id = _require_compliance_company_scope(actor_worker, company_id)
    except DashboardAccessError as exc:
        raise _compliance_access_denied() from exc

    return await build_company_arbzg_day_report(
        db,
        company_id=scoped_company_id,
        target_day=target_day,
    )


@router.get("/compliance/arbzg-findings")
async def compliance_arbzg_findings(
    token: str | None = Query(default=None),
    company_id: int | None = Query(default=None),
    target_day: date | None = Query(default=None),
    state: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    try:
        actor_worker = await get_dashboard_worker(token, db, redis_client)
        scoped_company_id = _require_compliance_company_scope(actor_worker, company_id)
    except DashboardAccessError as exc:
        raise _compliance_access_denied() from exc

    try:
        return {
            "company_id": scoped_company_id,
            "items": await list_arbzg_findings(
                db,
                company_id=scoped_company_id,
                target_date=target_day,
                state=state,
            ),
        }
    except ValueError as exc:
        raise _compliance_bad_request(str(exc)) from exc


@router.post("/compliance/arbzg-findings/open")
async def compliance_open_arbzg_review_finding(
    payload: ArbzgFindingOpenRequest,
    token: str | None = Query(default=None),
    company_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    try:
        actor_worker = await get_dashboard_worker(token, db, redis_client)
        scoped_company_id = _require_compliance_company_scope(actor_worker, company_id)
    except DashboardAccessError as exc:
        raise _compliance_access_denied() from exc

    try:
        finding = await open_arbzg_finding(
            db,
            company_id=scoped_company_id,
            worker_id=payload.worker_id,
            target_date=payload.target_date,
            finding_code=payload.finding_code,
            severity=payload.severity,
            actor_worker_id=actor_worker.id,
        )
    except ValueError as exc:
        raise _compliance_bad_request(str(exc)) from exc

    await db.commit()
    await db.refresh(finding)
    return serialize_arbzg_finding(finding)


@router.post("/compliance/arbzg-findings/{finding_id}/state")
async def compliance_update_arbzg_review_finding(
    finding_id: int,
    payload: ArbzgFindingStateUpdateRequest,
    token: str | None = Query(default=None),
    company_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    try:
        actor_worker = await get_dashboard_worker(token, db, redis_client)
        scoped_company_id = _require_compliance_company_scope(actor_worker, company_id)
    except DashboardAccessError as exc:
        raise _compliance_access_denied() from exc

    try:
        finding = await set_arbzg_finding_state(
            db,
            finding_id=finding_id,
            company_id=scoped_company_id,
            state=payload.state,
            reason=payload.reason,
            actor_worker_id=actor_worker.id,
        )
    except ValueError as exc:
        raise _compliance_bad_request(str(exc)) from exc

    await db.commit()
    await db.refresh(finding)
    return serialize_arbzg_finding(finding)
