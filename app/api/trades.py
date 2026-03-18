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
    # Use exit_reason as fill_type (already captures partial_profit, auto_close, guru_close, etc.)
    closed_sql = f"""SELECT event_time, event_type, position_id, ticker,
                           contract_symbol, contracts_closed, entry_price,
                           exit_price, realized_pnl, trade_date, exit_reason,
                           exit_reason as fill_type, 'closed' as trade_status
                    FROM realized_pnl_events
                    WHERE 1=1 {where_r.replace('r.', '')}"""

    # All entry executions (BOT side) — shows both open and closed entries
    ft_col_open = "fill_type" if has_fill_type else "NULL as fill_type"
    where_plain_filt = where_e.replace('e.', '')
    entry_sql = f"""SELECT execution_time as event_time, 'ENTRY' as event_type,
                          position_id, ticker, contract_symbol,
                          contracts as contracts_closed, fill_price as entry_price,
                          NULL as exit_price, NULL as realized_pnl, trade_date,
                          NULL as exit_reason, {ft_col_open},
                          CASE WHEN position_id IN (SELECT position_id FROM positions)
                               THEN 'open' ELSE 'closed' END as trade_status
                   FROM executions
                   WHERE side = 'BOT'
                     {where_plain_filt}"""

    union_sql = f"SELECT * FROM ({closed_sql} UNION ALL {entry_sql}) ORDER BY event_time DESC"
    # params: filter_vals for closed part + filter_vals for entry part
    union_params = filter_vals + filter_vals

    # Count
    count_sql = f"""SELECT (SELECT COUNT(*) FROM realized_pnl_events WHERE 1=1 {where_plain})
                  + (SELECT COUNT(*) FROM executions WHERE side = 'BOT'
                     {where_plain}) as cnt"""
    count_params = filter_vals + filter_vals
    total = conn.execute(count_sql, count_params).fetchone()["cnt"]
    total_pages = min(25, max(1, (min(total, 500) + per_page - 1) // per_page))
    page = min(page, total_pages) if total_pages > 0 else 1
    offset = (page - 1) * per_page

    final_sql = f"{union_sql} LIMIT {per_page} OFFSET {offset}"
    rows = [dict(r) for r in conn.execute(final_sql, union_params).fetchall()]

    return {"trades": rows, "page": page, "total_pages": total_pages, "total": total}


@router.get("/trades/positions")
async def get_trades_positions(
    date: str | None = Query(None),
    start: str | None = Query(None),
    end: str | None = Query(None),
    ticker: str | None = Query(None),
    page: int = Query(1, ge=1, le=25),
    per_page: int = Query(20, ge=1, le=50),
):
    """Position-level trade summary: one row per position with aggregated P&L."""
    conn = get_db()

    # Find position_ids that have ANY activity (entry or exit) in the date range
    date_where = ""
    date_params: list = []
    if date:
        date_where += " AND trade_date = ?"
        date_params.append(date)
    else:
        if start:
            date_where += " AND trade_date >= ?"
            date_params.append(start)
        if end:
            date_where += " AND trade_date <= ?"
            date_params.append(end)

    ticker_where = ""
    ticker_params: list = []
    if ticker:
        ticker_where += " AND ticker = ?"
        ticker_params.append(ticker.upper())

    # Positions with any execution OR pnl event in range
    pid_sql = f"""
        SELECT DISTINCT position_id FROM (
            SELECT position_id FROM executions WHERE 1=1 {date_where} {ticker_where}
            UNION
            SELECT position_id FROM realized_pnl_events WHERE 1=1 {date_where} {ticker_where}
        )
    """
    pid_params = date_params + ticker_params + date_params + ticker_params
    pid_rows = conn.execute(pid_sql, pid_params).fetchall()
    all_pids = [r["position_id"] for r in pid_rows]

    if not all_pids:
        return {"trades": [], "page": page, "total_pages": 0, "total": 0}

    placeholders = ",".join("?" * len(all_pids))

    # Get entry info: prefer executions (BOT side), fall back to realized_pnl_events
    pos_sql = f"""
        SELECT position_id, ticker, contract_symbol, entry_time, trade_date, entry_price, qty
        FROM (
            SELECT e.position_id,
                   e.ticker,
                   e.contract_symbol,
                   MIN(e.execution_time) as entry_time,
                   e.trade_date,
                   MAX(CASE WHEN e.side = 'BOT' THEN e.fill_price END) as entry_price,
                   SUM(CASE WHEN e.side = 'BOT' THEN e.contracts ELSE 0 END) as qty
            FROM executions e
            WHERE e.side = 'BOT' AND e.position_id IN ({placeholders})
            GROUP BY e.position_id

            UNION ALL

            SELECT r.position_id,
                   r.ticker,
                   r.contract_symbol,
                   MIN(r.event_time) as entry_time,
                   r.trade_date,
                   r.entry_price,
                   MAX(r.contracts_closed) as qty
            FROM realized_pnl_events r
            WHERE r.position_id IN ({placeholders})
              AND r.position_id NOT IN (SELECT position_id FROM executions WHERE side = 'BOT')
            GROUP BY r.position_id
        )
        ORDER BY entry_time DESC
    """

    # Count for pagination
    total = len(all_pids)
    total_pages = min(25, max(1, (min(total, 500) + per_page - 1) // per_page))
    page = min(page, total_pages) if total_pages > 0 else 1
    offset = (page - 1) * per_page

    entries = conn.execute(
        f"{pos_sql} LIMIT {per_page} OFFSET {offset}", all_pids + all_pids
    ).fetchall()
    entries = [dict(r) for r in entries]

    # Enrich with exit data and P&L
    position_ids = [e["position_id"] for e in entries]
    if not position_ids:
        return {"trades": [], "page": page, "total_pages": total_pages, "total": total}

    placeholders = ",".join("?" * len(position_ids))

    # Aggregate P&L per position
    pnl_rows = conn.execute(
        f"""SELECT position_id,
                   SUM(realized_pnl) as total_pnl,
                   MAX(event_time) as last_exit_time,
                   MAX(exit_price) as exit_price,
                   GROUP_CONCAT(DISTINCT exit_reason) as exit_reasons
            FROM realized_pnl_events
            WHERE position_id IN ({placeholders})
            GROUP BY position_id""",
        position_ids,
    ).fetchall()
    pnl_map = {r["position_id"]: dict(r) for r in pnl_rows}

    # Open positions set
    open_rows = conn.execute(
        f"SELECT position_id FROM positions WHERE position_id IN ({placeholders})",
        position_ids,
    ).fetchall()
    open_set = {r["position_id"] for r in open_rows}

    # Get entry fill_type from orders table
    order_rows = conn.execute(
        f"""SELECT position_id, order_type
            FROM orders
            WHERE position_id IN ({placeholders}) AND order_purpose = 'entry'""",
        position_ids,
    ).fetchall()
    order_type_map = {r["position_id"]: r["order_type"] for r in order_rows}

    # Remaining qty for open positions
    remaining_map = {}
    if open_set:
        open_list = list(open_set)
        open_ph = ",".join("?" * len(open_list))
        rem_rows = conn.execute(
            f"SELECT position_id, contracts FROM positions WHERE position_id IN ({open_ph})",
            open_list,
        ).fetchall()
        remaining_map = {r["position_id"]: r["contracts"] for r in rem_rows}

    trades = []
    for e in entries:
        pid = e["position_id"]
        pnl_data = pnl_map.get(pid, {})
        is_open = pid in open_set
        remaining = remaining_map.get(pid, 0) if is_open else 0

        # Determine status label
        if is_open and not pnl_data:
            status = "open"
        elif is_open and pnl_data:
            status = "partial"
        else:
            status = "closed"

        # Entry fill type from orders
        order_type = order_type_map.get(pid, "")
        fill_type = "limit" if order_type == "LMT" else "market" if order_type == "MKT" else order_type.lower() if order_type else ""

        # Exit info
        exit_reasons = pnl_data.get("exit_reasons", "") or ""
        exit_label = ""
        if "auto_close" in exit_reasons:
            exit_label = "auto_close"
        elif "partial_profit" in exit_reasons and status == "closed":
            exit_label = "partial+close"
        elif "partial_profit" in exit_reasons:
            exit_label = "partial"
        elif exit_reasons:
            exit_label = exit_reasons.split(",")[0]

        trades.append({
            "position_id": pid,
            "ticker": e["ticker"],
            "contract_symbol": e["contract_symbol"],
            "entry_time": e["entry_time"],
            "trade_date": e["trade_date"],
            "entry_price": e["entry_price"],
            "exit_price": pnl_data.get("exit_price"),
            "qty": e["qty"],
            "remaining": remaining,
            "total_pnl": round(pnl_data.get("total_pnl", 0) or 0, 2),
            "status": status,
            "fill_type": fill_type,
            "exit_label": exit_label,
            "last_exit_time": pnl_data.get("last_exit_time"),
        })

    return {"trades": trades, "page": page, "total_pages": total_pages, "total": total}


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
