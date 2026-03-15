"""
Authentication middleware: checks session cookie or admin token on protected routes.
"""

from fastapi import Request
from fastapi.responses import RedirectResponse


def is_authenticated(request: Request) -> bool:
    """Check if the current request has a valid session."""
    return request.session.get("authenticated", False)


def require_auth(request: Request):
    """Redirect to login if not authenticated. Use as a dependency."""
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=302)
    return None
