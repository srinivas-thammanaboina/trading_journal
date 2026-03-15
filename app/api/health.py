"""GET /api/health — bot status from system_state table."""

from datetime import date

from fastapi import APIRouter

from app.db import get_db

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/health")
async def health():
    conn = get_db()
    today = date.today().isoformat()

    # System state
    state = conn.execute(
        "SELECT * FROM system_state WHERE trade_date = ?", (today,)
    ).fetchone()

    # Open positions count
    pos_count = conn.execute("SELECT COUNT(*) as cnt FROM positions").fetchone()

    return {
        "bot_running": state is not None,
        "trade_date": today,
        "daily_realized_pnl": state["daily_realized_pnl"] if state else 0.0,
        "daily_unrealized_pnl": state["daily_unrealized_pnl"] if state else 0.0,
        "halted": bool(state["halted"]) if state else False,
        "open_positions": pos_count["cnt"] if pos_count else 0,
        "last_updated": state["updated_at"] if state else None,
    }
