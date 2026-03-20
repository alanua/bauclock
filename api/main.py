import uvicorn
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession
from api.routers import admin, public
from api.logger import logger
from api.redis_client import redis as api_redis
from db.database import get_db

app = FastAPI(
    title="SEK Zeiterfassung API",
    description="Backend API for construction site time tracking.",
    version="1.0.0"
)

app.include_router(admin.router, prefix="/api/v1")
app.include_router(public.router)

app.mount("/static", StaticFiles(directory="api/static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    return FileResponse("api/static/index.html")

@app.get("/dashboard")
async def serve_dashboard(token: str = None, db: AsyncSession = Depends(get_db)):
    if not token:
        raise HTTPException(status_code=404)
    
    worker_id = await api_redis.get(f"dash_token:{token}")
    if not worker_id:
        raise HTTPException(status_code=404)
    
    from db.models import Worker
    worker = await db.get(Worker, int(worker_id))
    if not worker or not worker.can_view_dashboard:
        raise HTTPException(status_code=404)
    
    return FileResponse("api/static/dashboard.html")

@app.get("/api/dashboard/data")
async def dashboard_data(token: str, db: AsyncSession = Depends(get_db)):
    worker_id = await api_redis.get(f"dash_token:{token}")
    if not worker_id:
        raise HTTPException(status_code=404)
    
    from db.models import Worker
    worker = await db.get(Worker, int(worker_id))
    if not worker or not worker.can_view_dashboard:
        raise HTTPException(status_code=404)
    
    from db.security import decrypt_string
    from db.models import Site, Payment, PaymentStatus, TimeEvent, EventType
    from sqlalchemy import select, func
    from datetime import date, timedelta
    
    today = date.today()
    
    # Workers
    stmt = select(Worker).where(
        Worker.company_id == worker.company_id,
        Worker.is_active == True
    )
    workers = (await db.execute(stmt)).scalars().all()
    
    # Today present
    present_ids = (await db.execute(
        select(TimeEvent.worker_id).where(
            func.date(TimeEvent.timestamp) == today
        ).distinct()
    )).scalars().all()
    
    return {
        "user": {
            "name": decrypt_string(worker.full_name_enc),
            "role": "OWNER" if not worker.created_by else "SUPERVISOR"
        },
        "today": {
            "present": len(present_ids),
            "total_workers": len(workers)
        },
        "workers": [
            {
                "id": w.id,
                "name": decrypt_string(w.full_name_enc),
                "type": w.worker_type.value,
                "rate": float(w.hourly_rate or 0),
                "contract_hours_week": w.contract_hours_week or 0,
                "present_today": w.id in present_ids
            }
            for w in workers
        ]
    }

from api.scheduler import setup_scheduler

@app.on_event("startup")
async def startup_event():
    logger.info("SEK Zeiterfassung API starting up...")
    setup_scheduler()

if __name__ == "__main__":
    from api.config import settings
    uvicorn.run("api.main:app", host="0.0.0.0", port=settings.API_PORT, reload=True)
