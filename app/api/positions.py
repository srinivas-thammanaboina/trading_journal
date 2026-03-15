"""GET /api/positions — current open positions."""

from fastapi import APIRouter

from app.db import get_db

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/positions")
async def get_positions():
    conn = get_db()
    rows = conn.execute(
        """SELECT position_id, ticker, contract_symbol, expiry_date,
                  strike, right, contracts, entry_price, stop_price,
                  opened_at, unrealized_pnl
           FROM positions ORDER BY opened_at DESC"""
    ).fetchall()
    return [dict(r) for r in rows]
