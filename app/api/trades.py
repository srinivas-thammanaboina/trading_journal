"""GET /api/trades — execution history."""

from datetime import date

from fastapi import APIRouter, Query

from app.db import get_db

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/trades")
async def get_trades(
    trade_date: str | None = Query(None, description="YYYY-MM-DD"),
    ticker: str | None = Query(None),
    start: str | None = Query(None, description="YYYY-MM-DD"),
    end: str | None = Query(None, description="YYYY-MM-DD"),
    limit: int = Query(100, ge=1, le=1000),
):
    conn = get_db()
    sql = "SELECT * FROM executions WHERE 1=1"
    params: list = []

    if trade_date:
        sql += " AND trade_date = ?"
        params.append(trade_date)
    else:
        if start:
            sql += " AND trade_date >= ?"
            params.append(start)
        if end:
            sql += " AND trade_date <= ?"
            params.append(end)

    if ticker:
        sql += " AND ticker = ?"
        params.append(ticker.upper())

    sql += " ORDER BY execution_time DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


@router.get("/trade/{position_id}")
async def get_trade_detail(position_id: str):
    """Full trade detail for a single position."""
    from state.journal import TradingJournal

    conn = get_db()
    journal = TradingJournal(conn)
    detail = journal.trade_detail(position_id)
    if not detail:
        return {"error": "Position not found"}
    return detail
