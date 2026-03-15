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
    PASSWORD_HASH: str = os.getenv("PASSWORD_HASH", "")  # bcrypt hash of login password
    SESSION_EXPIRY_HOURS: int = int(os.getenv("SESSION_EXPIRY_HOURS", "24"))

    # Rate limiting
    LOGIN_RATE_LIMIT: str = os.getenv("LOGIN_RATE_LIMIT", "5/minute")

    # Server
    HOST: str = os.getenv("HOST", "127.0.0.1")
    PORT: int = int(os.getenv("PORT", "8001"))
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"


settings = Settings()
