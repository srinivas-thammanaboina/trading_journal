"""
Trading Journal — FastAPI application entry point.

Read-only web interface for the SPX Trader bot's trading journal.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.db import close_db, get_db

# Configure logging — WARNING by default (errors only), DEBUG if enabled
log_level = logging.DEBUG if settings.DEBUG else logging.WARNING
logging.basicConfig(
    level=log_level,
    format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
)
# App logger at INFO to capture startup/auth events
logger = logging.getLogger("app")
logger.setLevel(logging.INFO)
# Suppress noisy uvicorn access logs
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    logger.info("Trading Journal starting — DB: %s", settings.DB_PATH)
    get_db()  # open connection on startup
    yield
    close_db()
    logger.info("Trading Journal stopped")


app = FastAPI(
    title="Trading Journal",
    description="Read-only trading journal for SPX Trader",
    lifespan=lifespan,
)

# Session middleware for login cookies
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SESSION_SECRET,
    max_age=settings.SESSION_EXPIRY_HOURS * 3600,
)

# Static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Register routers
from app.auth.routes import router as auth_router
from app.api.health import router as health_router
from app.api.trades import router as trades_router
from app.api.positions import router as positions_router
from app.api.alerts import router as alerts_router
from app.api.pnl import router as pnl_router
from app.api.stats import router as stats_router
from app.api.guru import router as guru_router
from app.api.broker_metrics import router as broker_metrics_router
from app.pages.routes import router as pages_router

app.include_router(auth_router)
app.include_router(health_router)
app.include_router(trades_router)
app.include_router(positions_router)
app.include_router(alerts_router)
app.include_router(pnl_router)
app.include_router(stats_router)
app.include_router(guru_router)
app.include_router(broker_metrics_router)
app.include_router(pages_router)
