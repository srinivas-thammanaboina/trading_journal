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
    """Paginated trades: closed (from realized_pnl_events) + open positions (from positions+executions)."""
    conn = get_db()
    # Check if fill_type column exists (schema v3+)
    has_fill_type = any(
        col[1] == "fill_type"
        for col in conn.execute("PRAGMA table_info(executions)").fetchall()
    )
    ft_col = "e.fill_type" if has_fill_type else "NULL as fill_type"

    # Build filter values list (one per filter, reused for each query part)
    filter_vals: list = []
    where_r = ""  # for realized_pnl_events aliased as r
    where_e = ""  # for executions aliased as e
    where_plain = ""  # no alias

    if date:
        where_r += " AND r.trade_date = ?"
        where_e += " AND e.trade_date = ?"
        where_plain += " AND trade_date = ?"
        filter_vals.append(date)
    else:
        if start:
            where_r += " AND r.trade_date >= ?"
            where_e += " AND e.trade_date >= ?"
            where_plain += " AND trade_date >= ?"
            filter_vals.append(start)
        if end:
            where_r += " AND r.trade_date <= ?"
            where_e += " AND e.trade_date <= ?"
            where_plain += " AND trade_date <= ?"
            filter_vals.append(end)
    if ticker:
        where_r += " AND r.ticker = ?"
        where_e += " AND e.ticker = ?"
        where_plain += " AND ticker = ?"
        filter_vals.append(ticker.upper())

    # Closed trades from realized_pnl_events
    closed_sql = f"""SELECT r.event_time, r.event_type, r.position_id, r.ticker,
                           r.contract_symbol, r.contracts_closed, r.entry_price,
                           r.exit_price, r.realized_pnl, r.trade_date, r.exit_reason,
                           {ft_col}, 'closed' as trade_status
                    FROM realized_pnl_events r
                    LEFT JOIN executions e ON e.position_id = r.position_id AND e.side = 'SLD'
                    WHERE 1=1 {where_r}"""

    # Open positions from positions + entry executions
    ft_col_open = "e.fill_type" if has_fill_type else "NULL as fill_type"
    open_sql = f"""SELECT e.execution_time as event_time, 'OPEN' as event_type,
                          e.position_id, e.ticker, e.contract_symbol,
                          e.contracts as contracts_closed, e.fill_price as entry_price,
                          NULL as exit_price, NULL as realized_pnl, e.trade_date,
                          NULL as exit_reason, {ft_col_open}, 'open' as trade_status
                   FROM executions e
                   WHERE e.side = 'BOT'
                     AND e.position_id IN (SELECT position_id FROM positions)
                     AND e.position_id NOT IN (SELECT position_id FROM realized_pnl_events)
                     {where_e}"""

    union_sql = f"SELECT * FROM ({closed_sql} UNION ALL {open_sql}) ORDER BY event_time DESC"
    # params: filter_vals for closed part + filter_vals for open part
    union_params = filter_vals + filter_vals

    # Count
    count_sql = f"""SELECT (SELECT COUNT(*) FROM realized_pnl_events WHERE 1=1 {where_plain})
                  + (SELECT COUNT(*) FROM executions WHERE side = 'BOT'
                     AND position_id IN (SELECT position_id FROM positions)
                     AND position_id NOT IN (SELECT position_id FROM realized_pnl_events)
                     {where_plain}) as cnt"""
    count_params = filter_vals + filter_vals
    total = conn.execute(count_sql, count_params).fetchone()["cnt"]
    total_pages = min(25, max(1, (min(total, 500) + per_page - 1) // per_page))
    page = min(page, total_pages) if total_pages > 0 else 1
    offset = (page - 1) * per_page

    final_sql = f"{union_sql} LIMIT {per_page} OFFSET {offset}"
    rows = [dict(r) for r in conn.execute(final_sql, union_params).fetchall()]

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
