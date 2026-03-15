"""
Read-only SQLite connection to the trading bot's journal database.

Opens in immutable/read-only mode so the journal website can never
modify bot state, even if compromised.
"""

import logging
import sqlite3
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

_conn: sqlite3.Connection | None = None


def get_db() -> sqlite3.Connection:
    """Return a read-only connection to the trading journal DB.

    Reuses a single connection (safe for single-threaded reads).
    """
    global _conn
    if _conn is not None:
        return _conn

    db_path = Path(settings.DB_PATH)
    if not db_path.exists():
        logger.warning("Trading journal DB not found at %s — queries will return empty", db_path)
        # Create an in-memory DB with empty tables so the app doesn't crash
        _conn = sqlite3.connect(":memory:")
        _conn.row_factory = sqlite3.Row
        _create_empty_schema(_conn)
        return _conn

    # Open read-only: uri=true enables the ?mode=ro query parameter
    uri = f"file:{db_path}?mode=ro"
    _conn = sqlite3.connect(uri, uri=True)
    _conn.row_factory = sqlite3.Row
    logger.info("Connected to trading journal DB (read-only): %s", db_path)
    return _conn


def _create_empty_schema(conn: sqlite3.Connection) -> None:
    """Create empty tables matching the bot's schema (for fallback mode)."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY, alert_time TEXT, source TEXT, raw_text TEXT, content_hash TEXT, parse_result TEXT, signal_id TEXT, ticker TEXT, action TEXT, strike REAL, right TEXT, entry_price REAL, stop_price REAL, risk_result TEXT, risk_reason TEXT, outcome TEXT, contracts INTEGER, trade_date TEXT);
        CREATE TABLE IF NOT EXISTS positions (position_id TEXT PRIMARY KEY, signal_id TEXT, ticker TEXT, contract_symbol TEXT, expiry_date TEXT, strike REAL, right TEXT, contracts INTEGER, entry_price REAL, stop_price REAL, ibkr_order_id INTEGER, ibkr_stop_order_id INTEGER, opened_at TEXT, unrealized_pnl REAL DEFAULT 0.0);
        CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, order_time TEXT, position_id TEXT, signal_id TEXT, ticker TEXT, contract_symbol TEXT, order_type TEXT, order_action TEXT, order_purpose TEXT, contracts INTEGER, limit_price REAL, stop_price REAL, ibkr_order_id INTEGER, status TEXT, fill_price REAL, filled_at TEXT, trade_date TEXT);
        CREATE TABLE IF NOT EXISTS executions (id INTEGER PRIMARY KEY, execution_id TEXT, execution_time TEXT, position_id TEXT, order_id INTEGER, ticker TEXT, contract_symbol TEXT, side TEXT, contracts INTEGER, fill_price REAL, commission REAL, trade_date TEXT);
        CREATE TABLE IF NOT EXISTS realized_pnl_events (id INTEGER PRIMARY KEY, event_time TEXT, event_type TEXT, position_id TEXT, ticker TEXT, contract_symbol TEXT, contracts_closed INTEGER, entry_price REAL, exit_price REAL, realized_pnl REAL, cumulative_daily_pnl REAL, trade_date TEXT);
        CREATE TABLE IF NOT EXISTS system_state (trade_date TEXT PRIMARY KEY, daily_realized_pnl REAL DEFAULT 0.0, daily_unrealized_pnl REAL DEFAULT 0.0, halted INTEGER DEFAULT 0, halt_reason TEXT, last_reconcile_time TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS daily_summaries (trade_date TEXT PRIMARY KEY, date_key TEXT, entries INTEGER DEFAULT 0, exits INTEGER DEFAULT 0, wins INTEGER DEFAULT 0, losses INTEGER DEFAULT 0, total_pnl REAL DEFAULT 0.0, pct_return REAL DEFAULT 0.0, account_size REAL, overnight_positions INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS guru_signals (id INTEGER PRIMARY KEY, signal_time TEXT, source TEXT, raw_text TEXT, ticker TEXT, action TEXT, strike REAL, right TEXT, expiry TEXT, entry_price REAL, stop_price REAL, exit_price REAL, we_executed INTEGER DEFAULT 0, our_outcome TEXT, our_reject_reason TEXT, paired_buy_id INTEGER, trade_date TEXT);
    """)


def close_db() -> None:
    global _conn
    if _conn:
        _conn.close()
        _conn = None
