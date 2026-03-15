"""GET /api/guru — guru signal tracking and comparison with bot execution."""

from fastapi import APIRouter, Query

from app.db import get_db

router = APIRouter(prefix="/api/guru", tags=["guru"])


@router.get("/signals")
async def guru_signals(
    start: str | None = Query(None),
    end: str | None = Query(None),
    ticker: str | None = Query(None),
    action: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
):
    conn = get_db()
    sql = "SELECT * FROM guru_signals WHERE 1=1"
    params: list = []
    if start:
        sql += " AND trade_date >= ?"
        params.append(start)
    if end:
        sql += " AND trade_date <= ?"
        params.append(end)
    if ticker:
        sql += " AND ticker = ?"
        params.append(ticker.upper())
    if action:
        sql += " AND action = ?"
        params.append(action.upper())
    sql += " ORDER BY signal_time DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


@router.get("/stats")
async def guru_stats(
    start: str | None = Query(None),
    end: str | None = Query(None),
    ticker: str | None = Query(None),
):
    conn = get_db()
    sql = "SELECT action, we_executed, our_outcome, ticker FROM guru_signals WHERE 1=1"
    params: list = []
    if start:
        sql += " AND trade_date >= ?"
        params.append(start)
    if end:
        sql += " AND trade_date <= ?"
        params.append(end)
    if ticker:
        sql += " AND ticker = ?"
        params.append(ticker.upper())

    rows = conn.execute(sql, params).fetchall()
    total = len(rows)
    buys = sum(1 for r in rows if r["action"] == "BUY")
    closes = sum(1 for r in rows if r["action"] in ("CLOSE", "SELL", "PARTIAL_CLOSE"))
    executed = sum(1 for r in rows if r["we_executed"])
    rejected = sum(1 for r in rows if r["our_outcome"] == "rejected")

    # Per-ticker
    tickers: dict = {}
    for r in rows:
        t = r["ticker"]
        if t not in tickers:
            tickers[t] = {"total": 0, "buys": 0, "closes": 0, "executed": 0, "rejected": 0}
        tickers[t]["total"] += 1
        if r["action"] == "BUY":
            tickers[t]["buys"] += 1
        if r["action"] in ("CLOSE", "SELL", "PARTIAL_CLOSE"):
            tickers[t]["closes"] += 1
        if r["we_executed"]:
            tickers[t]["executed"] += 1
        if r["our_outcome"] == "rejected":
            tickers[t]["rejected"] += 1

    return {
        "total_signals": total,
        "buys": buys,
        "closes": closes,
        "executed": executed,
        "rejected": rejected,
        "execution_rate": round(executed / total * 100, 1) if total else 0.0,
        "by_ticker": tickers,
    }


@router.get("/comparison")
async def guru_vs_bot(
    start: str | None = Query(None),
    end: str | None = Query(None),
    ticker: str | None = Query(None),
):
    """Side-by-side guru signals vs bot execution by ticker."""
    conn = get_db()

    # Guru side
    g_sql = "SELECT ticker, action, we_executed, our_outcome FROM guru_signals WHERE 1=1"
    g_params: list = []
    if start:
        g_sql += " AND trade_date >= ?"
        g_params.append(start)
    if end:
        g_sql += " AND trade_date <= ?"
        g_params.append(end)
    if ticker:
        g_sql += " AND ticker = ?"
        g_params.append(ticker.upper())

    guru_rows = conn.execute(g_sql, g_params).fetchall()

    guru_by_ticker: dict = {}
    for r in guru_rows:
        t = r["ticker"]
        if t not in guru_by_ticker:
            guru_by_ticker[t] = {"signals": 0, "buys": 0, "closes": 0, "executed": 0, "rejected": 0}
        guru_by_ticker[t]["signals"] += 1
        if r["action"] == "BUY":
            guru_by_ticker[t]["buys"] += 1
        if r["action"] in ("CLOSE", "SELL", "PARTIAL_CLOSE"):
            guru_by_ticker[t]["closes"] += 1
        if r["we_executed"]:
            guru_by_ticker[t]["executed"] += 1
        if r["our_outcome"] == "rejected":
            guru_by_ticker[t]["rejected"] += 1

    # Bot side
    b_sql = "SELECT ticker, realized_pnl FROM realized_pnl_events WHERE 1=1"
    b_params: list = []
    if start:
        b_sql += " AND trade_date >= ?"
        b_params.append(start)
    if end:
        b_sql += " AND trade_date <= ?"
        b_params.append(end)
    if ticker:
        b_sql += " AND ticker = ?"
        b_params.append(ticker.upper())

    bot_rows = conn.execute(b_sql, b_params).fetchall()
    bot_by_ticker: dict = {}
    for r in bot_rows:
        t = r["ticker"]
        if t not in bot_by_ticker:
            bot_by_ticker[t] = {"trades": 0, "pnl": 0.0, "wins": 0, "losses": 0}
        bot_by_ticker[t]["trades"] += 1
        bot_by_ticker[t]["pnl"] += r["realized_pnl"]
        if r["realized_pnl"] > 0:
            bot_by_ticker[t]["wins"] += 1
        elif r["realized_pnl"] < 0:
            bot_by_ticker[t]["losses"] += 1

    # Merge
    all_tickers = sorted(set(guru_by_ticker.keys()) | set(bot_by_ticker.keys()))
    comparison = []
    for t in all_tickers:
        g = guru_by_ticker.get(t, {"signals": 0, "buys": 0, "closes": 0, "executed": 0, "rejected": 0})
        b = bot_by_ticker.get(t, {"trades": 0, "pnl": 0.0, "wins": 0, "losses": 0})
        comparison.append({
            "ticker": t,
            "guru_signals": g["signals"],
            "guru_buys": g["buys"],
            "guru_closes": g["closes"],
            "bot_executed": g["executed"],
            "bot_rejected": g["rejected"],
            "bot_trades": b["trades"],
            "bot_pnl": round(b["pnl"], 2),
            "bot_wins": b["wins"],
            "bot_losses": b["losses"],
            "bot_win_rate": round(b["wins"] / b["trades"] * 100, 1) if b["trades"] else 0.0,
        })

    return {"comparison": comparison}
