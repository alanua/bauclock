import pytz
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, func
from api.bot_client import send_telegram_message, send_telegram_document
from api.logger import logger
from api.config import settings
from db.database import SessionLocal as async_session_maker
from db.models import TimeEvent, EventType, Worker, WorkerType, Payment, PaymentStatus
from db.security import decrypt_string
from zoneinfo import ZoneInfo
from api.services.pdf_generator import generate_pdf

BERLIN_TZ = pytz.timezone("Europe/Berlin")
scheduler = AsyncIOScheduler(timezone=BERLIN_TZ)

async def check_arbzg_pauses():
    logger.info("Executing ArbZG pause check...")
    async with async_session_maker() as session:
        today = datetime.now(timezone.utc).date()
        stmt = select(Worker).where(Worker.is_active == True)
        workers = (await session.execute(stmt)).scalars().all()
        now = datetime.now(timezone.utc)
        for w in workers:
            ev_stmt = select(TimeEvent).where(
                TimeEvent.worker_id == w.id,
                func.date(TimeEvent.timestamp) == today
            ).order_by(TimeEvent.timestamp.asc())
            events = (await session.execute(ev_stmt)).scalars().all()
            if not events:
                continue
            checkin_time = None
            total_pause_m = 0
            is_working = False
            for e in events:
                if e.event_type == EventType.CHECKIN:
                    checkin_time = e.timestamp
                    is_working = True
                elif e.event_type == EventType.PAUSE_START:
                    is_working = False
                elif e.event_type == EventType.PAUSE_END:
                    is_working = True
                elif e.event_type == EventType.CHECKOUT:
                    is_working = False
            if is_working and checkin_time:
                worked_hours = (now - checkin_time).total_seconds() / 3600
                if worked_hours > 9.0 and total_pause_m < 45:
                    try:
                        tg_id = int(decrypt_string(w.telegram_id_enc))
                        msg = "KRITISCH ArbZG §4: Sie arbeiten über 9 Stunden ohne 45 Min. Pause!" if w.language.value == "de" else "КРИТИЧНО: Понад 9 годин без 45 хв паузи!"
                        await send_telegram_message(tg_id, msg, settings.BOT_TOKEN)
                    except Exception:
                        pass
                    ch_stmt = select(Worker).where(Worker.company_id == w.company_id, Worker.can_view_dashboard == True)
                    chiefs = (await session.execute(ch_stmt)).scalars().all()
                    w_name = decrypt_string(w.full_name_enc)
                    for c in chiefs:
                        try:
                            c_tg = int(decrypt_string(c.telegram_id_enc))
                            await send_telegram_message(c_tg, f"ArbZG Verletzung: {w_name} arbeitet >9h ohne 45m Pause!", settings.BOT_TOKEN)
                        except Exception:
                            pass
                elif worked_hours > 6.0 and total_pause_m < 30:
                    try:
                        tg_id = int(decrypt_string(w.telegram_id_enc))
                        msg = "Achtung ArbZG §4: Sie arbeiten über 6 Stunden ohne 30 Min. Pause!" if w.language.value == "de" else "Увага: Понад 6 годин без 30 хв паузи!"
                        await send_telegram_message(tg_id, msg, settings.BOT_TOKEN)
                    except Exception:
                        pass

async def warn_unclosed_days_1800():
    logger.info("Executing 18:00 unclosed days check...")
    async with async_session_maker() as session:
        today = datetime.now(timezone.utc).date()
        stmt = select(Worker).join(TimeEvent).where(func.date(TimeEvent.timestamp) == today).distinct()
        workers = (await session.execute(stmt)).scalars().all()
        for w in workers:
            ev_stmt = select(TimeEvent).where(
                TimeEvent.worker_id == w.id,
                func.date(TimeEvent.timestamp) == today
            ).order_by(TimeEvent.timestamp.desc()).limit(1)
            last_event = (await session.execute(ev_stmt)).scalar_one_or_none()
            if last_event and last_event.event_type != EventType.CHECKOUT:
                try:
                    tg_id = int(decrypt_string(w.telegram_id_enc))
                    msg = "Erinnerung: Ihr Arbeitstag ist noch nicht beendet." if w.language.value == "de" else "Нагадування: Робочий день ще не завершено."
                    await send_telegram_message(tg_id, msg, settings.BOT_TOKEN)
                except Exception as e:
                    logger.error(f"Failed to send 18:00 alert to {w.id}: {e}")

async def alert_unclosed_days_2000():
    logger.info("Executing 20:00 unclosed days alert...")
    async with async_session_maker() as session:
        today = datetime.now(timezone.utc).date()
        stmt = select(Worker).join(TimeEvent).where(func.date(TimeEvent.timestamp) == today).distinct()
        workers = (await session.execute(stmt)).scalars().all()
        for w in workers:
            ev_stmt = select(TimeEvent).where(
                TimeEvent.worker_id == w.id,
                func.date(TimeEvent.timestamp) == today
            ).order_by(TimeEvent.timestamp.desc()).limit(1)
            last_event = (await session.execute(ev_stmt)).scalar_one_or_none()
            if last_event and last_event.event_type != EventType.CHECKOUT:
                stmt_chiefs = select(Worker).where(Worker.company_id == w.company_id, Worker.can_view_dashboard == True)
                chiefs = (await session.execute(stmt_chiefs)).scalars().all()
                name = decrypt_string(w.full_name_enc)
                for c in chiefs:
                    try:
                        c_id = int(decrypt_string(c.telegram_id_enc))
                        await send_telegram_message(c_id, f"Achtung: Mitarbeiter '{name}' hat sich heute nicht abgemeldet!", settings.BOT_TOKEN)
                    except Exception:
                        pass

