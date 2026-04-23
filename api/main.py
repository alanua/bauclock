import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from api.routers import admin, compliance, dashboard, dashboard_router, public
from api.logger import logger

app = FastAPI(
    title="SEK Zeiterfassung API",
    description="Backend API for construction site time tracking.",
    version="1.0.0"
)

app.include_router(admin.router, prefix="/api/v1")
app.include_router(compliance.router, prefix="/api/v1")
app.include_router(public.router)
app.include_router(dashboard_router.router)
app.include_router(dashboard.router)

app.mount("/static", StaticFiles(directory="api/static"), name="static")
app.mount("/public-ui", StaticFiles(directory="api/static/public-ui", check_dir=False), name="public-ui")

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    return FileResponse("api/static/index.html")

from api.scheduler import setup_scheduler

@app.on_event("startup")
async def startup_event():
    logger.info("SEK Zeiterfassung API starting up...")
    setup_scheduler()

if __name__ == "__main__":
    from api.config import settings
    uvicorn.run("api.main:app", host="0.0.0.0", port=settings.API_PORT, reload=True)
