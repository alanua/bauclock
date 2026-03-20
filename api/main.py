import uvicorn
from fastapi import FastAPI
from api.routers import admin, public
from api.logger import logger

app = FastAPI(
    title="SEK Zeiterfassung API",
    description="Backend API for construction site time tracking.",
    version="1.0.0"
)

from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi import HTTPException

app.include_router(admin.router, prefix="/api/v1")
app.include_router(public.router)

app.mount("/static", StaticFiles(directory="api/static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    return FileResponse("api/static/index.html")

@app.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard(token: str = None):
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized: Token required")
    # Additional token validation can be added here
    return FileResponse("api/static/dashboard.html")

from api.scheduler import setup_scheduler

@app.on_event("startup")
async def startup_event():
    logger.info("SEK Zeiterfassung API starting up...")
    setup_scheduler()

if __name__ == "__main__":
    from api.config import settings
    uvicorn.run("api.main:app", host="0.0.0.0", port=settings.API_PORT, reload=True)