async def generate_weekly_report():
    logger.info("Generating weekly PDF report...")
    async with async_session_maker() as session:
        today = datetime.now(ZoneInfo("Europe/Berlin")).date()
        start_of_week = today - timedelta(days=today.weekday() + 7)
        end_of_week = start_of_week + timedelta(days=6)
        stmt_comps = select(Worker.company_id).distinct()
        companies = (await session.execute(stmt_comps)).scalars().all()
        for comp_id in companies:
            if not comp_id:
                continue
            w_stmt = select(Worker).where(Worker.company_id == comp_id, Worker.is_active == True)
            workers = (await session.execute(w_stmt)).scalars().all()
            report_data = []
            for w in workers:
                p_stmt = select(func.sum(Payment.hours_paid), func.sum(Payment.amount_paid)).where(
                    Payment.worker_id == w.id,
                    Payment.period_start >= start_of_week,
                    Payment.period_start <= end_of_week
                )
                res = (await session.execute(p_stmt)).first()
                hours = res[0] or 0.0
                total = res[1] or 0.0
                status_stmt = select(Payment.status).where(
                    Payment.worker_id == w.id,
                    Payment.period_start >= start_of_week,
                    Payment.period_start <= end_of_week
                )
                statuses = (await session.execute(status_stmt)).scalars().all()
                all_confirmed = "🟢" if statuses and all(s == PaymentStatus.CONFIRMED for s in statuses) else "🔴"
                report_data.append({
                    "name": decrypt_string(w.full_name_enc),
                    "hours": hours,
                    "rate": w.hourly_rate or 0.0,
                    "amount": total,
                    "status": all_confirmed
                })
            if not report_data:
                continue
            pdf_bytes = generate_pdf(comp_id, start_of_week, end_of_week, report_data)
            c_stmt = select(Worker).where(Worker.company_id == comp_id, Worker.can_view_dashboard == True, Worker.is_active == True)
            chiefs = (await session.execute(c_stmt)).scalars().all()
            for c in chiefs:
                try:
                    c_tg = int(decrypt_string(c.telegram_id_enc))
                    msg = "Hier ist Ihr wöchentlicher Baustellenbericht 📊" if c.language.value == "de" else "Ось ваш тижневий звіт 📊"
                    await send_telegram_document(c_tg, pdf_bytes, f"Wochenbericht_{start_of_week.strftime('%Y%m%d')}.pdf", msg, settings.BOT_TOKEN)
                except Exception as e:
                    logger.error(f"Failed to send PDF to {c.id}: {e}")

async def monitor_minijob_limits():
    logger.info("Checking Minijob limits...")
    async with async_session_maker() as session:
        today = datetime.now(timezone.utc).date()
        start_of_month = today.replace(day=1)
        stmt = select(Worker).where(Worker.worker_type == WorkerType.MINIJOB, Worker.is_active == True)
        minis = (await session.execute(stmt)).scalars().all()
        for w in minis:
            pymt_stmt = select(func.sum(Payment.amount_paid)).where(
                Payment.worker_id == w.id,
                Payment.period_start >= start_of_month
            )
            paid_m = (await session.execute(pymt_stmt)).scalar() or 0.0
            w_name = decrypt_string(w.full_name_enc)
            if paid_m >= 520.0:
                try:
                    w_tg = int(decrypt_string(w.telegram_id_enc))
                    msg_w = f"KRITISCH: Fast am Minijob-Limit! (€{paid_m:.2f}/538€)" if w.language.value == "de" else f"КРИТИЧНО: Майже ліміт! (€{paid_m:.2f}/538€)"
                    await send_telegram_message(w_tg, msg_w, settings.BOT_TOKEN)
                    ch_stmt = select(Worker).where(Worker.company_id == w.company_id, Worker.can_view_dashboard == True)
                    chiefs = (await session.execute(ch_stmt)).scalars().all()
                    for c in chiefs:
                        c_tg = int(decrypt_string(c.telegram_id_enc))
                        await send_telegram_message(c_tg, f"KRITISCH: Minijobber {w_name} fast am Limit! (€{paid_m:.2f}/538€)", settings.BOT_TOKEN)
                except Exception:
                    pass
            elif paid_m >= 480.0:
                try:
                    w_tg = int(decrypt_string(w.telegram_id_enc))
                    msg_w = f"Warnung: Minijob-Grenze naht (€{paid_m:.2f}/538€)" if w.language.value == "de" else f"Попередження: Наближення ліміту (€{paid_m:.2f}/538€)"
                    await send_telegram_message(w_tg, msg_w, settings.BOT_TOKEN)
                    ch_stmt = select(Worker).where(Worker.company_id == w.company_id, Worker.can_view_dashboard == True)
                    chiefs = (await session.execute(ch_stmt)).scalars().all()
                    for c in chiefs:
                        c_tg = int(decrypt_string(c.telegram_id_enc))
                        await send_telegram_message(c_tg, f"Minijob-Warnung: {w_name} nähert sich 538€ (€{paid_m:.2f})", settings.BOT_TOKEN)
                except Exception:
                    pass

def setup_scheduler():
    scheduler.add_job(check_arbzg_pauses, 'interval', minutes=15)
    scheduler.add_job(warn_unclosed_days_1800, CronTrigger(hour=18, minute=0, timezone=BERLIN_TZ))
    scheduler.add_job(alert_unclosed_days_2000, CronTrigger(hour=20, minute=0, timezone=BERLIN_TZ))
    scheduler.add_job(generate_weekly_report, CronTrigger(day_of_week='mon', hour=8, minute=0, timezone=BERLIN_TZ))
    scheduler.add_job(monitor_minijob_limits, CronTrigger(hour=19, minute=0, timezone=BERLIN_TZ))
    scheduler.start()
    logger.info("Scheduler started in Europe/Berlin timezone.")
