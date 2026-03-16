"""
Server-rendered HTML page routes.

All pages require authentication (session cookie).
Data is fetched from SQLite read-only and passed to Jinja2 templates.
"""

from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth.middleware import is_authenticated
from app.db import get_db

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="app/templates")


def _require_auth(request: Request):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=302)
    return None


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return RedirectResponse(url="/dashboard", status_code=302)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    redirect = _require_auth(request)
    if redirect:
        return redirect

    conn = get_db()
    today = date.today().isoformat()

    # Health / system state
    state = conn.execute(
        "SELECT * FROM system_state ORDER BY updated_at DESC LIMIT 1"
    ).fetchone()
    pos_count = conn.execute("SELECT COUNT(*) as cnt FROM positions").fetchone()

    health = {
        "bot_running": state is not None,
        "daily_realized_pnl": state["daily_realized_pnl"] if state else 0.0,
        "daily_unrealized_pnl": state["daily_unrealized_pnl"] if state else 0.0,
        "halted": bool(state["halted"]) if state else False,
        "open_positions": pos_count["cnt"] if pos_count else 0,
    }

    # Open positions
    positions = conn.execute(
        "SELECT * FROM positions ORDER BY opened_at DESC"
    ).fetchall()
    positions = [dict(r) for r in positions]

    # Recent trades with P&L (join executions with pnl_events)
    recent_trades = conn.execute(
        """SELECT e.*, p.realized_pnl as pnl
           FROM executions e
           LEFT JOIN realized_pnl_events p
             ON e.position_id = p.position_id AND e.trade_date = p.trade_date
             AND e.side = 'SLD'
           ORDER BY e.execution_time DESC LIMIT 20"""
    ).fetchall()
    recent_trades = [dict(r) for r in recent_trades]

    # Today's alert stats
    alert_count = conn.execute(
        "SELECT COUNT(*) as c FROM alerts WHERE trade_date = ?", (today,)
    ).fetchone()["c"]
    acted_count = conn.execute(
        "SELECT COUNT(*) as c FROM alerts WHERE trade_date = ? AND outcome = 'filled'", (today,)
    ).fetchone()["c"]
    rejected_count = conn.execute(
        "SELECT COUNT(*) as c FROM alerts WHERE trade_date = ? AND outcome = 'rejected'", (today,)
    ).fetchone()["c"]

    # Win/loss stats (all time for summary cards)
    pnl_rows = conn.execute("SELECT realized_pnl FROM realized_pnl_events").fetchall()
    pnls = [r["realized_pnl"] for r in pnl_rows]
    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p < 0)
    stats = {
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / len(pnls) * 100, 1) if pnls else 0.0,
    }

    # Position ticker summary (e.g. "1 SPX · 1 IWM swing")
    pos_tickers = {}
    for p in positions:
        t = p.get("ticker", "?")
        pos_tickers[t] = pos_tickers.get(t, 0) + 1
    pos_summary = " · ".join(f"{c} {t}" for t, c in pos_tickers.items()) if pos_tickers else "None"

    # Bot uptime — derive from last system_state update
    last_updated = state["updated_at"] if state else None

    # Daily P&L for equity curve
    daily_pnl = [dict(r) for r in conn.execute(
        """SELECT trade_date, SUM(realized_pnl) as total_pnl
           FROM realized_pnl_events
           GROUP BY trade_date ORDER BY trade_date"""
    ).fetchall()]

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "active_page": "dashboard",
        "health": health,
        "positions": positions,
        "recent_trades": recent_trades,
        "alert_count": alert_count,
        "acted_count": acted_count,
        "rejected_count": rejected_count,
        "stats": stats,
        "pos_summary": pos_summary,
        "last_updated": last_updated,
        "daily_pnl": daily_pnl,
    })


