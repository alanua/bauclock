from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request as FastAPIRequest
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.redis_client import redis_client
from api.services.dashboard_access import (
    DASHBOARD_RESPONSE_HEADERS,
    DashboardContext,
    DashboardAccessError,
    get_company_present_worker_ids,
    get_dashboard_context,
    get_dashboard_worker,
    get_dashboard_role,
    get_miniapp_bot_role,
    get_miniapp_dashboard_context,
    get_miniapp_private_worker,
)
from db.calendar_service import list_worker_calendar_events
from db.database import get_db
from db.models import CalendarEvent, Company, EventType, Payment, Request, RequestStatus, Site, SitePartnerCompany, TimeEvent, Worker
from db.request_service import (
    RequestAccessError,
    create_request,
    list_company_requests,
    list_worker_requests,
    reject_request,
    resolve_request,
)
from db.security import decrypt_string


router = APIRouter()
DASHBOARD_SHELL_VERSION = "20260417-sites-alpha"


class MiniAppBootstrapRequest(BaseModel):
    init_data: str


class WorkerProblemCreateRequest(BaseModel):
    text: str
    related_date: date | None = None


def _dashboard_access_denied() -> HTTPException:
    return HTTPException(status_code=404, detail="Not found")


def _serialize_datetime(value) -> str | None:
    return value.isoformat() if value else None


async def _get_company_worker_names(
    db: AsyncSession,
    *,
    company_id: int,
    worker_ids: set[int],
) -> dict[int, str]:
    if not worker_ids:
        return {}

    stmt = select(Worker).where(
        Worker.company_id == company_id,
        Worker.id.in_(worker_ids),
    )
    workers = (await db.execute(stmt)).scalars().all()
    return {
        company_worker.id: decrypt_string(company_worker.full_name_enc)
        for company_worker in workers
    }


async def _serialize_company_requests(
    db: AsyncSession,
    *,
    company_id: int,
    requests: list[Request],
) -> list[dict[str, str | int | None]]:
    worker_names = await _get_company_worker_names(
        db,
        company_id=company_id,
        worker_ids={
            request.target_worker_id
            for request in requests
            if request.target_worker_id is not None
        },
    )
    return [
        {
            "id": request.id,
            "created_at": _serialize_datetime(request.created_at),
            "related_date": request.related_date.isoformat() if request.related_date else None,
            "target_worker_name": worker_names.get(request.target_worker_id, "-"),
            "text": request.text,
            "status": request.status,
        }
        for request in requests
    ]


def _event_type_value(event_type) -> str:
    if hasattr(event_type, "value"):
        return str(event_type.value)
    return str(event_type or "")


