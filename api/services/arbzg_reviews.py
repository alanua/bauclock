from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ArbzgFinding, ArbzgFindingState, Worker


VALID_ARBZG_FINDING_STATES = {
    ArbzgFindingState.OPEN.value,
    ArbzgFindingState.REVIEWED.value,
    ArbzgFindingState.RESOLVED.value,
    ArbzgFindingState.DISMISSED.value,
}


def _normalize_state(state: str) -> str:
    normalized = (state or "").strip().casefold()
    if normalized not in VALID_ARBZG_FINDING_STATES:
        raise ValueError("invalid_arbzg_finding_state")
    return normalized


def _normalize_text(value: str | None) -> str | None:
    normalized = (value or "").strip()
    return normalized or None


def serialize_arbzg_finding(finding: ArbzgFinding) -> dict[str, object]:
    return {
        "id": int(finding.id),
        "company_id": int(finding.company_id),
        "worker_id": int(finding.worker_id),
        "target_date": finding.target_date.isoformat(),
        "finding_code": str(finding.finding_code),
        "severity": str(finding.severity),
        "state": str(finding.state),
        "state_reason": finding.state_reason,
        "created_by_worker_id": finding.created_by_worker_id,
        "updated_by_worker_id": finding.updated_by_worker_id,
        "created_at": finding.created_at.isoformat() if finding.created_at else None,
        "updated_at": finding.updated_at.isoformat() if finding.updated_at else None,
    }


async def _require_worker_company_scope(
    db: AsyncSession,
    *,
    company_id: int,
    worker_id: int,
) -> None:
    worker = await db.get(Worker, worker_id)
    if worker is None or int(worker.company_id) != int(company_id):
        raise ValueError("arbzg_worker_company_scope_denied")


async def open_arbzg_finding(
    db: AsyncSession,
    *,
    company_id: int,
    worker_id: int,
    target_date: date,
    finding_code: str,
    severity: str,
    actor_worker_id: int | None = None,
) -> ArbzgFinding:
    await _require_worker_company_scope(db, company_id=company_id, worker_id=worker_id)
    normalized_code = (finding_code or "").strip()
    normalized_severity = (severity or "").strip() or "warning"
    if not normalized_code:
        raise ValueError("finding_code_required")

    finding = await db.scalar(
        select(ArbzgFinding).where(
            ArbzgFinding.company_id == company_id,
            ArbzgFinding.worker_id == worker_id,
            ArbzgFinding.target_date == target_date,
            ArbzgFinding.finding_code == normalized_code,
        )
    )

    if finding is None:
        finding = ArbzgFinding(
            company_id=company_id,
            worker_id=worker_id,
            target_date=target_date,
            finding_code=normalized_code,
            severity=normalized_severity,
            state=ArbzgFindingState.OPEN.value,
            created_by_worker_id=actor_worker_id,
            updated_by_worker_id=actor_worker_id,
        )
        db.add(finding)
        await db.flush()
        return finding

    finding.severity = normalized_severity
    finding.state = ArbzgFindingState.OPEN.value
    finding.state_reason = None
    finding.updated_by_worker_id = actor_worker_id
    db.add(finding)
    await db.flush()
    return finding


async def set_arbzg_finding_state(
    db: AsyncSession,
    *,
    finding_id: int,
    company_id: int,
    state: str,
    actor_worker_id: int | None = None,
    reason: str | None = None,
) -> ArbzgFinding:
    finding = await db.get(ArbzgFinding, finding_id)
    if finding is None:
        raise ValueError("arbzg_finding_not_found")
    if int(finding.company_id) != int(company_id):
        raise ValueError("arbzg_finding_scope_denied")

    finding.state = _normalize_state(state)
    finding.state_reason = _normalize_text(reason)
    finding.updated_by_worker_id = actor_worker_id
    db.add(finding)
    await db.flush()
    return finding


async def list_arbzg_findings(
    db: AsyncSession,
    *,
    company_id: int,
    target_date: date | None = None,
    worker_id: int | None = None,
    state: str | None = None,
) -> list[dict[str, object]]:
    stmt = (
        select(ArbzgFinding)
        .where(ArbzgFinding.company_id == company_id)
        .order_by(
            ArbzgFinding.target_date.desc(),
            ArbzgFinding.worker_id.asc(),
            ArbzgFinding.finding_code.asc(),
            ArbzgFinding.id.asc(),
        )
    )
    if target_date is not None:
        stmt = stmt.where(ArbzgFinding.target_date == target_date)
    if worker_id is not None:
        stmt = stmt.where(ArbzgFinding.worker_id == worker_id)
    if state is not None:
        stmt = stmt.where(ArbzgFinding.state == _normalize_state(state))

    findings = (await db.execute(stmt)).scalars().all()
    return [serialize_arbzg_finding(finding) for finding in findings]


async def load_arbzg_finding_map(
    db: AsyncSession,
    *,
    company_id: int,
    target_date: date,
    worker_ids: list[int] | None = None,
) -> dict[tuple[int, str], dict[str, object]]:
    stmt = select(ArbzgFinding).where(
        ArbzgFinding.company_id == company_id,
        ArbzgFinding.target_date == target_date,
    )
    if worker_ids:
        stmt = stmt.where(ArbzgFinding.worker_id.in_(worker_ids))

    findings = (await db.execute(stmt)).scalars().all()
    return {
        (int(finding.worker_id), str(finding.finding_code)): serialize_arbzg_finding(finding)
        for finding in findings
    }