@router.get("/trades", response_class=HTMLResponse)
async def trades_page(request: Request):
    redirect = _require_auth(request)
    if redirect:
        return redirect

    conn = get_db()
    filter_date = request.query_params.get("date", "")
    filter_ticker = request.query_params.get("ticker", "")

    sql = "SELECT * FROM realized_pnl_events WHERE 1=1"
    params: list = []

    if filter_date:
        sql += " AND trade_date = ?"
        params.append(filter_date)

    if filter_ticker:
        sql += " AND ticker = ?"
        params.append(filter_ticker.upper())

    sql += " ORDER BY event_time DESC LIMIT 200"
    pnl_events = [dict(r) for r in conn.execute(sql, params).fetchall()]

    # Compute summary
    total_pnl = sum(e["realized_pnl"] for e in pnl_events)
    wins_list = [e["realized_pnl"] for e in pnl_events if e["realized_pnl"] > 0]
    losses_list = [e["realized_pnl"] for e in pnl_events if e["realized_pnl"] < 0]
    total = len(pnl_events)
    win_rate = (len(wins_list) / total * 100) if total > 0 else 0
    expectancy = (total_pnl / total) if total > 0 else 0
    profit_factor = (sum(wins_list) / abs(sum(losses_list))) if losses_list else 0.0

    return templates.TemplateResponse("trades.html", {
        "request": request,
        "active_page": "trades",
        "pnl_events": pnl_events,
        "total_pnl": total_pnl,
        "win_rate": win_rate,
        "expectancy": expectancy,
        "profit_factor": profit_factor,
        "filter_date": filter_date,
        "filter_ticker": filter_ticker,
    })


@router.get("/trade/{position_id}", response_class=HTMLResponse)
async def trade_detail_page(request: Request, position_id: str):
    redirect = _require_auth(request)
    if redirect:
        return redirect

    from app.journal import TradingJournal

    conn = get_db()
    journal = TradingJournal(conn)
    detail = journal.trade_detail(position_id)

    if not detail:
        return templates.TemplateResponse("trade_detail.html", {
            "request": request,
            "active_page": "trades",
            "summary": {"position_id": position_id, "ticker": "?", "contract": "", "trade_date": "", "entry_price": 0, "exit_price": 0, "contracts": 0, "total_pnl": 0, "is_win": False, "is_open": False},
            "position": None,
            "executions": [],
            "orders": [],
            "pnl_events": [],
            "alert": None,
            "guru_signal": None,
            "timeline": [],
        })

    return templates.TemplateResponse("trade_detail.html", {
        "request": request,
        "active_page": "trades",
        **detail,
    })


