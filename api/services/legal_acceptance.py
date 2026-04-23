from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.legal_acceptance_requirements import (
    GPS_SITE_PRESENCE_NOTICE_DOCUMENT,
    GPS_REQUIREMENT_REQUIRED,
    PRIVACY_NOTICE_DOCUMENT,
    TIME_TRACKING_NOTICE_DOCUMENT,
    required_worker_document_types,
    resolve_worker_gps_site_presence_requirements,
)
from db.models import LegalAcceptanceLog, Worker


COMPANY_DOCUMENT_VERSIONS = {
    "saas_terms": "2026-04-de-v1",
    "avv_dpa": "2026-04-de-v1",
    "privacy_toms_retention_subprocessors": "2026-04-de-v1",
}

WORKER_DOCUMENT_VERSIONS = {
    PRIVACY_NOTICE_DOCUMENT: "2026-04-de-v1",
    TIME_TRACKING_NOTICE_DOCUMENT: "2026-04-de-v1",
    GPS_SITE_PRESENCE_NOTICE_DOCUMENT: "2026-04-de-v1",
}

COMPANY_DOCUMENT_ACTIONS = {
    "saas_terms": "accepted",
    "avv_dpa": "accepted",
    "privacy_toms_retention_subprocessors": "acknowledged",
}

WORKER_DOCUMENT_ACTIONS = {
    PRIVACY_NOTICE_DOCUMENT: "acknowledged",
    TIME_TRACKING_NOTICE_DOCUMENT: "acknowledged",
    GPS_SITE_PRESENCE_NOTICE_DOCUMENT: "acknowledged",
}


def _require_text(value: str, *, error_code: str) -> str:
    normalized = (value or "").strip()
    if not normalized:
        raise ValueError(error_code)
    return normalized


async def record_legal_acceptance(
    db: AsyncSession,
    *,
    actor_type: str,
    actor_id: int,
    company_id: int | None,
    document_type: str,
    document_version: str,
    action_type: str,
) -> LegalAcceptanceLog:
    normalized_actor_type = _require_text(actor_type, error_code="actor_type_required")
    normalized_document_type = _require_text(document_type, error_code="document_type_required")
    normalized_document_version = _require_text(document_version, error_code="document_version_required")
    normalized_action_type = _require_text(action_type, error_code="action_type_required")
    if normalized_action_type not in {"accepted", "acknowledged"}:
        raise ValueError("invalid_action_type")

    row = LegalAcceptanceLog(
        actor_type=normalized_actor_type,
        actor_id=actor_id,
        company_id=company_id,
        document_type=normalized_document_type,
        document_version=normalized_document_version,
        action_type=normalized_action_type,
    )
    db.add(row)
    await db.flush()
    return row


async def record_company_onboarding_acceptance(
    db: AsyncSession,
    *,
    actor_worker_id: int,
    company_id: int,
) -> None:
    for document_type, document_version in COMPANY_DOCUMENT_VERSIONS.items():
        await record_legal_acceptance(
            db,
            actor_type="worker",
            actor_id=actor_worker_id,
            company_id=company_id,
            document_type=document_type,
            document_version=document_version,
            action_type=COMPANY_DOCUMENT_ACTIONS[document_type],
        )


async def record_worker_onboarding_acknowledgements(
    db: AsyncSession,
    *,
    worker_id: int,
    company_id: int,
    gps_notice_enabled: bool | None = None,
) -> None:
    gps_notice_required = bool(gps_notice_enabled)
    if gps_notice_enabled is None:
        worker = await db.get(Worker, worker_id)
        if worker is None:
            raise ValueError("worker_not_found")
        gps_requirements = await resolve_worker_gps_site_presence_requirements(
            db,
            workers=[worker],
        )
        gps_notice_required = (
            gps_requirements[int(worker.id)].state == GPS_REQUIREMENT_REQUIRED
        )

    for document_type, document_version in WORKER_DOCUMENT_VERSIONS.items():
        if document_type == GPS_SITE_PRESENCE_NOTICE_DOCUMENT and not gps_notice_required:
            continue
        await record_legal_acceptance(
            db,
            actor_type="worker",
            actor_id=worker_id,
            company_id=company_id,
            document_type=document_type,
            document_version=document_version,
            action_type=WORKER_DOCUMENT_ACTIONS[document_type],
        )


