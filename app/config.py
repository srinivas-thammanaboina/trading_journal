"""
Trading Journal configuration.

All settings loaded from environment variables with sensible defaults.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class Settings:
    # Database — read-only connection to the trading bot's SQLite journal
    DB_PATH: str = os.getenv(
        "DB_PATH",
        str(Path(__file__).resolve().parent.parent.parent / "spx_trader" / "state" / "trading_journal.db"),
    )

    # Auth
    ADMIN_SECRET: str = os.getenv("ADMIN_SECRET", "")
    SESSION_SECRET: str = os.getenv("SESSION_SECRET", "change-me-in-production")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "test123")
    PASSWORD_HASH: str = os.getenv("PASSWORD_HASH", "")  # bcrypt hash — auto-generated if ADMIN_PASSWORD is set
    SESSION_EXPIRY_HOURS: int = int(os.getenv("SESSION_EXPIRY_HOURS", "24"))

    # Rate limiting
    LOGIN_RATE_LIMIT: str = os.getenv("LOGIN_RATE_LIMIT", "5/minute")

    # Server
    HOST: str = os.getenv("HOST", "127.0.0.1")
    PORT: int = int(os.getenv("PORT", "8001"))
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"


settings = Settings()

# Auto-hash ADMIN_PASSWORD if PASSWORD_HASH is not set
if not settings.PASSWORD_HASH and settings.ADMIN_PASSWORD:
    import bcrypt
    settings.PASSWORD_HASH = bcrypt.hashpw(
        settings.ADMIN_PASSWORD.encode(), bcrypt.gensalt()
    ).decode()
