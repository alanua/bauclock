import pytz
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, func, and_
from aiogram import Bot

from api.logger import logger
from bot.config import settings
from db.database import async_session_maker
from db.models import TimeEvent, EventType, Worker, WorkerType, Payment, PaymentStatus
from db.security import decrypt_string
from aiogram.types import BufferedInputFile
from zoneinfo import ZoneInfo
from api.services.pdf_generator import generate_pdf

# Target Timezone
BERLIN_TZ = pytz.timezone("Europe/Berlin")

scheduler = AsyncIOScheduler(timezone=BERLIN_TZ)
bot = Bot(token=settings.BOT_TOKEN)

async def check_arbzg_pauses():
    """Checks for pauses extending beyond ArbZG limits or missing pauses and alerts via Bot."""
    logger.info("Executing ArbZG pause check...")
    async with async_session_maker() as session:
        today = datetime.now(timezone.utc).date()
        
        # ArbZG simple check: Alert if working > 6 hours without taking at least 30m pause.
        # Check active workers today.
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
                    # simplistic calculation for pause duration could go here
                    pass
                elif e.event_type == EventType.CHECKOUT:
                    is_working = False
                    
            if is_working and checkin_time:
                worked_hours = (now - checkin_time).total_seconds() / 3600
                
                # Check 9h / 45m rule first
                if worked_hours > 9.0 and total_pause_m < 45:
                    # Alert Worker
                    try:
                        tg_id = int(decrypt_string(w.telegram_id_enc))
                        msg = "KRITISCH ArbZG §4: Sie arbeiten über 9 Stunden ohne 45 Min. Pause. Bitte sofort Pause einlegen!" if w.language.value == "de" else "КРИТИЧНО ArbZG §4: Працюєте понад 9 годин без 45 хв паузи. Зробіть перерву!"
                        await bot.send_message(tg_id, msg)
                    except Exception:
                        pass
                        
                    # Alert Chiefs
                    ch_stmt = select(Worker).where(Worker.company_id == w.company_id, Worker.can_view_dashboard == True)
                    chiefs = (await session.execute(ch_stmt)).scalars().all()
                    w_name = decrypt_string(w.full_name_enc)
                    for c in chiefs:
                        try:
                            c_tg = int(decrypt_string(c.telegram_id_enc))
                            await bot.send_message(c_tg, f"ArbZG Verletzung: {w_name} arbeitet >9h ohne 45m Pause!")
                        except Exception:
                            pass
                            
                # Check 6h / 30m rule
                elif worked_hours > 6.0 and total_pause_m < 30:
                    try:
                        tg_id = int(decrypt_string(w.telegram_id_enc))
                        msg = "Achtung ArbZG §4: Sie arbeiten über 6 Stunden ohne 30 Min. Pause. Bitte Pause einlegen!" if w.language.value == "de" else "Увага ArbZG §4: Ви працюєте понад 6 годин. Зробіть перерву!"
                        await bot.send_message(tg_id, msg)
                    except Exception:
                        pass

async def warn_unclosed_days_1800():
    """Sends 18:00 reminder to workers with unclosed days."""
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
                    msg = "Erinnerung: Ihr Arbeitstag ist noch nicht beendet (Checkout vergessen?)." if w.language.value == "de" else "Нагадування: Робочий день ще не завершено (не забули Checkout?)."
                    await bot.send_message(tg_id, msg)
                except Exception as e:
                    logger.error(f"Failed to send 18:00 alert to {w.id}: {e}")

async def alert_unclosed_days_2000():
    """Sends 20:00 alert to supervisors for unclosed days."""
    logger.info("Executing 20:00 unclosed days alert to supervisors...")
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
                # Notify all chefs for this company
                stmt_chiefs = select(Worker).where(Worker.company_id == w.company_id, Worker.can_view_dashboard == True)
                chiefs = (await session.execute(stmt_chiefs)).scalars().all()
                name = decrypt_string(w.full_name_enc)
                
                for c in chiefs:
                    try:
                        c_id = int(decrypt_string(c.telegram_id_enc))
                        await bot.send_message(c_id, f"Achtung: Mitarbeiter '{name}' hat sich heute noch nicht abgemeldet! Bitte im Adminbereich manuell schließen.")
                    except Exception:
                        pass

