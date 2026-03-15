"""
Authentication helpers: password hashing, session validation, rate limiting.
"""

import hashlib
import hmac
import secrets
import time
from datetime import datetime

import bcrypt

from app.config import settings


def hash_password(password: str) -> str:
    """Hash a password with bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False


def verify_admin_token(token: str) -> bool:
    """Check if the provided token matches the admin secret."""
    if not settings.ADMIN_SECRET:
        return False
    return hmac.compare_digest(token, settings.ADMIN_SECRET)


def generate_session_token() -> str:
    """Generate a cryptographically secure session token."""
    return secrets.token_urlsafe(32)


# Simple in-memory rate limiter
_login_attempts: dict[str, list[float]] = {}
_RATE_WINDOW = 60.0  # 1 minute
_MAX_ATTEMPTS = 5


def check_rate_limit(ip: str) -> bool:
    """Return True if the IP is within rate limits, False if blocked."""
    now = time.monotonic()
    attempts = _login_attempts.get(ip, [])
    # Prune old attempts
    attempts = [t for t in attempts if now - t < _RATE_WINDOW]
    _login_attempts[ip] = attempts
    return len(attempts) < _MAX_ATTEMPTS


def record_login_attempt(ip: str) -> None:
    """Record a login attempt for rate limiting."""
    now = time.monotonic()
    if ip not in _login_attempts:
        _login_attempts[ip] = []
    _login_attempts[ip].append(now)