def _safe_minutes_between(start: datetime | None, end: datetime | None) -> int:
    if not start or not end:
        return 0
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return max(int((end - start).total_seconds() // 60), 0)


def _calculate_day_minutes(events: list[TimeEvent], now: datetime) -> dict[str, int]:
    work_minutes = 0
    break_minutes = 0
    active_start: datetime | None = None
    pause_start: datetime | None = None

    for event in events:
        event_type = _event_type_value(event.event_type)
        timestamp = event.timestamp
        if event_type == EventType.CHECKIN.value:
            active_start = timestamp
            pause_start = None
        elif event_type == EventType.PAUSE_START.value:
            work_minutes += _safe_minutes_between(active_start, timestamp)
            active_start = None
            pause_start = timestamp
        elif event_type == EventType.PAUSE_END.value:
            break_minutes += _safe_minutes_between(pause_start, timestamp)
            pause_start = None
            active_start = timestamp
        elif event_type == EventType.CHECKOUT.value:
            work_minutes += _safe_minutes_between(active_start, timestamp)
            break_minutes += _safe_minutes_between(pause_start, timestamp)
            active_start = None
            pause_start = None

    work_minutes += _safe_minutes_between(active_start, now)
    break_minutes += _safe_minutes_between(pause_start, now)
    return {
        "work_minutes": work_minutes,
        "break_minutes": break_minutes,
    }


def _worker_status(events: list[TimeEvent]) -> dict[str, str | None]:
    if not events:
        return {
            "key": "not_started",
            "label": "Noch nicht gestartet",
            "detail": "Keine Buchung fuer heute",
            "tone": "neutral",
            "last_event_type": None,
            "last_event_at": None,
        }

    last_event = events[-1]
    last_event_type = _event_type_value(last_event.event_type)
    status_map = {
        EventType.CHECKIN.value: ("working", "Am Arbeiten", "Seit der letzten Ankunft", "success"),
        EventType.PAUSE_START.value: ("paused", "In Pause", "Pause laeuft", "warning"),
        EventType.PAUSE_END.value: ("working", "Am Arbeiten", "Seit dem Pausenende", "success"),
        EventType.CHECKOUT.value: ("done", "Feierabend", "Heute abgeschlossen", "neutral"),
    }
    key, label, detail, tone = status_map.get(
        last_event_type,
        ("unknown", "Status offen", "Letzte Buchung wird geprueft", "neutral"),
    )
    return {
        "key": key,
        "label": label,
        "detail": detail,
        "tone": tone,
        "last_event_type": last_event_type,
        "last_event_at": _serialize_datetime(last_event.timestamp),
    }


async def _get_worker_today_events(
    db: AsyncSession,
    *,
    worker_id: int,
    today: date,
) -> list[TimeEvent]:
    result = await db.execute(
        select(TimeEvent)
        .where(
            TimeEvent.worker_id == worker_id,
            func.date(TimeEvent.timestamp) == today,
        )
        .order_by(TimeEvent.timestamp.asc(), TimeEvent.id.asc())
    )
    return list(result.scalars().all())


def _serialize_worker_calendar_event(event: CalendarEvent) -> dict[str, str | None]:
    labels = {
        "vacation": "Urlaub",
        "sick_leave": "Krankmeldung",
        "public_holiday": "Feiertag",
        "non_working_day": "Freier Tag",
    }
    return {
        "type": event.event_type,
        "label": labels.get(event.event_type, event.event_type),
        "date_from": event.date_from.isoformat(),
        "date_to": event.date_to.isoformat(),
        "comment": event.comment,
    }


def _serialize_worker_request(request: Request) -> dict[str, str | int | None]:
    return {
        "id": request.id,
        "created_at": _serialize_datetime(request.created_at),
        "related_date": request.related_date.isoformat() if request.related_date else None,
        "text": request.text,
        "status": request.status,
    }


async def _get_latest_worker_payment(
    db: AsyncSession,
    *,
    worker_id: int,
) -> Payment | None:
    result = await db.execute(
        select(Payment)
        .where(Payment.worker_id == worker_id)
        .order_by(Payment.period_end.desc(), Payment.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _get_authenticated_worker_home_worker(
    db: AsyncSession,
    *,
    token: str | None,
    telegram_init_data: str | None,
) -> Worker:
    if (token or "").strip():
        return await get_dashboard_worker(token, db, redis_client)
    return await get_miniapp_private_worker(telegram_init_data, db)


async def _serialize_worker_home(
    db: AsyncSession,
    *,
    worker: Worker,
) -> dict[str, object]:
    today = date.today()
    now = datetime.now(timezone.utc)
    company = await db.get(Company, worker.company_id)
    site = await db.get(Site, worker.site_id) if worker.site_id else None
    today_events = await _get_worker_today_events(db, worker_id=worker.id, today=today)
    day_minutes = _calculate_day_minutes(today_events, now)
    calendar_events = sorted(
        [
            event
            for event in await list_worker_calendar_events(db, worker=worker)
            if event.date_to >= today
        ],
        key=lambda event: (event.date_from, event.id),
    )[:3]
    worker_requests_all = list(await list_worker_requests(db, worker=worker))
    worker_requests = worker_requests_all[:3]
    open_request_count = sum(1 for request in worker_requests_all if request.status == "open")
    latest_payment = await _get_latest_worker_payment(db, worker_id=worker.id)
    hourly_rate = float(worker.hourly_rate or 0)
    today_amount = round((day_minutes["work_minutes"] / 60) * hourly_rate, 2)

    return {
        "user": {
            "id": worker.id,
            "name": decrypt_string(worker.full_name_enc),
            "role": "WORKER",
        },
        "company": {
            "name": company.name if company else "BauClock",
        },
        "site": {
            "name": site.name if site else None,
            "address": site.address if site else None,
        },
        "status": _worker_status(today_events),
        "hours": {
            "today_minutes": day_minutes["work_minutes"],
            "break_minutes": day_minutes["break_minutes"],
            "contract_hours_week": int(worker.contract_hours_week or 0),
        },
        "money": {
            "billing_type": _event_type_value(worker.billing_type),
            "hourly_rate": hourly_rate,
            "today_estimate": today_amount,
            "latest_payment": {
                "amount_paid": float(latest_payment.amount_paid),
                "hours_paid": float(latest_payment.hours_paid),
                "status": _event_type_value(latest_payment.status),
                "period_start": _serialize_datetime(latest_payment.period_start),
                "period_end": _serialize_datetime(latest_payment.period_end),
            }
            if latest_payment
            else None,
        },
        "calendar": {
            "items": [_serialize_worker_calendar_event(event) for event in calendar_events],
        },
        "requests": {
            "open_count": open_request_count,
            "items": [_serialize_worker_request(request) for request in worker_requests],
        },
    }


def _dashboard_context_user(context: DashboardContext) -> dict[str, str]:
    if context.worker:
        return {
            "name": decrypt_string(context.worker.full_name_enc),
            "role": get_dashboard_role(context.worker),
        }
    return {
        "name": context.display_name or "Platform Superadmin",
        "role": context.role or "PLATFORM_SUPERADMIN",
    }


def _management_access_role(context: DashboardContext) -> str:
    if context.is_platform_superadmin:
        return "platform_superadmin"
    if not context.worker:
        return "company_owner"

    access_role = str(getattr(context.worker, "access_role", "") or "").strip()
    if access_role and access_role != "worker":
        return access_role
    if getattr(context.worker, "created_by", None) is None:
        return "company_owner"
    return "objektmanager"


def _management_role_groups(access_role: str) -> list[str]:
    if access_role in {"company_owner", "platform_superadmin"}:
        return ["operations", "finance", "partners", "entry_points", "people", "requests"]
    if access_role == "accountant":
        return ["finance", "entry_points", "requests"]
    if access_role == "objektmanager":
        return ["operations", "partners", "entry_points", "people", "requests"]
    return ["operations", "entry_points", "people", "requests"]


def _dashboard_manager(context: DashboardContext):
    if context.worker:
        return context.worker
    return SimpleNamespace(
        id=None,
        company_id=context.company_id,
        can_view_dashboard=True,
        is_active=True,
        created_by=None,
    )


async def _get_authenticated_dashboard_context(
    db: AsyncSession,
    *,
    token: str | None,
    telegram_init_data: str | None,
) -> DashboardContext:
    if (token or "").strip():
        return await get_dashboard_context(token, db, redis_client)
    return await get_miniapp_dashboard_context(telegram_init_data, db)


async def _get_company_today_events(
    db: AsyncSession,
    *,
    company_id: int,
    today: date,
) -> list[TimeEvent]:
    result = await db.execute(
        select(TimeEvent)
        .join(Worker, Worker.id == TimeEvent.worker_id)
        .where(
            Worker.company_id == company_id,
            Worker.is_active.is_(True),
            Worker.time_tracking_enabled.is_(True),
            func.date(TimeEvent.timestamp) == today,
        )
        .order_by(TimeEvent.worker_id.asc(), TimeEvent.timestamp.asc(), TimeEvent.id.asc())
    )
    return list(result.scalars().all())


def _management_today_status(
    workers: list[Worker],
    events: list[TimeEvent],
) -> dict[str, int]:
    events_by_worker: dict[int, list[TimeEvent]] = {}
    for event in events:
        events_by_worker.setdefault(event.worker_id, []).append(event)

    working = 0
    on_break = 0
    unclosed = 0
    not_checked_in = 0
    for worker in workers:
        worker_events = events_by_worker.get(worker.id, [])
        if not worker_events:
            not_checked_in += 1
            continue

        last_event_type = _event_type_value(worker_events[-1].event_type)
        if last_event_type in {EventType.CHECKIN.value, EventType.PAUSE_END.value}:
            working += 1
        if last_event_type == EventType.PAUSE_START.value:
            on_break += 1
        if last_event_type != EventType.CHECKOUT.value:
            unclosed += 1

    return {
        "working": working,
        "on_break": on_break,
        "not_checked_in": not_checked_in,
        "unclosed_days": unclosed,
    }


def _status_badge_class(status_key: str) -> str:
    return {
        "working": "working",
        "paused": "on_break",
        "done": "finished",
        "not_started": "not_started",
    }.get(status_key, "not_started")


def _site_role_from_description(description: str | None, default: str) -> str:
    value = (description or "").casefold()
    if "subcontractor" in value or "subunternehmer" in value:
        return "subcontractor"
    if "general_contractor" in value or "generalunternehmer" in value:
        return "general_contractor"
    return default


async def _serialize_management_sites(
    db: AsyncSession,
    *,
    context: DashboardContext,
) -> dict[str, object]:
    access_role = _management_access_role(context)
    focus_site_id = context.worker.site_id if access_role == "objektmanager" and context.worker else None
    rows: list[tuple[Site, str, bool, str | None]] = []

    own_stmt = select(Site).where(
        Site.company_id == context.company_id,
        Site.is_active.is_(True),
    )
    if focus_site_id:
        own_stmt = own_stmt.where(Site.id == focus_site_id)
    own_sites = (await db.execute(own_stmt.order_by(Site.name))).scalars().all()
    rows.extend(
        (
            site,
            _site_role_from_description(site.description, "general_contractor"),
            False,
            None,
        )
        for site in own_sites
    )

    joined_stmt = (
        select(Site, Company)
        .join(SitePartnerCompany, SitePartnerCompany.site_id == Site.id)
        .join(Company, Company.id == Site.company_id)
        .where(
            SitePartnerCompany.company_id == context.company_id,
            SitePartnerCompany.is_active.is_(True),
            Site.is_active.is_(True),
        )
    )
    if focus_site_id:
        joined_stmt = joined_stmt.where(Site.id == focus_site_id)
    joined_rows = (await db.execute(joined_stmt.order_by(Site.name))).all()
    rows.extend((site, "subcontractor", True, owner_company.name) for site, owner_company in joined_rows)

    items: list[dict[str, object]] = []
    seen: set[tuple[int, str]] = set()
    for site, role, is_joined_site, owner_company_name in rows:
        key = (site.id, role)
        if key in seen:
            continue
        seen.add(key)
        assigned_worker_count = await db.scalar(
            select(func.count(Worker.id)).where(
                Worker.company_id == context.company_id,
                Worker.site_id == site.id,
                Worker.is_active.is_(True),
                Worker.time_tracking_enabled.is_(True),
            )
        )
        partner_company_count = 0
        if site.company_id == context.company_id:
            partner_company_count = int(
                await db.scalar(
                    select(func.count(SitePartnerCompany.id)).where(
                        SitePartnerCompany.site_id == site.id,
                        SitePartnerCompany.is_active.is_(True),
                    )
                )
                or 0
            )
        items.append(
            {
                "id": site.id,
                "name": site.name,
                "address": site.address,
                "role": role,
                "is_joined_site": is_joined_site,
                "owner_company_name": owner_company_name,
                "qr_available": bool(site.qr_token),
                "public_url": f"/s/{site.qr_token}" if site.qr_token else None,
                "assigned_worker_count": int(assigned_worker_count or 0),
                "partner_company_count": partner_company_count,
            }
        )

    return {
        "total": len(items),
        "owned": sum(1 for item in items if not item["is_joined_site"]),
        "joined": sum(1 for item in items if item["is_joined_site"]),
        "items": items,
    }


def _serialize_management_workers(
    workers: list[Worker],
    *,
    present_ids: set[int],
    events_by_worker: dict[int, list[TimeEvent]],
    now: datetime,
) -> list[dict[str, object]]:
    serialized_workers = []
    for company_worker in workers:
        worker_events = events_by_worker.get(company_worker.id, [])
        status = _worker_status(worker_events)
        minutes = _calculate_day_minutes(worker_events, now)
        serialized_workers.append(
            {
                "id": company_worker.id,
                "name": decrypt_string(company_worker.full_name_enc),
                "type": company_worker.worker_type.value,
                "rate": float(company_worker.hourly_rate or 0),
                "contract_hours_week": int(company_worker.contract_hours_week or 0),
                "present_today": company_worker.id in present_ids,
                "today_status": _status_badge_class(str(status["key"])),
                "today_status_label": status["label"],
                "today_work_minutes": minutes["work_minutes"],
                "today_break_minutes": minutes["break_minutes"],
            }
        )
    return serialized_workers


async def _serialize_partner_groups(
    db: AsyncSession,
    *,
    context: DashboardContext,
    today: date,
    now: datetime,
) -> tuple[list[dict[str, object]], dict[str, int]]:
    rows = (
        await db.execute(
            select(SitePartnerCompany, Site, Company)
            .join(Site, Site.id == SitePartnerCompany.site_id)
            .join(Company, Company.id == SitePartnerCompany.company_id)
            .where(
                Site.company_id == context.company_id,
                Site.is_active.is_(True),
                SitePartnerCompany.role == "subcontractor",
                SitePartnerCompany.is_active.is_(True),
            )
            .order_by(Company.name, Site.name)
        )
    ).all()

    groups: list[dict[str, object]] = []
    totals = {
        "companies": 0,
        "people": 0,
        "present": 0,
        "work_minutes": 0,
    }
    for _partnership, site, company in rows:
        partner_workers = (
            await db.execute(
                select(Worker)
                .where(
                    Worker.company_id == company.id,
                    Worker.site_id == site.id,
                    Worker.is_active.is_(True),
                    Worker.time_tracking_enabled.is_(True),
                )
                .order_by(Worker.id)
            )
        ).scalars().all()
        worker_ids = [worker.id for worker in partner_workers]
        events_by_worker: dict[int, list[TimeEvent]] = {}
        if worker_ids:
            events = (
                await db.execute(
                    select(TimeEvent)
                    .where(
                        TimeEvent.worker_id.in_(worker_ids),
                        TimeEvent.site_id == site.id,
                        func.date(TimeEvent.timestamp) == today,
                    )
                    .order_by(TimeEvent.timestamp.asc())
                )
            ).scalars().all()
            for event in events:
                events_by_worker.setdefault(event.worker_id, []).append(event)

        people = []
        for worker in partner_workers:
            worker_events = events_by_worker.get(worker.id, [])
            status = _worker_status(worker_events)
            minutes = _calculate_day_minutes(worker_events, now)
            present_today = bool(worker_events)
            totals["people"] += 1
            totals["present"] += 1 if present_today else 0
            totals["work_minutes"] += int(minutes["work_minutes"])
            people.append(
                {
                    "id": worker.id,
                    "name": decrypt_string(worker.full_name_enc),
                    "present_today": present_today,
                    "today_status": _status_badge_class(str(status["key"])),
                    "today_status_label": status["label"],
                    "today_work_minutes": minutes["work_minutes"],
                    "today_break_minutes": minutes["break_minutes"],
                }
            )

        totals["companies"] += 1
        groups.append(
            {
                "company_id": company.id,
                "company_name": company.name,
                "site_id": site.id,
                "site_name": site.name,
                "people": people,
                "present_today": sum(1 for person in people if person["present_today"]),
                "today_work_minutes": sum(int(person["today_work_minutes"]) for person in people),
            }
        )

    return groups, totals


async def _serialize_management_home(
    db: AsyncSession,
    *,
    context: DashboardContext,
    workers: list[Worker],
    today: date,
) -> dict[str, object]:
    access_role = _management_access_role(context)
    today_events = await _get_company_today_events(db, company_id=context.company_id, today=today)
    today_status = _management_today_status(workers, today_events)
    now = datetime.now(timezone.utc)
    partner_groups, partner_totals = await _serialize_partner_groups(
        db,
        context=context,
        today=today,
        now=now,
    )
    sites = await _serialize_management_sites(db, context=context)

    open_request_count = await db.scalar(
        select(func.count(Request.id)).where(
            Request.company_id == context.company_id,
            Request.status == RequestStatus.OPEN.value,
        )
    )
    upcoming_calendar_count = await db.scalar(
        select(func.count(CalendarEvent.id)).where(
            CalendarEvent.company_id == context.company_id,
            CalendarEvent.is_active.is_(True),
            CalendarEvent.date_to >= today,
        )
    )

    month_start = datetime(today.year, today.month, 1, tzinfo=timezone.utc)
    payments = (
        await db.execute(
            select(Payment)
            .join(Worker, Worker.id == Payment.worker_id)
            .where(
                Worker.company_id == context.company_id,
                Payment.period_start >= month_start,
            )
        )
    ).scalars().all()
    pending_payments = [
        payment
        for payment in payments
        if _event_type_value(payment.status) == "PENDING"
    ]
    confirmed_payments = [
        payment
        for payment in payments
        if _event_type_value(payment.status) == "CONFIRMED"
    ]
    pending_overtime_hours = sum(
        float(payment.hours_paid or 0)
        for payment in pending_payments
        if _event_type_value(payment.payment_type) == "OVERTIME"
    )

    subcontractor_workers = [
        worker
        for worker in workers
        if _event_type_value(worker.worker_type) == "SUBUNTERNEHMER"
    ]
    trade_workers = [
        worker
        for worker in workers
        if _event_type_value(worker.worker_type) == "GEWERBE"
    ]
    scope_label = "Alle sichtbaren Unternehmensdaten"
    if access_role == "objektmanager" and context.worker and context.worker.site_id:
        site = await db.get(Site, context.worker.site_id)
        if site:
            scope_label = f"Objektfokus: {site.name}"
    elif access_role == "accountant":
        scope_label = "Abrechnung und Meldungen"

    return {
        "access_role": access_role,
        "role_groups": _management_role_groups(access_role),
        "scope_label": scope_label,
        "operations": today_status,
        "requests": {
            "open": int(open_request_count or 0),
        },
        "finance": {
            "pending_amount": round(sum(float(payment.amount_paid or 0) for payment in pending_payments), 2),
            "confirmed_amount": round(sum(float(payment.amount_paid or 0) for payment in confirmed_payments), 2),
            "pending_overtime_hours": round(pending_overtime_hours, 2),
            "payment_entries": len(payments),
        },
        "partners": {
            "subcontractor_workers": len(subcontractor_workers),
            "trade_workers": len(trade_workers),
            "total_partner_workers": len(subcontractor_workers) + len(trade_workers),
            "subcontractor_companies": partner_totals["companies"],
            "partner_people": partner_totals["people"],
            "partner_present": partner_totals["present"],
            "partner_work_minutes": partner_totals["work_minutes"],
            "groups": partner_groups,
        },
        "sites": sites,
        "quick_entries": {
            "people": len(workers),
            "sites": int(sites["total"]),
            "calendar": int(upcoming_calendar_count or 0),
            "exports": len(payments),
        },
    }


@router.get("/dashboard")
async def serve_dashboard(
    request: FastAPIRequest,
    token: str | None = Query(default=None),
    version: str | None = Query(default=None, alias="v"),
):
    if version != DASHBOARD_SHELL_VERSION:
        query_params = dict(request.query_params)
        query_params["v"] = DASHBOARD_SHELL_VERSION
        return RedirectResponse(
            f"{request.url.path}?{urlencode(query_params)}",
            status_code=307,
            headers=DASHBOARD_RESPONSE_HEADERS,
        )
    return FileResponse("api/static/dashboard.html", headers=DASHBOARD_RESPONSE_HEADERS)


@router.post("/api/dashboard/miniapp/bootstrap")
async def dashboard_miniapp_bootstrap(
    payload: MiniAppBootstrapRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        context = await get_miniapp_dashboard_context(payload.init_data, db)
    except DashboardAccessError as exc:
        try:
            if get_miniapp_bot_role(payload.init_data) == "shared_client":
                return {
                    "auth_mode": "miniapp",
                    "landing": "neutral_tetris",
                }
        except DashboardAccessError:
            pass
        raise _dashboard_access_denied() from exc

    return {
        "auth_mode": "miniapp",
        "user": _dashboard_context_user(context),
    }


@router.get("/api/dashboard/data")
async def dashboard_data(
    token: str | None = Query(default=None),
    telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
    db: AsyncSession = Depends(get_db),
):
    try:
        context = await _get_authenticated_dashboard_context(
            db,
            token=token,
            telegram_init_data=telegram_init_data,
        )
    except DashboardAccessError as exc:
        raise _dashboard_access_denied() from exc

    today = date.today()

    stmt = select(Worker).where(
        Worker.company_id == context.company_id,
        Worker.is_active.is_(True),
        Worker.time_tracking_enabled.is_(True),
    )
    workers = (await db.execute(stmt)).scalars().all()
    present_ids = await get_company_present_worker_ids(db, context.company_id, today)
    now = datetime.now(timezone.utc)
    today_events = await _get_company_today_events(db, company_id=context.company_id, today=today)
    events_by_worker: dict[int, list[TimeEvent]] = {}
    for event in today_events:
        events_by_worker.setdefault(event.worker_id, []).append(event)

    user = _dashboard_context_user(context)
    user["access_role"] = _management_access_role(context)

    return {
        "user": user,
        "today": {
            "present": len(present_ids),
            "total_workers": len(workers),
        },
        "management_home": await _serialize_management_home(
            db,
            context=context,
            workers=list(workers),
            today=today,
        ),
        "workers": _serialize_management_workers(
            list(workers),
            present_ids=present_ids,
            events_by_worker=events_by_worker,
            now=now,
        ),
    }


@router.get("/api/dashboard/worker-home")
async def dashboard_worker_home(
    token: str | None = Query(default=None),
    telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
    db: AsyncSession = Depends(get_db),
):
    try:
        worker = await _get_authenticated_worker_home_worker(
            db,
            token=token,
            telegram_init_data=telegram_init_data,
        )
    except DashboardAccessError as exc:
        raise _dashboard_access_denied() from exc

    return await _serialize_worker_home(db, worker=worker)


@router.post("/api/dashboard/worker-home/requests")
async def dashboard_worker_request_create(
    payload: WorkerProblemCreateRequest,
    token: str | None = Query(default=None),
    telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
    db: AsyncSession = Depends(get_db),
):
    try:
        worker = await _get_authenticated_worker_home_worker(
            db,
            token=token,
            telegram_init_data=telegram_init_data,
        )
    except DashboardAccessError as exc:
        raise _dashboard_access_denied() from exc

    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="request_text_required")
    if len(text) > 280:
        raise HTTPException(status_code=400, detail="request_text_too_long")

    try:
        request = await create_request(
            db,
            creator_worker=worker,
            target_worker_id=worker.id,
            related_date=payload.related_date,
            text=text,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RequestAccessError as exc:
        raise _dashboard_access_denied() from exc

    return {"request": _serialize_worker_request(request)}


@router.get("/api/dashboard/requests")
async def dashboard_requests(
    token: str | None = Query(default=None),
    telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
    db: AsyncSession = Depends(get_db),
):
    try:
        context = await _get_authenticated_dashboard_context(
            db,
            token=token,
            telegram_init_data=telegram_init_data,
        )
        requests = await list_company_requests(db, manager_worker=_dashboard_manager(context))
    except (DashboardAccessError, RequestAccessError) as exc:
        raise _dashboard_access_denied() from exc

    return {
        "requests": await _serialize_company_requests(
            db,
            company_id=context.company_id,
            requests=list(requests),
        )
    }


@router.api_route("/api/dashboard/requests/{request_id}/resolve", methods=["POST", "PATCH"])
async def dashboard_request_resolve(
    request_id: int,
    token: str | None = Query(default=None),
    telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
    db: AsyncSession = Depends(get_db),
):
    try:
        context = await _get_authenticated_dashboard_context(
            db,
            token=token,
            telegram_init_data=telegram_init_data,
        )
        request = await resolve_request(
            db,
            request_id=request_id,
            manager_worker=_dashboard_manager(context),
        )
    except (DashboardAccessError, RequestAccessError) as exc:
        raise _dashboard_access_denied() from exc

    return {
        "id": request.id,
        "status": request.status,
        "resolved_at": _serialize_datetime(request.resolved_at),
    }


@router.api_route("/api/dashboard/requests/{request_id}/reject", methods=["POST", "PATCH"])
async def dashboard_request_reject(
    request_id: int,
    token: str | None = Query(default=None),
    telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
    db: AsyncSession = Depends(get_db),
):
    try:
        context = await _get_authenticated_dashboard_context(
            db,
            token=token,
            telegram_init_data=telegram_init_data,
        )
        request = await reject_request(
            db,
            request_id=request_id,
            manager_worker=_dashboard_manager(context),
        )
    except (DashboardAccessError, RequestAccessError) as exc:
        raise _dashboard_access_denied() from exc

    return {
        "id": request.id,
        "status": request.status,
        "resolved_at": _serialize_datetime(request.resolved_at),
    }