async def generate_weekly_report():
    """Generates the weekly PDF report on Mondays at 8:00."""
    logger.info("Generating weekly PDF report and sending to Chiefs...")
    async with async_session_maker() as session:
        # Get last week's Monday and Sunday
        today = datetime.now(ZoneInfo("Europe/Berlin")).date()
        start_of_week = today - timedelta(days=today.weekday() + 7) 
        end_of_week = start_of_week + timedelta(days=6)
        
        # 1. Fetch all distinct companies
        stmt_comps = select(Worker.company_id).distinct()
        companies = (await session.execute(stmt_comps)).scalars().all()
        
        for comp_id in companies:
            if not comp_id: continue
            
            # 2. Get active workers for the company
            w_stmt = select(Worker).where(Worker.company_id == comp_id, Worker.is_active == True)
            workers = (await session.execute(w_stmt)).scalars().all()
            
            # Map of worker names to their weekly statistics
            report_data = []
            
            for w in workers:
                # Calculate hours paid and total amounts for the week
                p_stmt = select(func.sum(Payment.hours_paid), func.sum(Payment.amount_paid)).where(
                    Payment.worker_id == w.id,
                    Payment.period_start >= start_of_week,
                    Payment.period_start <= end_of_week
                )
                res = (await session.execute(p_stmt)).first()
                hours = res[0] or 0.0
                total = res[1] or 0.0
                
                # Payment Status (Checking if any exist and are CONFIRMED)
                status_stmt = select(Payment.status).where(
                    Payment.worker_id == w.id,
                    Payment.period_start >= start_of_week,
                    Payment.period_start <= end_of_week
                )
                statuses = (await session.execute(status_stmt)).scalars().all()
                all_confirmed = "🟢 CONFIRMED" if len(statuses) > 0 and all(s == PaymentStatus.CONFIRMED for s in statuses) else "🔴 PENDING"
                
                report_data.append({
                    "name": decrypt_string(w.full_name_enc),
                    "hours": hours,
                    "rate": w.hourly_rate or 0.0,
                    "amount": total,
                    "status": all_confirmed
                })
                
            if not report_data:
                continue
                
            # 3. Pass data to WeasyPrint generator
            pdf_bytes = generate_pdf(comp_id, start_of_week, end_of_week, report_data)
            
            # 4. Find all chiefs for this company and send the PDF
            c_stmt = select(Worker).where(Worker.company_id == comp_id, Worker.can_view_dashboard == True, Worker.is_active == True)
            chiefs = (await session.execute(c_stmt)).scalars().all()
            
            for c in chiefs:
                try:
                    c_tg = int(decrypt_string(c.telegram_id_enc))
                    file = BufferedInputFile(pdf_bytes, filename=f"Wochenbericht_{start_of_week.strftime('%Y%m%d')}.pdf")
                    msg = "Hier ist Ihr wöchentlicher Baustellenbericht 📊" if c.language.value == "de" else "Ось ваш тижневий звіт 📊"
                    await bot.send_document(c_tg, file, caption=msg)
                except Exception as e:
                    logger.error(f"Failed to send PDF to {c.id}: {e}")

async def monitor_minijob_limits():
    """Monitors monthly earnings for MINIJOB workers and alerts if near 538 EUR."""
    logger.info("Checking Minijob limits...")
    async with async_session_maker() as session:
        today = datetime.now(timezone.utc).date()
        start_of_month = today.replace(day=1)
        
        # Get all minijobbers
        stmt = select(Worker).where(Worker.worker_type == WorkerType.MINIJOB, Worker.is_active == True)
        minis = (await session.execute(stmt)).scalars().all()
        
        for w in minis:
            # Check payments for this month plus running hours
            pymt_stmt = select(func.sum(Payment.amount_paid)).where(
                Payment.worker_id == w.id,
                Payment.period_start >= start_of_month
            )
            paid_m = (await session.execute(pymt_stmt)).scalar() or 0.0
            
            w_name = decrypt_string(w.full_name_enc)
            
            # Critical Alert at 520 EUR
            if paid_m >= 520.0:
                try:
                    w_tg = int(decrypt_string(w.telegram_id_enc))
                    msg_w = f"KRITISCH: Sie haben fast das Minijob-Limit erreicht (Aktuell: €{paid_m:.2f} von €538)." if w.language.value == "de" else f"КРИТИЧНО: Ви майже досягли ліміту (Вже: €{paid_m:.2f} з €538)."
                    await bot.send_message(w_tg, msg_w)
                    
                    ch_stmt = select(Worker).where(Worker.company_id == w.company_id, Worker.can_view_dashboard == True)
                    chiefs = (await session.execute(ch_stmt)).scalars().all()
                    for c in chiefs:
                        c_tg = int(decrypt_string(c.telegram_id_enc))
                        await bot.send_message(c_tg, f"KRITISCH: Minijobber {w_name} fast am Limit! (Aktuell: €{paid_m:.2f}/538€)")
                except Exception:
                    pass
            
            # Warning Alert at 480 EUR 
            elif paid_m >= 480.0:  
                try:
                    # Notify Worker
                    w_tg = int(decrypt_string(w.telegram_id_enc))
                    msg_w = f"Warnung: Sie nähern sich der 538€ Minijob-Grenze (Bisher: €{paid_m:.2f})." if w.language.value == "de" else f"Попередження: Ви наближаєтеся до ліміту 538€ (Вже: €{paid_m:.2f})."
                    await bot.send_message(w_tg, msg_w)
                    
                    # Notify Chiefs
                    ch_stmt = select(Worker).where(Worker.company_id == w.company_id, Worker.can_view_dashboard == True)
                    chiefs = (await session.execute(ch_stmt)).scalars().all()
                    for c in chiefs:
                        c_tg = int(decrypt_string(c.telegram_id_enc))
                        await bot.send_message(c_tg, f"Minijob-Warnung: {w_name} nähert sich der 538€ Grenze (Aktuell: €{paid_m:.2f}).")
                except Exception:
                    pass

def setup_scheduler():
    """Registers all cron jobs and starts the scheduler."""
    scheduler.add_job(check_arbzg_pauses, 'interval', minutes=15)
    scheduler.add_job(warn_unclosed_days_1800, CronTrigger(hour=18, minute=0, timezone=BERLIN_TZ))
    scheduler.add_job(alert_unclosed_days_2000, CronTrigger(hour=20, minute=0, timezone=BERLIN_TZ))
    scheduler.add_job(generate_weekly_report, CronTrigger(day_of_week='mon', hour=8, minute=0, timezone=BERLIN_TZ))
    scheduler.add_job(monitor_minijob_limits, CronTrigger(hour=19, minute=0, timezone=BERLIN_TZ))
    
    scheduler.start()
    logger.info("Background Scheduler initialized in Europe/Berlin timezone.")
