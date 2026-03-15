"""
Authentication routes: login, logout.
"""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth.security import (
    check_rate_limit,
    record_login_attempt,
    verify_admin_token,
    verify_password,
)
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("authenticated"):
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login")
async def login_submit(request: Request):
    form = await request.form()
    password = form.get("password", "")
    ip = request.client.host if request.client else "unknown"

    # Rate limit check
    if not check_rate_limit(ip):
        logger.warning("Login rate limited: %s", ip)
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Too many attempts. Try again in 1 minute."},
            status_code=429,
        )

    record_login_attempt(ip)

    # Check password or admin token
    authenticated = False
    if settings.PASSWORD_HASH and verify_password(password, settings.PASSWORD_HASH):
        authenticated = True
    elif settings.ADMIN_SECRET and verify_admin_token(password):
        authenticated = True

    if not authenticated:
        logger.warning("Failed login attempt from %s", ip)
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid password."},
            status_code=401,
        )

    request.session["authenticated"] = True
    logger.info("Successful login from %s", ip)
    return RedirectResponse(url="/dashboard", status_code=302)


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)