@router.get("/alerts", response_class=HTMLResponse)
async def alerts_page(request: Request):
    redirect = _require_auth(request)
    if redirect:
        return redirect

    conn = get_db()
    filter_date = request.query_params.get("date", "")
    filter_outcome = request.query_params.get("outcome", "")

    # Use today if no date filter
    target_date = filter_date or date.today().isoformat()

    # Pipeline funnel counts
    total = conn.execute(
        "SELECT COUNT(*) as c FROM alerts WHERE trade_date = ?", (target_date,)
    ).fetchone()["c"]
    parsed = conn.execute(
        "SELECT COUNT(*) as c FROM alerts WHERE trade_date = ? AND parse_result = 'signal'", (target_date,)
    ).fetchone()["c"]
    approved = conn.execute(
        "SELECT COUNT(*) as c FROM alerts WHERE trade_date = ? AND risk_result = 'approved'", (target_date,)
    ).fetchone()["c"]
    filled = conn.execute(
        "SELECT COUNT(*) as c FROM alerts WHERE trade_date = ? AND outcome = 'filled'", (target_date,)
    ).fetchone()["c"]
    rejected = conn.execute(
        "SELECT COUNT(*) as c FROM alerts WHERE trade_date = ? AND outcome = 'rejected'", (target_date,)
    ).fetchone()["c"]

    pipeline = {
        "total": total,
        "parsed": parsed,
        "approved": approved,
        "filled": filled,
        "rejected": rejected,
        "parse_rate": round(parsed / total * 100, 1) if total else 0.0,
        "fill_rate": round(filled / approved * 100, 1) if approved else 0.0,
    }

    # Parse quality diagnostic
    ignored_commentary = conn.execute(
        "SELECT COUNT(*) as c FROM alerts WHERE trade_date = ? AND parse_result = 'non_actionable'", (target_date,)
    ).fetchone()["c"]
    parse_errors = conn.execute(
        "SELECT COUNT(*) as c FROM alerts WHERE trade_date = ? AND parse_result = 'error'", (target_date,)
    ).fetchone()["c"]
    duplicates = conn.execute(
        "SELECT COUNT(*) as c FROM alerts WHERE trade_date = ? AND outcome = 'duplicate'", (target_date,)
    ).fetchone()["c"]
    parse_quality = [
        ("Parsed OK", parsed),
        ("Ignored commentary", ignored_commentary),
        ("Duplicates", duplicates),
        ("Parse failures", parse_errors),
    ]

    # Risk outcome diagnostic
    reason_rows = conn.execute(
        """SELECT risk_reason, COUNT(*) as cnt FROM alerts
           WHERE trade_date = ? AND risk_reason IS NOT NULL
           GROUP BY risk_reason ORDER BY cnt DESC""",
        (target_date,),
    ).fetchall()
    risk_outcome = [("Approved", approved)]
    for r in reason_rows:
        risk_outcome.append((r["risk_reason"], r["cnt"]))

    # Broker outcome diagnostic
    broker_outcome = []
    for status, label in [("filled", "Filled"), ("rejected", "Rejected"), ("duplicate", "Duplicate"), ("ignored", "Ignored"), ("parse_error", "Parse error")]:
        cnt = conn.execute(
            "SELECT COUNT(*) as c FROM alerts WHERE trade_date = ? AND outcome = ?", (target_date, status)
        ).fetchone()["c"]
        if cnt > 0:
            broker_outcome.append((label, cnt))

    # Reject reasons (keep for dedicated section)
    reject_reasons = {r["risk_reason"]: r["cnt"] for r in reason_rows if r["risk_reason"]}

    # System notes (auto-generated from data)
    notes = []
    if total > 0:
        parse_pct = round(parsed / total * 100)
        if parse_pct >= 90:
            notes.append("Parse quality is healthy above 90%")
        elif parse_pct >= 70:
            notes.append(f"Parse quality at {parse_pct}% — some alerts not recognized")
        else:
            notes.append(f"Parse quality low at {parse_pct}% — review parser prompts")

    if reject_reasons:
        top_reason = max(reject_reasons, key=reject_reasons.get)
        notes.append(f"Most skips from: {top_reason}")

    if approved > 0:
        fill_pct = round(filled / approved * 100)
        if fill_pct >= 90:
            notes.append("Broker fill rate is excellent for paper")
        else:
            notes.append(f"Broker fill rate at {fill_pct}% — check order timeouts")

    if duplicates > 0:
        notes.append(f"{duplicates} duplicate alerts caught by dedup filter")

    if parse_errors > 0:
        notes.append(f"{parse_errors} parse failures — check logs for malformed alerts")

    # Alerts list
    sql = "SELECT * FROM alerts WHERE trade_date = ?"
    params: list = [target_date]
    if filter_outcome:
        sql += " AND outcome = ?"
        params.append(filter_outcome)
    sql += " ORDER BY alert_time DESC LIMIT 100"
    alerts = [dict(r) for r in conn.execute(sql, params).fetchall()]

    return templates.TemplateResponse("alerts.html", {
        "request": request,
        "active_page": "alerts",
        "alerts": alerts,
        "pipeline": pipeline,
        "parse_quality": parse_quality,
        "risk_outcome": risk_outcome,
        "broker_outcome": broker_outcome,
        "reject_reasons": reject_reasons,
        "notes": notes,
        "filter_date": filter_date,
        "filter_outcome": filter_outcome,
    })


