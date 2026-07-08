import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import Base, SessionLocal, engine, get_db, run_lightweight_migrations
from app.routers import (
    activity,
    alert_rules,
    auth,
    blacklists,
    clients,
    diagnostics,
    dashboard,
    domains,
    groups,
    ips,
    listings,
    logs,
    maintenance,
    reports,
    services as services_router,
    settings_router,
    users,
)
from app.runtime_settings import effective_settings
from app.seed import seed_if_empty
from app.services.logging_control import apply_log_level
from app.services.scheduler import start_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    run_lightweight_migrations(engine)
    db = SessionLocal()
    try:
        seed_if_empty(db)
        apply_log_level(effective_settings(db).log_level)
    finally:
        db.close()
    start_scheduler()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (
    auth.router, clients.router, services_router.router, groups.router, ips.router,
    domains.router, blacklists.router, listings.router, alert_rules.router,
    settings_router.router, reports.router, activity.router, dashboard.router, diagnostics.router,
    users.router, logs.router, maintenance.router,
):
    app.include_router(router)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

PAGES = ["dashboard", "ips", "domains", "clients", "groups", "blacklists", "alert-rules", "settings", "activity", "users", "logs", "login"]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
async def root(request: Request, db: Session = Depends(get_db)):
    lang = effective_settings(db).language
    return templates.TemplateResponse("dashboard.html", {"request": request, "active_page": "dashboard", "lang": lang})


for page in PAGES:
    if page == "dashboard":
        continue

    def make_view(page_name):
        async def view(request: Request, db: Session = Depends(get_db)):
            lang = effective_settings(db).language
            return templates.TemplateResponse(f"{page_name}.html", {"request": request, "active_page": page_name, "lang": lang})
        return view

    app.add_api_route(f"/{page}", make_view(page), methods=["GET"], include_in_schema=False)