def _company_document_state_from_row(
    row: LegalAcceptanceLog | None,
    *,
    document_type: str,
) -> dict[str, object]:
    required_version = COMPANY_DOCUMENT_VERSIONS[document_type]
    required_action = COMPANY_DOCUMENT_ACTIONS[document_type]
    completed = bool(
        row
        and row.document_version == required_version
        and row.action_type == required_action
    )
    return {
        "document_type": document_type,
        "required": True,
        "required_version": required_version,
        "required_action_type": required_action,
        "completed": completed,
        "accepted_version": row.document_version if row else None,
        "accepted_action_type": row.action_type if row else None,
        "accepted_at": row.created_at.isoformat() if row and row.created_at else None,
    }


async def get_legal_acceptance_overview(
    db: AsyncSession,
    *,
    company_id: int,
) -> dict[str, object]:
    active_workers = (
        await db.execute(
            select(Worker)
            .where(
                Worker.company_id == company_id,
                Worker.is_active.is_(True),
            )
            .order_by(Worker.id.asc())
        )
    ).scalars().all()
    active_worker_total = len(active_workers)

    company_document_rows = (
        await db.execute(
            select(LegalAcceptanceLog)
            .where(
                LegalAcceptanceLog.company_id == company_id,
                LegalAcceptanceLog.document_type.in_(tuple(COMPANY_DOCUMENT_VERSIONS.keys())),
            )
            .order_by(
                LegalAcceptanceLog.document_type.asc(),
                LegalAcceptanceLog.created_at.desc(),
                LegalAcceptanceLog.id.desc(),
            )
        )
    ).scalars().all()
    latest_company_document_rows: dict[str, LegalAcceptanceLog] = {}
    for row in company_document_rows:
        latest_company_document_rows.setdefault(row.document_type, row)

    company_document_states = {
        document_type: _company_document_state_from_row(
            latest_company_document_rows.get(document_type),
            document_type=document_type,
        )
        for document_type in COMPANY_DOCUMENT_VERSIONS
    }
    company_documents = {
        document_type: bool(state["completed"])
        for document_type, state in company_document_states.items()
    }

    worker_document_rows = (
        await db.execute(
            select(LegalAcceptanceLog)
            .where(
                LegalAcceptanceLog.company_id == company_id,
                LegalAcceptanceLog.actor_type == "worker",
                LegalAcceptanceLog.document_type.in_(tuple(WORKER_DOCUMENT_VERSIONS.keys())),
            )
            .order_by(LegalAcceptanceLog.created_at.desc(), LegalAcceptanceLog.id.desc())
        )
    ).scalars().all()
    accepted_documents_by_worker: dict[int, dict[str, LegalAcceptanceLog]] = {}
    for row in worker_document_rows:
        worker_documents = accepted_documents_by_worker.setdefault(int(row.actor_id), {})
        worker_documents.setdefault(row.document_type, row)

    gps_requirements = await resolve_worker_gps_site_presence_requirements(
        db,
        workers=active_workers,
    )
    worker_notice_states: list[dict[str, object]] = []
    completed_worker_count = 0
    gps_requirement_counts = {
        "required": 0,
        "not_required": 0,
        "not_applicable": 0,
    }
    for worker in active_workers:
        gps_requirement = gps_requirements[int(worker.id)]
        required_documents = required_worker_document_types(
            worker,
            gps_requirement=gps_requirement,
        )
        accepted_documents = accepted_documents_by_worker.get(int(worker.id), {})
        completed_documents = [
            document_type
            for document_type in required_documents
            if (
                accepted_documents.get(document_type) is not None
                and accepted_documents[document_type].document_version == WORKER_DOCUMENT_VERSIONS[document_type]
                and accepted_documents[document_type].action_type == WORKER_DOCUMENT_ACTIONS[document_type]
            )
        ]
        missing_documents = [
            document_type
            for document_type in required_documents
            if document_type not in completed_documents
        ]
        gps_requirement_counts[gps_requirement.state] += 1
        state = {
            "worker_id": int(worker.id),
            "required_documents": required_documents,
            "completed_documents": completed_documents,
            "missing_documents": missing_documents,
            "gps_site_presence_requirement": {
                "state": gps_requirement.state,
                "source": gps_requirement.source,
                "site_gps_capable": gps_requirement.site_gps_capable,
                "configured_value": gps_requirement.configured_value,
            },
            "complete": not missing_documents,
        }
        worker_notice_states.append(state)
        if state["complete"]:
            completed_worker_count += 1

    incomplete_workers = [state for state in worker_notice_states if not bool(state["complete"])]

    return {
        "company_documents": company_documents,
        "company_document_states": company_document_states,
        "company_documents_complete": all(company_documents.values()),
        "worker_notice_completion": {
            "completed": completed_worker_count,
            "total": active_worker_total,
        },
        "gps_site_presence_requirement_counts": gps_requirement_counts,
        "worker_notice_states": worker_notice_states,
        "incomplete_workers": incomplete_workers,
    }
