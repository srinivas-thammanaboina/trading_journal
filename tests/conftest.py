"""Shared test fixtures — resets rate limiter between test modules."""

import pytest


@pytest.fixture(autouse=True, scope="module")
def reset_rate_limiter():
    """Reset login rate limiter before each test module."""
    from app.auth.security import _login_attempts
    _login_attempts.clear()
    yield