@router.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request):
    redirect = _require_auth(request)
    if redirect:
        return redirect

    conn = get_db()

    # Stats
    rows = conn.execute("SELECT realized_pnl, ticker FROM realized_pnl_events").fetchall()
    pnls = [r["realized_pnl"] for r in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    # Deeper metrics
    best_trade = max(pnls) if pnls else 0.0
    worst_trade = min(pnls) if pnls else 0.0
    expectancy = round(sum(pnls) / len(pnls), 2) if pnls else 0.0
    profit_factor = round(sum(wins) / abs(sum(losses)), 2) if losses else 0.0
    breakeven_list = [p for p in pnls if p == 0]

    # Max drawdown from cumulative P&L
    max_dd_pct = 0.0
    if pnls:
        cumulative = 0.0
        peak = 0.0
        for p in pnls:
            cumulative += p
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if peak > 0 and (dd / peak) > max_dd_pct:
                max_dd_pct = dd / peak
    max_dd_pct = round(max_dd_pct * 100, 1)

    overall = {
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len(breakeven_list),
        "total": len(pnls),
        "win_rate": round(len(wins) / len(pnls) * 100, 1) if pnls else 0.0,
        "total_pnl": round(sum(pnls), 2),
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "best_trade": round(best_trade, 2),
        "worst_trade": round(worst_trade, 2),
        "expectancy": expectancy,
        "profit_factor": profit_factor,
        "max_dd_pct": max_dd_pct,
        "breakeven_rate": round(len(breakeven_list) / len(pnls) * 100, 1) if pnls else 0.0,
    }

    # Per-ticker
    tickers: dict[str, list] = {}
    for r in rows:
        tickers.setdefault(r["ticker"], []).append(r)

    by_ticker = {}
    for t, rs in tickers.items():
        t_pnls = [r["realized_pnl"] for r in rs]
        t_wins = [p for p in t_pnls if p > 0]
        t_losses = [p for p in t_pnls if p < 0]
        by_ticker[t] = {
            "wins": len(t_wins), "losses": len(t_losses),
            "total": len(t_pnls),
            "win_rate": round(len(t_wins) / len(t_pnls) * 100, 1) if t_pnls else 0,
            "total_pnl": round(sum(t_pnls), 2),
            "avg_win": round(sum(t_wins) / len(t_wins), 2) if t_wins else 0,
            "avg_loss": round(sum(t_losses) / len(t_losses), 2) if t_losses else 0,
        }

    stats = {"overall": overall, "by_ticker": by_ticker}

    # Daily P&L for chart
    daily_pnl = [dict(r) for r in conn.execute(
        """SELECT trade_date, SUM(realized_pnl) as total_pnl, COUNT(*) as trade_count
           FROM realized_pnl_events
           GROUP BY trade_date ORDER BY trade_date"""
    ).fetchall()]

    # Calendar data: {date_str: {pnl, trades}} for current month
    import calendar as cal
    today = date.today()
    cal_year = int(request.query_params.get("cal_year", today.year))
    cal_month = int(request.query_params.get("cal_month", today.month))
    _, days_in_month = cal.monthrange(cal_year, cal_month)
    first_weekday = cal.monthrange(cal_year, cal_month)[0]  # 0=Monday

    # Convert to Sunday-start (0=Sun, 1=Mon, ..., 6=Sat)
    first_weekday_sun = (first_weekday + 1) % 7

    calendar_data = {}
    month_start = f"{cal_year:04d}-{cal_month:02d}-01"
    month_end = f"{cal_year:04d}-{cal_month:02d}-{days_in_month:02d}"
    cal_rows = conn.execute(
        """SELECT trade_date, SUM(realized_pnl) as pnl, COUNT(*) as trades
           FROM realized_pnl_events
           WHERE trade_date >= ? AND trade_date <= ?
           GROUP BY trade_date""",
        (month_start, month_end),
    ).fetchall()
    month_total_pnl = 0.0
    month_total_trades = 0
    for r in cal_rows:
        calendar_data[r["trade_date"]] = {"pnl": round(r["pnl"], 1), "trades": r["trades"]}
        month_total_pnl += r["pnl"]
        month_total_trades += r["trades"]
    month_total_pnl = round(month_total_pnl, 2)

    month_names = ["", "January", "February", "March", "April", "May", "June",
                   "July", "August", "September", "October", "November", "December"]

    return templates.TemplateResponse("analytics.html", {
        "request": request,
        "active_page": "analytics",
        "stats": stats,
        "daily_pnl": daily_pnl,
        "calendar_data": calendar_data,
        "cal_year": cal_year,
        "cal_month": cal_month,
        "cal_month_name": month_names[cal_month],
        "days_in_month": days_in_month,
        "first_weekday_sun": first_weekday_sun,
        "today_str": today.isoformat(),
        "month_total_pnl": month_total_pnl,
        "month_total_trades": month_total_trades,
    })


@router.get("/guru", response_class=HTMLResponse)
async def guru_page(request: Request):
    redirect = _require_auth(request)
    if redirect:
        return redirect

    conn = get_db()
    filter_start = request.query_params.get("start", "")
    filter_end = request.query_params.get("end", "")
    filter_ticker = request.query_params.get("ticker", "")

    # Get available tickers for dropdown
    try:
        ticker_rows = conn.execute(
            "SELECT DISTINCT ticker FROM guru_signals ORDER BY ticker"
        ).fetchall()
        available_tickers = [r["ticker"] for r in ticker_rows]
    except Exception:
        available_tickers = []

    # Guru stats
    g_sql = "SELECT action, we_executed, our_outcome, ticker FROM guru_signals WHERE 1=1"
    g_params: list = []
    if filter_start:
        g_sql += " AND trade_date >= ?"
        g_params.append(filter_start)
    if filter_end:
        g_sql += " AND trade_date <= ?"
        g_params.append(filter_end)
    if filter_ticker:
        g_sql += " AND ticker = ?"
        g_params.append(filter_ticker)

    rows = conn.execute(g_sql, g_params).fetchall()
    total = len(rows)
    buys = sum(1 for r in rows if r["action"] == "BUY")
    closes = sum(1 for r in rows if r["action"] in ("CLOSE", "SELL", "PARTIAL_CLOSE"))
    executed = sum(1 for r in rows if r["we_executed"])
    rejected = sum(1 for r in rows if r["our_outcome"] == "rejected")

    missed = rejected  # signals guru sent but bot didn't execute

    guru_stats = {
        "total_signals": total,
        "buys": buys,
        "closes": closes,
        "executed": executed,
        "rejected": rejected,
        "execution_rate": round(executed / total * 100, 1) if total else 0.0,
    }

    # Reject reason breakdown for gap analysis
    gap_reasons: dict = {}
    for r in rows:
        if r["our_outcome"] == "rejected":
            # We don't have reject reason in this query, so we'll get from guru_signals
            pass
    gap_rows = conn.execute(
        "SELECT our_reject_reason, COUNT(*) as cnt FROM guru_signals WHERE our_outcome = 'rejected' AND our_reject_reason IS NOT NULL"
        + (" AND trade_date >= ?" if filter_start else "")
        + (" AND trade_date <= ?" if filter_end else "")
        + (" AND ticker = ?" if filter_ticker else "")
        + " GROUP BY our_reject_reason ORDER BY cnt DESC",
        [p for p in [filter_start, filter_end, filter_ticker] if p],
    ).fetchall()
    gap_reasons = [(r["our_reject_reason"], r["cnt"]) for r in gap_rows]

    # Per-ticker guru data
    guru_by_ticker: dict = {}
    for r in rows:
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

    # Bot P&L by ticker
    b_sql = "SELECT ticker, realized_pnl FROM realized_pnl_events WHERE 1=1"
    b_params: list = []
    if filter_start:
        b_sql += " AND trade_date >= ?"
        b_params.append(filter_start)
    if filter_end:
        b_sql += " AND trade_date <= ?"
        b_params.append(filter_end)
    if filter_ticker:
        b_sql += " AND ticker = ?"
        b_params.append(filter_ticker)

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

    # Merge comparison
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

    # Recent signals
    s_sql = "SELECT * FROM guru_signals WHERE 1=1"
    s_params: list = []
    if filter_start:
        s_sql += " AND trade_date >= ?"
        s_params.append(filter_start)
    if filter_end:
        s_sql += " AND trade_date <= ?"
        s_params.append(filter_end)
    if filter_ticker:
        s_sql += " AND ticker = ?"
        s_params.append(filter_ticker)
    s_sql += " ORDER BY signal_time DESC LIMIT 100"

    signals = [dict(r) for r in conn.execute(s_sql, s_params).fetchall()]

    # Bot totals for execution quality panel
    bot_total_pnl = sum(b["pnl"] for b in bot_by_ticker.values())
    bot_total_trades = sum(b["trades"] for b in bot_by_ticker.values())
    bot_total_wins = sum(b["wins"] for b in bot_by_ticker.values())
    fill_rate = round(executed / total * 100, 1) if total else 0.0

    return templates.TemplateResponse("guru.html", {
        "request": request,
        "active_page": "guru",
        "guru_stats": guru_stats,
        "comparison": comparison,
        "signals": signals,
        "available_tickers": available_tickers,
        "filter_start": filter_start,
        "filter_end": filter_end,
        "filter_ticker": filter_ticker,
        "bot_total_pnl": round(bot_total_pnl, 2),
        "bot_total_trades": bot_total_trades,
        "fill_rate": fill_rate,
        "gap_reasons": gap_reasons,
        "missed": missed,
    })


@router.get("/health", response_class=HTMLResponse)
async def health_page(request: Request):
    redirect = _require_auth(request)
    if redirect:
        return redirect

    conn = get_db()
    today = date.today().isoformat()

    state = conn.execute(
        "SELECT * FROM system_state ORDER BY updated_at DESC LIMIT 1"
    ).fetchone()
    pos_count = conn.execute("SELECT COUNT(*) as cnt FROM positions").fetchone()

    health = {
        "bot_running": state is not None,
        "daily_realized_pnl": state["daily_realized_pnl"] if state else 0.0,
        "daily_unrealized_pnl": state["daily_unrealized_pnl"] if state else 0.0,
        "halted": bool(state["halted"]) if state else False,
        "open_positions": pos_count["cnt"] if pos_count else 0,
        "trade_date": today,
        "last_updated": state["updated_at"] if state else None,
    }

    # Risk used % (realized loss / max loss limit)
    max_loss = 1000.0
    risk_pct = abs(health["daily_realized_pnl"]) / max_loss * 100 if health["daily_realized_pnl"] < 0 else 0.0

    # Auto-close stats for today
    auto_close_count = conn.execute(
        "SELECT COUNT(*) as c FROM realized_pnl_events WHERE trade_date = ? AND event_type = 'AUTO_CLOSE'",
        (today,),
    ).fetchone()["c"]

    # Same-day expiry positions (candidates for auto-close)
    same_day_positions = conn.execute(
        "SELECT * FROM positions WHERE expiry_date = ? ORDER BY opened_at",
        (today,),
    ).fetchall()
    same_day_positions = [dict(r) for r in same_day_positions]

    # Time until market close (3:55 PM ET auto-close)
    from datetime import datetime
    import pytz
    now_et = datetime.now(tz=pytz.timezone("America/New_York"))
    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    auto_close_time = now_et.replace(hour=15, minute=55, second=0, microsecond=0)
    market_close_time = now_et.replace(hour=16, minute=15, second=0, microsecond=0)

    is_weekend = now_et.weekday() >= 5
    is_market_hours = market_open <= now_et <= market_close_time and not is_weekend
    auto_close_triggered = now_et >= auto_close_time and not is_weekend

    if is_weekend:
        close_label = "Weekend"
        close_color = "muted"
    elif now_et < market_open:
        close_label = "Pre-market"
        close_color = "muted"
    elif now_et >= market_close_time:
        close_label = "Closed"
        close_color = "muted"
    elif auto_close_triggered:
        close_label = "Done"
        close_color = "positive"
    else:
        total_mins = max(0, int((auto_close_time - now_et).total_seconds() / 60))
        hours = total_mins // 60
        mins = total_mins % 60
        if hours > 0:
            close_label = f"{hours}h {mins}m"
        else:
            close_label = f"{mins}m"
        # Color: green > 2h, yellow < 1h, red < 15m
        if total_mins <= 15:
            close_color = "negative"
        elif total_mins <= 60:
            close_color = "warning"
        else:
            close_color = "positive"

    return templates.TemplateResponse("health.html", {
        "request": request,
        "active_page": "health",
        "health": health,
        "risk_pct": risk_pct,
        "auto_close_count": auto_close_count,
        "same_day_positions": same_day_positions,
        "close_label": close_label,
        "close_color": close_color,
        "auto_close_triggered": auto_close_triggered,
        "is_market_hours": is_market_hours,
    })
