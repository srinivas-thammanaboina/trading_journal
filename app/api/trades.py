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


@router.get("/trades/pnl")
async def get_trades_pnl(
    date: str | None = Query(None),
    start: str | None = Query(None),
    end: str | None = Query(None),
    ticker: str | None = Query(None),
    page: int = Query(1, ge=1, le=25),
    per_page: int = Query(20, ge=1, le=50),
):
    """Paginated realized P&L events for trades table."""
    conn = get_db()
    sql = "SELECT * FROM realized_pnl_events WHERE 1=1"
    count_sql = "SELECT COUNT(*) as cnt FROM realized_pnl_events WHERE 1=1"
    params: list = []

    if date:
        sql += " AND trade_date = ?"
        count_sql += " AND trade_date = ?"
        params.append(date)
    else:
        if start:
            sql += " AND trade_date >= ?"
            count_sql += " AND trade_date >= ?"
            params.append(start)
        if end:
            sql += " AND trade_date <= ?"
            count_sql += " AND trade_date <= ?"
            params.append(end)
    if ticker:
        sql += " AND ticker = ?"
        count_sql += " AND ticker = ?"
        params.append(ticker.upper())

    total = conn.execute(count_sql, params).fetchone()["cnt"]
    total_pages = min(25, max(1, (min(total, 500) + per_page - 1) // per_page))
    page = min(page, total_pages) if total_pages > 0 else 1
    offset = (page - 1) * per_page

    sql += f" ORDER BY event_time DESC LIMIT {per_page} OFFSET {offset}"
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

    return {"trades": rows, "page": page, "total_pages": total_pages, "total": total}


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
