from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Site, Worker


PRIVACY_NOTICE_DOCUMENT = "privacy_notice"
TIME_TRACKING_NOTICE_DOCUMENT = "time_tracking_notice"
GPS_SITE_PRESENCE_NOTICE_DOCUMENT = "gps_site_presence_notice"


def gps_site_presence_enabled_for_site(site: Site | None) -> bool:
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


def required_worker_document_types(
    worker: Worker,
    *,
    gps_site_presence_enabled: bool,
) -> list[str]:
    required = [PRIVACY_NOTICE_DOCUMENT]
    if bool(getattr(worker, "is_active", False)) and bool(getattr(worker, "time_tracking_enabled", False)):
        required.append(TIME_TRACKING_NOTICE_DOCUMENT)
        if gps_site_presence_enabled:
            required.append(GPS_SITE_PRESENCE_NOTICE_DOCUMENT)
    return required


async def resolve_worker_gps_site_presence_requirements(
    db: AsyncSession,
    *,
    workers: Sequence[Worker],
) -> dict[int, bool]:
    site_ids = {worker.site_id for worker in workers if getattr(worker, "site_id", None) is not None}
    if not site_ids:
        return {int(worker.id): False for worker in workers}

    sites = (
        await db.execute(
            select(Site).where(Site.id.in_(site_ids))
        )
    ).scalars().all()
    sites_by_id = {int(site.id): site for site in sites}
    return {
        int(worker.id): gps_site_presence_enabled_for_site(sites_by_id.get(worker.site_id))
        for worker in workers
    }

