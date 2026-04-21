from __future__ import annotations

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import LegalAcceptanceLog, Worker


COMPANY_DOCUMENT_VERSIONS = {
    "saas_terms": "2026-04-de-v1",
    "avv_dpa": "2026-04-de-v1",
    "privacy_toms_retention_subprocessors": "2026-04-de-v1",
}

WORKER_DOCUMENT_VERSIONS = {
    "privacy_notice": "2026-04-de-v1",
    "time_tracking_notice": "2026-04-de-v1",
    "gps_site_presence_notice": "2026-04-de-v1",
}


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
    row = LegalAcceptanceLog(
        actor_type=actor_type,
        actor_id=actor_id,
        company_id=company_id,
        document_type=document_type,
        document_version=document_version,
        action_type=action_type,
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
        action_type = "accepted" if document_type in {"saas_terms", "avv_dpa"} else "acknowledged"
        await record_legal_acceptance(
            db,
            actor_type="worker",
            actor_id=actor_worker_id,
            company_id=company_id,
            document_type=document_type,
            document_version=document_version,
            action_type=action_type,
        )


async def record_worker_onboarding_acknowledgements(
    db: AsyncSession,
    *,
    worker_id: int,
    company_id: int,
    gps_notice_enabled: bool = True,
) -> None:
    for document_type, document_version in WORKER_DOCUMENT_VERSIONS.items():
        if document_type == "gps_site_presence_notice" and not gps_notice_enabled:
            continue
        await record_legal_acceptance(
            db,
            actor_type="worker",
            actor_id=worker_id,
            company_id=company_id,
            document_type=document_type,
            document_version=document_version,
            action_type="acknowledged",
        )


async def get_legal_acceptance_overview(
    db: AsyncSession,
    *,
    company_id: int,
) -> dict[str, object]:
    active_worker_total = int(
        await db.scalar(
            select(func.count(Worker.id)).where(
                Worker.company_id == company_id,
                Worker.is_active.is_(True),
            )
        )
        or 0
    )

    company_documents = {}
    for document_type in COMPANY_DOCUMENT_VERSIONS:
        latest = await db.scalar(
            select(LegalAcceptanceLog.id)
            .where(
                LegalAcceptanceLog.company_id == company_id,
                LegalAcceptanceLog.document_type == document_type,
            )
            .order_by(LegalAcceptanceLog.created_at.desc(), LegalAcceptanceLog.id.desc())
            .limit(1)
        )
        company_documents[document_type] = bool(latest)

    worker_completion_subquery = (
        select(
            LegalAcceptanceLog.actor_id.label("worker_id"),
            func.count(distinct(LegalAcceptanceLog.document_type)).label("document_count"),
        )
        .where(
            LegalAcceptanceLog.company_id == company_id,
            LegalAcceptanceLog.actor_type == "worker",
            LegalAcceptanceLog.document_type.in_(tuple(WORKER_DOCUMENT_VERSIONS.keys())),
        )
        .group_by(LegalAcceptanceLog.actor_id)
        .subquery()
    )
    completed_worker_count = int(
        await db.scalar(
            select(func.count())
            .select_from(worker_completion_subquery)
            .where(worker_completion_subquery.c.document_count >= len(WORKER_DOCUMENT_VERSIONS))
        )
        or 0
    )

    return {
        "company_documents": company_documents,
        "company_documents_complete": all(company_documents.values()),
        "worker_notice_completion": {
            "completed": completed_worker_count,
            "total": active_worker_total,
        },
    }
