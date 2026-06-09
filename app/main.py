import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.database import init_db

# ── Lifespan ────────────────────────────────────────────────────────────────
_scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    # Startup
    await init_db()

    # Import and start scheduler (import here to avoid circular imports at module level)
    from app.services.scheduler import start_scheduler
    global _scheduler
    _scheduler = await start_scheduler()

    yield

    # Shutdown
    if _scheduler:
        _scheduler.shutdown(wait=False)


# ── FastAPI App ──────────────────────────────────────────────────────────────
app = FastAPI(
    title="GhostWriter",
    description="Automated blog article generator for Ghost CMS",
    version="1.0.0",
    lifespan=lifespan,
)

# ── Static Files ─────────────────────────────────────────────────────────────
static_dir = Path(__file__).resolve().parent / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# ── Templates ────────────────────────────────────────────────────────────────
templates_dir = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


# ── Routers ──────────────────────────────────────────────────────────────────
from app.routers import articles, dashboard, feeds, prompts, schedules, settings as settings_router

app.include_router(dashboard.router)
app.include_router(prompts.router, prefix="/prompts")
app.include_router(feeds.router, prefix="/feeds")
app.include_router(schedules.router, prefix="/schedules")
app.include_router(articles.router, prefix="/articles")
app.include_router(settings_router.router, prefix="/settings")


# ── Health Check ─────────────────────────────────────────────────────────────
@app.get("/health")
async def health_check():
    return {"status": "ok", "app": "GhostWriter", "version": "1.0.0"}


# ── Root Redirect ────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})
