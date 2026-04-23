from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Company, Site, Worker


PRIVACY_NOTICE_DOCUMENT = "privacy_notice"
TIME_TRACKING_NOTICE_DOCUMENT = "time_tracking_notice"
GPS_SITE_PRESENCE_NOTICE_DOCUMENT = "gps_site_presence_notice"

GPS_REQUIREMENT_REQUIRED = "required"
GPS_REQUIREMENT_NOT_REQUIRED = "not_required"
GPS_REQUIREMENT_NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class WorkerGpsSitePresenceRequirement:
    state: str
    source: str
    site_gps_capable: bool
    configured_value: bool | None

    @property
    def is_required(self) -> bool:
        return self.state == GPS_REQUIREMENT_REQUIRED


def gps_site_presence_capable_for_site(site: Site | None) -> bool:
    if site is None or not bool(getattr(site, "is_active", False)):
        return False
    return all(
        value is not None
        for value in (
            getattr(site, "lat", None),
            getattr(site, "lon", None),
            getattr(site, "radius_m", None),
        )
    )


def _time_tracking_notice_required(worker: Worker) -> bool:
    return bool(getattr(worker, "is_active", False)) and bool(getattr(worker, "time_tracking_enabled", False))


def _gps_requirement_from_setting(
    *,
    configured_value: bool,
    source: str,
    site_gps_capable: bool,
) -> WorkerGpsSitePresenceRequirement:
    if not configured_value:
        return WorkerGpsSitePresenceRequirement(
            state=GPS_REQUIREMENT_NOT_REQUIRED,
            source=source,
            site_gps_capable=site_gps_capable,
            configured_value=False,
        )
    if site_gps_capable:
        return WorkerGpsSitePresenceRequirement(
            state=GPS_REQUIREMENT_REQUIRED,
            source=source,
            site_gps_capable=True,
            configured_value=True,
        )
    return WorkerGpsSitePresenceRequirement(
        state=GPS_REQUIREMENT_NOT_APPLICABLE,
        source=f"{source}_site_not_capable",
        site_gps_capable=False,
        configured_value=True,
    )


def resolve_worker_gps_site_presence_requirement(
    worker: Worker,
    *,
    company: Company | None,
    site: Site | None,
) -> WorkerGpsSitePresenceRequirement:
    if not _time_tracking_notice_required(worker):
        return WorkerGpsSitePresenceRequirement(
            state=GPS_REQUIREMENT_NOT_APPLICABLE,
            source="worker_not_tracked",
            site_gps_capable=gps_site_presence_capable_for_site(site),
            configured_value=None,
        )

    site_gps_capable = gps_site_presence_capable_for_site(site)
    worker_override = getattr(worker, "gps_site_presence_required_override", None)
    site_setting = getattr(site, "gps_site_presence_required", None) if site is not None else None
    company_setting = getattr(company, "gps_site_presence_required", None) if company is not None else None

    if worker_override is not None:
        return _gps_requirement_from_setting(
            configured_value=bool(worker_override),
            source="worker_override",
            site_gps_capable=site_gps_capable,
        )
    if site_setting is not None:
        return _gps_requirement_from_setting(
            configured_value=bool(site_setting),
            source="site_setting",
            site_gps_capable=site_gps_capable,
        )
    if company_setting is not None:
        return _gps_requirement_from_setting(
            configured_value=bool(company_setting),
            source="company_setting",
            site_gps_capable=site_gps_capable,
        )
    if site_gps_capable:
        return WorkerGpsSitePresenceRequirement(
            state=GPS_REQUIREMENT_REQUIRED,
            source="fallback_site_gps_capable",
            site_gps_capable=True,
            configured_value=None,
        )
    return WorkerGpsSitePresenceRequirement(
        state=GPS_REQUIREMENT_NOT_APPLICABLE,
        source="fallback_not_gps_capable",
        site_gps_capable=False,
        configured_value=None,
    )


def required_worker_document_types(
    worker: Worker,
    *,
    gps_requirement: WorkerGpsSitePresenceRequirement | None = None,
    gps_site_presence_enabled: bool | None = None,
) -> list[str]:
    required = [PRIVACY_NOTICE_DOCUMENT]
    if _time_tracking_notice_required(worker):
        required.append(TIME_TRACKING_NOTICE_DOCUMENT)

    effective_gps_requirement = gps_requirement
    if effective_gps_requirement is None:
        effective_gps_requirement = WorkerGpsSitePresenceRequirement(
            state=GPS_REQUIREMENT_REQUIRED if bool(gps_site_presence_enabled) else GPS_REQUIREMENT_NOT_REQUIRED,
            source="legacy_boolean",
            site_gps_capable=bool(gps_site_presence_enabled),
            configured_value=bool(gps_site_presence_enabled),
        )

    if effective_gps_requirement.is_required:
        required.append(GPS_SITE_PRESENCE_NOTICE_DOCUMENT)
    return required


async def resolve_worker_gps_site_presence_requirements(
    db: AsyncSession,
    *,
    workers: Sequence[Worker],
) -> dict[int, WorkerGpsSitePresenceRequirement]:
    site_ids = {worker.site_id for worker in workers if getattr(worker, "site_id", None) is not None}
    company_ids = {worker.company_id for worker in workers if getattr(worker, "company_id", None) is not None}

    sites_by_id: dict[int, Site] = {}
    if site_ids:
        sites = (
            await db.execute(
                select(Site).where(Site.id.in_(site_ids))
            )
        ).scalars().all()
        sites_by_id = {int(site.id): site for site in sites}

    companies_by_id: dict[int, Company] = {}
    if company_ids:
        companies = (
            await db.execute(
                select(Company).where(Company.id.in_(company_ids))
            )
        ).scalars().all()
        companies_by_id = {int(company.id): company for company in companies}

    return {
        int(worker.id): resolve_worker_gps_site_presence_requirement(
            worker,
            company=companies_by_id.get(int(worker.company_id)),
            site=sites_by_id.get(int(worker.site_id)) if getattr(worker, "site_id", None) is not None else None,
        )
        for worker in workers
    }
