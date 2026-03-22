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
        "bot_running": bool(state["gateway_connected"]) if state and "gateway_connected" in state.keys() else state is not None,
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

    # Recent trades — one row per position (grouped)
    recent_entries = conn.execute(
        """SELECT e.position_id, e.ticker, e.contract_symbol,
                  MIN(e.trade_date) as trade_date,
                  MIN(e.execution_time) as entry_time,
                  MAX(CASE WHEN e.side = 'BOT' THEN e.fill_price END) as entry_price,
                  SUM(CASE WHEN e.side = 'BOT' THEN e.contracts ELSE 0 END) as qty
           FROM executions e
           GROUP BY e.position_id
           ORDER BY MIN(e.execution_time) DESC
           LIMIT 15"""
    ).fetchall()
    recent_entries = [dict(r) for r in recent_entries]

    # Enrich with P&L and status
    recent_trades = []
    for entry in recent_entries:
        pid = entry["position_id"]
        pnl_row = conn.execute(
            "SELECT SUM(realized_pnl) as total_pnl, MAX(exit_price) as exit_price FROM realized_pnl_events WHERE position_id = ?",
            (pid,),
        ).fetchone()
        is_open = conn.execute(
            "SELECT 1 FROM positions WHERE position_id = ?", (pid,)
        ).fetchone() is not None

        total_pnl = round((pnl_row["total_pnl"] or 0), 2) if pnl_row else 0
        exit_price = pnl_row["exit_price"] if pnl_row else None
        has_exits = pnl_row and pnl_row["total_pnl"] is not None

        status = "open" if is_open and not has_exits else "partial" if is_open else "closed"
        entry["entry_price"] = entry.get("entry_price") or 0.0
        entry["qty"] = entry.get("qty") or 0
        recent_trades.append({
            **entry,
            "total_pnl": total_pnl,
            "exit_price": exit_price,
            "status": status,
        })

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

    # Stock positions (from assignments, etc.)
    try:
        stock_positions = [dict(r) for r in conn.execute(
            "SELECT * FROM stock_positions WHERE closed = 0 ORDER BY symbol"
        ).fetchall()]
    except Exception:
        stock_positions = []  # table may not exist yet

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
        "stock_positions": stock_positions,
    })


@router.get("/trades", response_class=HTMLResponse)
async def trades_page(request: Request):
    redirect = _require_auth(request)
    if redirect:
        return redirect

    conn = get_db()
    filter_start = request.query_params.get("start", "")
    filter_end = request.query_params.get("end", "")
    filter_ticker = request.query_params.get("ticker", "")

    # Default to latest trading day if no filters (check both pnl_events and executions)
    if not filter_start and not filter_end:
        latest = conn.execute(
            """SELECT MAX(d) as d FROM (
                SELECT MAX(trade_date) as d FROM realized_pnl_events
                UNION ALL
                SELECT MAX(trade_date) as d FROM executions
            )"""
        ).fetchone()
        if latest and latest["d"]:
            filter_start = latest["d"]
            filter_end = latest["d"]

    # All P&L events for summary cards
    all_sql = "SELECT * FROM realized_pnl_events WHERE 1=1"
    all_params: list = []
    if filter_start:
        all_sql += " AND trade_date >= ?"
        all_params.append(filter_start)
    if filter_end:
        all_sql += " AND trade_date <= ?"
        all_params.append(filter_end)
    if filter_ticker:
        all_sql += " AND ticker = ?"
        all_params.append(filter_ticker.upper())
    all_sql += " ORDER BY event_time DESC"
    all_events = [dict(r) for r in conn.execute(all_sql, all_params).fetchall()]

    # Summary stats
    total_pnl = sum(e["realized_pnl"] for e in all_events)
    wins_list = [e["realized_pnl"] for e in all_events if e["realized_pnl"] > 0]
    losses_list = [e["realized_pnl"] for e in all_events if e["realized_pnl"] < 0]
    total = len(all_events)
    win_rate = (len(wins_list) / total * 100) if total > 0 else 0
    expectancy = (total_pnl / total) if total > 0 else 0
    profit_factor = (sum(wins_list) / abs(sum(losses_list))) if losses_list else 0.0

    # Biggest winner and loser
    biggest_winner = max(all_events, key=lambda e: e["realized_pnl"]) if all_events else None
    biggest_loser = min(all_events, key=lambda e: e["realized_pnl"]) if all_events else None

    # Time-of-day breakdown — classify by ENTRY time, not exit time
    # Open: 9:30-10:00, Patience: 10:00-15:00, Lotto: 15:00-16:15
    # Get entry times from executions (BOT side) for each position
    time_buckets = {"open": {"total": 0, "wins": 0, "losses": 0},
                    "patience": {"total": 0, "wins": 0, "losses": 0},
                    "lotto": {"total": 0, "wins": 0, "losses": 0}}

    # Build entry time map from executions
    entry_sql = "SELECT position_id, MIN(execution_time) as entry_time FROM executions WHERE side = 'BOT'"
    entry_params: list = []
    if filter_start:
        entry_sql += " AND trade_date >= ?"
        entry_params.append(filter_start)
    if filter_end:
        entry_sql += " AND trade_date <= ?"
        entry_params.append(filter_end)
    if filter_ticker:
        entry_sql += " AND ticker = ?"
        entry_params.append(filter_ticker.upper())
    entry_sql += " GROUP BY position_id"
    entry_times = {r["position_id"]: r["entry_time"] for r in conn.execute(entry_sql, entry_params).fetchall()}

    for e in all_events:
        # Use entry time for classification, fall back to event_time
        pos_id = e.get("position_id", "")
        event_time = entry_times.get(pos_id, e.get("event_time", ""))
        # Extract hour:minute from ISO timestamp
        try:
            if "T" in event_time:
                time_part = event_time.split("T")[1][:5]
            else:
                time_part = event_time[11:16] if len(event_time) > 16 else ""
            h, m = int(time_part[:2]), int(time_part[3:5])
            mins = h * 60 + m
        except (ValueError, IndexError):
            continue

        if mins < 600:  # before 10:00 AM
            bucket = "open"
        elif mins >= 900:  # after 3:00 PM
            bucket = "lotto"
        else:
            bucket = "patience"

        time_buckets[bucket]["total"] += 1
        if e["realized_pnl"] > 0:
            time_buckets[bucket]["wins"] += 1
        elif e["realized_pnl"] < 0:
            time_buckets[bucket]["losses"] += 1

    # Also count open positions (entries without exits) in time buckets
    closed_position_ids = {e.get("position_id") for e in all_events}
    for pos_id, etime in entry_times.items():
        if pos_id in closed_position_ids:
            continue  # already counted above
        try:
            if "T" in etime:
                tp = etime.split("T")[1][:5]
            else:
                tp = etime[11:16] if len(etime) > 16 else ""
            h, m = int(tp[:2]), int(tp[3:5])
            mins = h * 60 + m
        except (ValueError, IndexError):
            continue
        if mins < 600:
            time_buckets["open"]["total"] += 1
        elif mins >= 900:
            time_buckets["lotto"]["total"] += 1
        else:
            time_buckets["patience"]["total"] += 1

    return templates.TemplateResponse("trades.html", {
        "request": request,
        "active_page": "trades",
        "total_pnl": total_pnl,
        "win_rate": win_rate,
        "expectancy": expectancy,
        "profit_factor": profit_factor,
        "biggest_winner": biggest_winner,
        "biggest_loser": biggest_loser,
        "time_buckets": time_buckets,
        "total_trades": total,
        "filter_start": filter_start,
        "filter_end": filter_end,
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
    filter_start = request.query_params.get("start", "")
    filter_end = request.query_params.get("end", "")
    filter_outcome = request.query_params.get("outcome", "")

    # Default to latest day with alerts, or today
    if not filter_start and not filter_end:
        latest = conn.execute("SELECT MAX(trade_date) as d FROM alerts").fetchone()
        if latest and latest["d"]:
            filter_start = latest["d"]
            filter_end = latest["d"]
        else:
            filter_start = date.today().isoformat()
            filter_end = filter_start

    # Build date clause
    date_clause = ""
    date_params: list = []
    if filter_start:
        date_clause += " AND trade_date >= ?"
        date_params.append(filter_start)
    if filter_end:
        date_clause += " AND trade_date <= ?"
        date_params.append(filter_end)

    def count_alerts(extra_clause: str = "", extra_params: list | None = None) -> int:
        sql = f"SELECT COUNT(*) as c FROM alerts WHERE 1=1{date_clause}{extra_clause}"
        return conn.execute(sql, date_params + (extra_params or [])).fetchone()["c"]

    # Pipeline funnel counts
    total = count_alerts()
    parsed = count_alerts(" AND parse_result = 'signal'")
    approved = count_alerts(" AND risk_result = 'approved'")
    filled = count_alerts(" AND outcome = 'filled'")
    rejected = count_alerts(" AND outcome = 'rejected'")

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
    ignored_commentary = count_alerts(" AND parse_result = 'non_actionable'")
    parse_errors = count_alerts(" AND parse_result = 'error'")
    duplicates = count_alerts(" AND outcome = 'duplicate'")
    parse_quality = [
        ("Parsed OK", parsed),
        ("Ignored commentary", ignored_commentary),
        ("Duplicates", duplicates),
        ("Parse failures", parse_errors),
    ]

    # Risk outcome diagnostic
    reason_rows = conn.execute(
        f"""SELECT risk_reason, COUNT(*) as cnt FROM alerts
           WHERE 1=1{date_clause} AND risk_reason IS NOT NULL
           GROUP BY risk_reason ORDER BY cnt DESC""",
        date_params,
    ).fetchall()
    risk_outcome = [("Approved", approved)]
    for r in reason_rows:
        risk_outcome.append((r["risk_reason"], r["cnt"]))

    # Broker outcome diagnostic
    broker_outcome = []
    for status, label in [("filled", "Filled"), ("rejected", "Rejected"), ("duplicate", "Duplicate"), ("ignored", "Ignored"), ("parse_error", "Parse error")]:
        cnt = count_alerts(" AND outcome = ?", [status])
        if cnt > 0:
            broker_outcome.append((label, cnt))

    # Reject reasons
    reject_reasons = {r["risk_reason"]: r["cnt"] for r in reason_rows if r["risk_reason"]}

    # Parser latency metrics (columns added in schema v6 — graceful fallback)
    parser_metrics = {}
    parser_chart_data = []  # [{time, ms, engine}, ...] for bar chart
    try:
        latency_rows = conn.execute(
            f"""SELECT alert_time, parse_latency_ms, parser_engine FROM alerts
               WHERE 1=1{date_clause} AND parse_latency_ms IS NOT NULL
               ORDER BY alert_time""",
            date_params,
        ).fetchall()

        if latency_rows:
            latencies = sorted([r["parse_latency_ms"] for r in latency_rows])
            n = len(latencies)
            parser_metrics = {
                "count": n,
                "avg": round(sum(latencies) / n),
                "max": max(latencies),
                "p95": latencies[min(int(n * 0.95), n - 1)],
                "p99": latencies[min(int(n * 0.99), n - 1)],
            }
            engine_counts = {}
            for r in latency_rows:
                eng = r["parser_engine"] or "unknown"
                engine_counts[eng] = engine_counts.get(eng, 0) + 1
                # Chart data point
                t = r["alert_time"] or ""
                day = t[:10]  # YYYY-MM-DD
                hhmm = t[11:16] if len(t) >= 16 else ""  # HH:MM
                parser_chart_data.append({
                    "day": day,
                    "hhmm": hhmm,
                    "ms": r["parse_latency_ms"],
                    "engine": eng,
                })
            parser_metrics["engines"] = engine_counts
    except Exception:
        pass  # columns don't exist yet (pre-v6 schema)

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

    # Alert audit loaded via AJAX (/api/alerts)

    return templates.TemplateResponse("alerts.html", {
        "request": request,
        "active_page": "alerts",
        "pipeline": pipeline,
        "parse_quality": parse_quality,
        "risk_outcome": risk_outcome,
        "broker_outcome": broker_outcome,
        "reject_reasons": reject_reasons,
        "parser_metrics": parser_metrics,
        "parser_chart_data": parser_chart_data,
        "notes": notes,
        "filter_start": filter_start,
        "filter_end": filter_end,
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
    from datetime import datetime
    import pytz
    now_et = datetime.now(tz=pytz.timezone("America/New_York"))
    is_market_hours = 5 <= now_et.weekday() < 5 and now_et.hour >= 9

    # Available tickers for filter
    try:
        available_tickers = [r["ticker"] for r in conn.execute(
            "SELECT DISTINCT ticker FROM guru_signals ORDER BY ticker").fetchall()]
    except Exception:
        available_tickers = []

    # ── All guru signals (filtered) ──
    g_sql = "SELECT action, we_executed, our_outcome, our_reject_reason, ticker, entry_price, exit_price, strike, \"right\" FROM guru_signals WHERE 1=1"
    g_params: list = []
    if filter_start:
        g_sql += " AND trade_date >= ?"; g_params.append(filter_start)
    if filter_end:
        g_sql += " AND trade_date <= ?"; g_params.append(filter_end)
    if filter_ticker:
        g_sql += " AND ticker = ?"; g_params.append(filter_ticker)
    rows = conn.execute(g_sql, g_params).fetchall()

    total = len(rows)
    buys = sum(1 for r in rows if r["action"] == "BUY")
    closes = sum(1 for r in rows if r["action"] in ("CLOSE", "SELL", "PARTIAL_CLOSE"))
    executed = sum(1 for r in rows if r["we_executed"])
    rejected = sum(1 for r in rows if r["our_outcome"] == "rejected")
    skipped = sum(1 for r in rows if r["our_outcome"] == "skipped")
    filled_count = sum(1 for r in rows if r["our_outcome"] == "filled")

    # Parsed = non-duplicate, non-skipped signals (i.e. the parser returned actionable or rejected)
    parsed = sum(1 for r in rows if r["our_outcome"] not in ("skipped",))
    eligible = parsed - rejected  # passed risk gates

    # ── Bot P&L by ticker ──
    b_sql = "SELECT ticker, realized_pnl FROM realized_pnl_events WHERE 1=1"
    b_params: list = []
    if filter_start:
        b_sql += " AND trade_date >= ?"; b_params.append(filter_start)
    if filter_end:
        b_sql += " AND trade_date <= ?"; b_params.append(filter_end)
    if filter_ticker:
        b_sql += " AND ticker = ?"; b_params.append(filter_ticker)
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

    bot_total_pnl = sum(b["pnl"] for b in bot_by_ticker.values())
    bot_total_trades = sum(b["trades"] for b in bot_by_ticker.values())
    bot_total_wins = sum(b["wins"] for b in bot_by_ticker.values())
    bot_win_rate = round(bot_total_wins / bot_total_trades * 100, 1) if bot_total_trades else 0.0
    follow_rate = round(executed / total * 100, 1) if total else 0.0
    reject_rate = round(rejected / total * 100, 1) if total else 0.0

    # ── Funnel stages ──
    closed_count = sum(b["trades"] for b in bot_by_ticker.values())
    funnel = [
        {"label": "Signals", "value": total, "color": "#3498db"},
        {"label": "Parsed", "value": parsed, "color": "#2ecc71"},
        {"label": "Eligible", "value": eligible, "color": "#f39c12"},
        {"label": "Executed", "value": executed, "color": "#2ecc71"},
        {"label": "Filled", "value": filled_count or executed, "color": "#3498db"},
        {"label": "Closed", "value": closed_count, "color": "#bc8cff"},
        {"label": "Rejected", "value": rejected, "color": "#e74c3c"},
    ]

    # ── Rejection reasons with type/impact badges ──
    gap_rows = conn.execute(
        "SELECT our_reject_reason, COUNT(*) as cnt FROM guru_signals WHERE our_outcome = 'rejected' AND our_reject_reason IS NOT NULL"
        + (" AND trade_date >= ?" if filter_start else "")
        + (" AND trade_date <= ?" if filter_end else "")
        + (" AND ticker = ?" if filter_ticker else "")
        + " GROUP BY our_reject_reason ORDER BY cnt DESC",
        [p for p in [filter_start, filter_end, filter_ticker] if p],
    ).fetchall()

    rejection_reasons = []
    for r in gap_rows:
        reason = r["our_reject_reason"]
        cnt = r["cnt"]
        # Classify type and impact
        reason_lower = reason.lower()
        if "halt" in reason_lower:
            rtype, impact = "Risk", "Protected"
        elif "max" in reason_lower or "position" in reason_lower or "concurrent" in reason_lower:
            rtype, impact = "Risk", "Neutral"
        elif "duplicate" in reason_lower:
            rtype, impact = "Duplicate", "Neutral"
        elif "price" in reason_lower or "cap" in reason_lower or "entry" in reason_lower:
            rtype, impact = "Price", "Mixed"
        elif "afternoon" in reason_lower or "session" in reason_lower or "lotto" in reason_lower or "morning" in reason_lower:
            rtype, impact = "Session", "Protected"
        elif "0dte" in reason_lower or "cutoff" in reason_lower:
            rtype, impact = "Session", "Protected"
        else:
            rtype, impact = "Other", "Neutral"
        rejection_reasons.append({"reason": reason, "count": cnt, "type": rtype, "impact": impact})

    # ── Miss Quality Analysis ──
    # Pair guru BUY→CLOSE to estimate what bot missed
    missed_winners = 0
    avoided_losers = 0
    neutral_misses = 0
    largest_missed_winner = {"ticker": "—", "pnl": 0}
    largest_avoided_loser = {"ticker": "—", "pnl": 0}

    guru_open: dict = {}
    for r in rows:
        action = (r["action"] or "").upper()
        ticker = r["ticker"]
        key = (ticker, r["strike"], r["right"])

        if action == "BUY" and r["entry_price"] and not r["we_executed"]:
            guru_open[key] = dict(r)
        elif action in ("CLOSE", "SELL", "PARTIAL_CLOSE") and key in guru_open:
            entry = guru_open.pop(key)
            exit_p = r["exit_price"] or r["entry_price"]
            if exit_p and entry.get("entry_price"):
                pnl = round((exit_p - entry["entry_price"]) * 100, 2)
                if pnl > 0:
                    missed_winners += 1
                    if pnl > largest_missed_winner["pnl"]:
                        largest_missed_winner = {"ticker": ticker, "pnl": pnl}
                elif pnl < 0:
                    avoided_losers += 1
                    if pnl < largest_avoided_loser["pnl"]:
                        largest_avoided_loser = {"ticker": ticker, "pnl": pnl}
                else:
                    neutral_misses += 1

    missed_opportunity_pnl = largest_missed_winner["pnl"] - abs(largest_avoided_loser["pnl"]) if missed_winners > 0 else 0

    # ── Operator Takeaway ──
    takeaways = []
    takeaways.append({"title": "Bot followed", "detail": f"{follow_rate:.1f}% of guru flow"})
    # Find biggest drag
    worst_ticker = max(bot_by_ticker.items(), key=lambda x: abs(x[1]["pnl"]), default=("—", {"pnl": 0}))
    if worst_ticker[1]["pnl"] < 0:
        takeaways.append({"title": "Main drag", "detail": f"{worst_ticker[0]} concentration and weak fills"})
    # Risk rules assessment
    if avoided_losers > missed_winners:
        takeaways.append({"title": "Risk rules", "detail": "blocked several likely losers"})
    elif avoided_losers > 0:
        takeaways.append({"title": "Risk rules", "detail": f"avoided {avoided_losers} losers, missed {missed_winners} winners"})
    # Best ticker
    best_ticker = max(bot_by_ticker.items(), key=lambda x: x[1]["pnl"], default=("—", {"pnl": 0}))
    if best_ticker[1]["pnl"] > 0:
        takeaways.append({"title": "Best covered", "detail": best_ticker[0]})
    # Action
    if worst_ticker[1]["pnl"] < -100:
        takeaways.append({"title": "Action", "detail": f"review {worst_ticker[0]} gating vs execution quality"})

    # ── Quality Verdict ──
    if bot_total_pnl > 0:
        verdict = "Profitable"
        verdict_detail = "risk rules + execution working"
    elif avoided_losers > missed_winners:
        verdict = "Risk Protected"
        verdict_detail = "rules saved more than they cost"
    elif worst_ticker[1]["pnl"] < -200:
        verdict = f"{worst_ticker[0]} Drag"
        verdict_detail = f"risk rules helped\nbut {worst_ticker[0]} drove losses"
    else:
        verdict = "Under Review"
        verdict_detail = "insufficient data for verdict"

    # ── Per-ticker comparison table ──
    guru_by_ticker: dict = {}
    for r in rows:
        t = r["ticker"]
        if t not in guru_by_ticker:
            guru_by_ticker[t] = {"signals": 0, "buys": 0, "closes": 0, "executed": 0, "rejected": 0}
        guru_by_ticker[t]["signals"] += 1
        if r["action"] == "BUY": guru_by_ticker[t]["buys"] += 1
        if r["action"] in ("CLOSE", "SELL", "PARTIAL_CLOSE"): guru_by_ticker[t]["closes"] += 1
        if r["we_executed"]: guru_by_ticker[t]["executed"] += 1
        if r["our_outcome"] == "rejected": guru_by_ticker[t]["rejected"] += 1

    all_tickers = sorted(set(guru_by_ticker.keys()) | set(bot_by_ticker.keys()))
    comparison = []
    for t in all_tickers:
        g = guru_by_ticker.get(t, {"signals": 0, "executed": 0, "rejected": 0})
        b = bot_by_ticker.get(t, {"trades": 0, "pnl": 0.0, "wins": 0, "losses": 0})
        elig = g["executed"] + g["rejected"]  # approximate eligible
        frate = round(g["executed"] / g["signals"] * 100, 0) if g["signals"] else 0
        wr = round(b["wins"] / b["trades"] * 100, 1) if b["trades"] else 0.0
        # Verdict per ticker
        if b["pnl"] < -200:
            tv = "Main loss driver"
        elif b["pnl"] > 50:
            tv = "Decent coverage"
        elif b["trades"] <= 1:
            tv = "Low sample"
        elif wr == 0 and b["trades"] > 2:
            tv = "Execution okay" if b["pnl"] > -50 else "Needs review"
        else:
            tv = "No signal value" if b["trades"] == 0 else "Tracking"
        comparison.append({
            "ticker": t, "guru": g["signals"], "eligible": elig,
            "executed": g["executed"], "rejected": g["rejected"],
            "follow_rate": frate, "trades": b["trades"], "win_rate": wr,
            "bot_pnl": round(b["pnl"], 2), "verdict": tv,
        })

    # Chart data
    chart_tickers = [c["ticker"] for c in comparison if c["guru"] > 0]
    chart_guru = [c["guru"] for c in comparison if c["guru"] > 0]
    chart_executed = [c["executed"] for c in comparison if c["guru"] > 0]
    chart_rejected = [c["rejected"] for c in comparison if c["guru"] > 0]

    pnl_chart = sorted(
        [{"ticker": t, "pnl": round(b["pnl"], 0)} for t, b in bot_by_ticker.items()],
        key=lambda x: x["pnl"], reverse=True
    )

    # ── Unsupported tickers ──
    skipped_rows = conn.execute("""
        SELECT * FROM guru_signals
        WHERE our_outcome = 'skipped' AND our_reject_reason LIKE '%unsupported ticker%'
        ORDER BY ticker, signal_time
    """).fetchall()
    unsupported_tickers: dict = {}
    unsup_open: dict = {}
    for r in skipped_rows:
        t = r["ticker"]
        if t not in unsupported_tickers:
            unsupported_tickers[t] = {"ticker": t, "total_signals": 0, "entries": 0, "exits": 0, "wins": 0, "losses": 0, "total_pnl": 0.0}
        unsupported_tickers[t]["total_signals"] += 1
        action = (r["action"] or "").upper()
        key = (t, r["strike"], r["right"])
        if action == "BUY" and r["entry_price"]:
            unsupported_tickers[t]["entries"] += 1
            unsup_open[key] = r
        elif action in ("CLOSE", "SELL") and key in unsup_open:
            entry = unsup_open.pop(key)
            unsupported_tickers[t]["exits"] += 1
            if r["exit_price"] and entry["entry_price"]:
                pnl = round((r["exit_price"] - entry["entry_price"]) * 100, 2)
                unsupported_tickers[t]["total_pnl"] += pnl
                if pnl > 0: unsupported_tickers[t]["wins"] += 1
                else: unsupported_tickers[t]["losses"] += 1
    unsupported_list = []
    for t, data in sorted(unsupported_tickers.items()):
        closed = data["wins"] + data["losses"]
        data["closed_trades"] = closed
        data["win_rate"] = round(data["wins"] / closed * 100, 1) if closed else 0.0
        data["total_pnl"] = round(data["total_pnl"], 2)
        data["open_entries"] = data["entries"] - data["exits"]
        unsupported_list.append(data)

    return templates.TemplateResponse("guru.html", {
        "request": request,
        "active_page": "guru",
        "is_market_hours": is_market_hours,
        # Filters
        "available_tickers": available_tickers,
        "filter_start": filter_start,
        "filter_end": filter_end,
        "filter_ticker": filter_ticker,
        # Row 1 KPIs
        "total_signals": total,
        "buys": buys,
        "closes": closes,
        "follow_rate": follow_rate,
        "executed": executed,
        "reject_rate": reject_rate,
        "rejected": rejected,
        "missed_winners": missed_winners,
        "avoided_losers": avoided_losers,
        "missed_opportunity_pnl": missed_opportunity_pnl,
        "bot_total_pnl": round(bot_total_pnl, 2),
        "bot_total_trades": bot_total_trades,
        "bot_win_rate": bot_win_rate,
        "verdict": verdict,
        "verdict_detail": verdict_detail,
        # Row 2 funnel
        "funnel": funnel,
        # Row 3 diagnostics
        "rejection_reasons": rejection_reasons,
        "neutral_misses": neutral_misses,
        "largest_missed_winner": largest_missed_winner,
        "largest_avoided_loser": largest_avoided_loser,
        "takeaways": takeaways,
        # Row 4 table
        "comparison": comparison,
        # Row 5 charts
        "chart_tickers": chart_tickers,
        "chart_guru": chart_guru,
        "chart_executed": chart_executed,
        "chart_rejected": chart_rejected,
        "pnl_chart": pnl_chart,
        # Unsupported
        "unsupported_tickers": unsupported_list,
    })


@router.get("/health", response_class=HTMLResponse)
async def health_page(request: Request):
    redirect = _require_auth(request)
    if redirect:
        return redirect

    conn = get_db()
    today = date.today().isoformat()
    from datetime import datetime
    import pytz
    ET = pytz.timezone("America/New_York")
    now_et = datetime.now(tz=ET)

    # ── System state ──
    state = conn.execute(
        "SELECT * FROM system_state ORDER BY updated_at DESC LIMIT 1"
    ).fetchone()

    gateway_connected = bool(state["gateway_connected"]) if state and "gateway_connected" in state.keys() else state is not None
    daily_realized_pnl = state["daily_realized_pnl"] if state else 0.0
    daily_unrealized_pnl = state["daily_unrealized_pnl"] if state else 0.0
    halted = bool(state["halted"]) if state else False
    last_updated = state["updated_at"] if state else None

    # ── Open positions ──
    open_positions = conn.execute("SELECT * FROM positions ORDER BY opened_at").fetchall()
    open_positions = [dict(r) for r in open_positions]

    # ── Market hours logic ──
    is_weekend = now_et.weekday() >= 5
    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    auto_close_time = now_et.replace(hour=15, minute=55, second=0, microsecond=0)
    market_close_time = now_et.replace(hour=16, minute=15, second=0, microsecond=0)
    is_market_hours = market_open <= now_et <= market_close_time and not is_weekend
    auto_close_triggered = now_et >= auto_close_time and not is_weekend

    # ── Card 1: Trading Status ──
    max_loss = 1000.0
    halt_distance = max_loss + daily_realized_pnl  # positive = room left
    if halted:
        trading_status = "Blocked"
        trading_status_color = "red"
        trading_reason = "Daily halt triggered"
    elif not is_market_hours:
        if is_weekend:
            trading_status = "Blocked"
            trading_status_color = "red"
            trading_reason = "Weekend — market closed"
        elif now_et < market_open:
            trading_status = "Blocked"
            trading_status_color = "red"
            trading_reason = "Pre-market — waiting for 9:30 AM ET"
        else:
            trading_status = "Blocked"
            trading_status_color = "red"
            trading_reason = "Market closed for the day"
    else:
        # Time-of-day session
        h, m = now_et.hour, now_et.minute
        mins = h * 60 + m
        if mins < 13 * 60:  # before 1 PM
            trading_status = "Allowed"
            trading_status_color = "green"
            trading_reason = "Morning session — base + profits"
        elif mins < 15 * 60 + 30:  # before 3:30 PM
            if daily_realized_pnl > 0:
                trading_status = "Allowed"
                trading_status_color = "green"
                trading_reason = "Afternoon — house money only"
            else:
                trading_status = "Blocked"
                trading_status_color = "amber"
                trading_reason = "Afternoon requires house money"
        elif mins < 15 * 60 + 55:  # before 3:55 PM
            if daily_realized_pnl > 0:
                trading_status = "Allowed"
                trading_status_color = "amber"
                trading_reason = "EOD lotto — 15% of profits"
            else:
                trading_status = "Blocked"
                trading_status_color = "amber"
                trading_reason = "EOD lotto requires profits"
        else:
            trading_status = "Blocked"
            trading_status_color = "red"
            trading_reason = "0DTE cutoff — no new entries"

    # ── Card 3: Session Budget ──
    h, m = now_et.hour, now_et.minute
    mins = h * 60 + m
    if not is_market_hours:
        session_label = "Closed"
        session_detail = "No active session"
    elif mins < 13 * 60:
        session_label = "Morning"
        budget = 1000.0 + max(0, daily_realized_pnl)
        next_risk = budget * 0.50
        session_detail = f"$1,000 base + realized · next risk ${next_risk:,.0f}"
    elif mins < 15 * 60 + 30:
        session_label = "Afternoon"
        next_risk = max(0, daily_realized_pnl) * 0.25
        session_detail = f"profits only · next risk ${next_risk:,.0f}"
    else:
        session_label = "EOD Lotto"
        next_risk = max(0, daily_realized_pnl) * 0.15
        session_detail = f"profits only · next risk ${next_risk:,.0f}"

    # ── Card 4: Open Exposure ──
    same_day_count = sum(1 for p in open_positions if p.get("expiry_date") == today)
    positions_needing_attention = sum(1 for p in open_positions
        if not p.get("stop_price") or p.get("expiry_date") == today)

    # ── Card 5: Broker Health ──
    # Get latest ack/fill latency
    try:
        lat_row = conn.execute("""
            SELECT
                ROUND(AVG(CASE WHEN ack_received_at IS NOT NULL AND submit_started_at IS NOT NULL
                    THEN (julianday(ack_received_at) - julianday(submit_started_at)) * 86400000
                    ELSE NULL END), 0) as avg_ack_ms,
                ROUND(AVG(CASE WHEN first_fill_at IS NOT NULL AND submit_started_at IS NOT NULL
                    THEN (julianday(first_fill_at) - julianday(submit_started_at)) * 86400000
                    ELSE NULL END), 0) as avg_fill_ms
            FROM orders WHERE trade_date = ? AND submit_started_at IS NOT NULL
        """, (today,)).fetchone()
        avg_ack_ms = int(lat_row["avg_ack_ms"] or 0) if lat_row else 0
        avg_fill_ms = int(lat_row["avg_fill_ms"] or 0) if lat_row else 0
    except Exception:
        avg_ack_ms = 0
        avg_fill_ms = 0

    # ── Auto-close countdown ──
    auto_close_count = conn.execute(
        "SELECT COUNT(*) as c FROM realized_pnl_events WHERE trade_date = ? AND event_type = 'AUTO_CLOSE'",
        (today,),
    ).fetchone()["c"]

    if is_weekend:
        close_label = "Weekend"
    elif now_et < market_open:
        close_label = "Pre-market"
    elif now_et >= market_close_time:
        close_label = "Closed"
    elif auto_close_triggered:
        close_label = "Done"
    else:
        total_mins = max(0, int((auto_close_time - now_et).total_seconds() / 60))
        hours = total_mins // 60
        mins_left = total_mins % 60
        close_label = f"{hours}h {mins_left}m" if hours > 0 else f"{mins_left}m"

    # ── Entry Gate Result ──
    gates = []
    gates.append({"name": "Daily halt", "pass": not halted,
                  "detail": "HALTED" if halted else "Clear"})
    gates.append({"name": "Market hours", "pass": is_market_hours,
                  "detail": "Open" if is_market_hours else "Closed"})
    gates.append({"name": "Supported ticker", "pass": True, "detail": "13 tickers active"})
    gates.append({"name": "Entry <= $5.00", "pass": True, "detail": "Cap enforced"})

    # Per-ticker max pos — check if any ticker is at max
    ticker_counts = {}
    for p in open_positions:
        t = p.get("ticker", "SPX")
        if not p.get("is_runner"):
            ticker_counts[t] = ticker_counts.get(t, 0) + 1
    any_at_max = any(v >= 3 for v in ticker_counts.values())  # SPX max=3
    gates.append({"name": "Per-ticker max pos", "pass": not any_at_max,
                  "detail": "At limit" if any_at_max else "Available"})

    dte_cutoff = mins >= 15 * 60 + 55 if is_market_hours else False
    gates.append({"name": "0DTE cutoff", "pass": not dte_cutoff,
                  "detail": "Active" if dte_cutoff else "Clear"})

    all_gates_pass = all(g["pass"] for g in gates)
    if all_gates_pass:
        gate_result = "BUY ALLOWED"
        gate_result_color = "green"
    else:
        blocked_gates = [g["name"] for g in gates if not g["pass"]]
        gate_result = f"BUY BLOCKED — {' / '.join(blocked_gates)}"
        gate_result_color = "red"

    # ── Attention alerts ──
    attention_items = []
    if same_day_count > 0 and not auto_close_triggered:
        total_mins_left = max(0, int((auto_close_time - now_et).total_seconds() / 60))
        attention_items.append({
            "type": "AUTO-CLOSE",
            "severity": "red" if total_mins_left <= 15 else "amber",
            "title": f"AUTO-CLOSE IN {close_label}",
            "detail": f"{same_day_count} same-day expiry position{'s' if same_day_count != 1 else ''}",
        })

    # ITM risk — positions near ITM (placeholder, would need market data)
    for p in open_positions:
        if not p.get("stop_price") and p.get("expiry_date") != today:
            attention_items.append({
                "type": "MISSING STOP",
                "severity": "amber",
                "title": "MISSING STOP",
                "detail": f"{p.get('ticker', '?')} {p.get('contract_symbol', '?')} — no stop set",
            })

    # ── Reconnect count ──
    try:
        recon = conn.execute(
            "SELECT COUNT(*) as c FROM gateway_events WHERE event_type = 'reconnect' AND trade_date = ?",
            (today,),
        ).fetchone()
        reconnect_count = recon["c"] if recon else 0
    except Exception:
        reconnect_count = 0

    # ── Recent risk events from alerts table ──
    risk_events = []
    try:
        recent_alerts = conn.execute("""
            SELECT alert_time, ticker, action, parse_result, raw_text
            FROM alerts WHERE trade_date = ?
            ORDER BY alert_time DESC LIMIT 20
        """, (today,)).fetchall()
        for a in recent_alerts:
            result = a["parse_result"] or ""
            action = a["action"] or ""
            ticker = a["ticker"] or ""
            raw = (a["raw_text"] or "")[:80]
            time_str = (a["alert_time"] or "")[11:19]

            if result == "signal" and action in ("BUY", "SELL", "CLOSE", "UPDATE_STOP"):
                risk_events.append({
                    "time": time_str,
                    "type": action,
                    "color": "green" if action == "BUY" else "amber" if action == "UPDATE_STOP" else "blue",
                    "detail": f"{action} {ticker} — executed",
                })
            elif result == "ignored":
                risk_events.append({
                    "time": time_str,
                    "type": "SKIPPED",
                    "color": "muted",
                    "detail": f"non-actionable: {raw[:50]}",
                })
            elif result == "duplicate":
                risk_events.append({
                    "time": time_str,
                    "type": "DUPLICATE",
                    "color": "muted",
                    "detail": f"duplicate suppressed",
                })
            elif result in ("rejected", "blocked"):
                risk_events.append({
                    "time": time_str,
                    "type": "BUY BLOCKED",
                    "color": "red",
                    "detail": f"{ticker} {action} — {result}",
                })
    except Exception:
        pass

    # ── Position flags ──
    for p in open_positions:
        flags = []
        if p.get("expiry_date") == today:
            flags.append({"label": "0DTE", "color": "amber"})
            flags.append({"label": "AUTO-CLOSE", "color": "red"})
        if not p.get("stop_price"):
            flags.append({"label": "NO STOP", "color": "red"})
        if p.get("is_runner"):
            flags.append({"label": "RUNNER", "color": "green"})
        # DTE
        try:
            if p.get("expiry_date") and p["expiry_date"] != today:
                exp = datetime.strptime(p["expiry_date"], "%Y%m%d").date() if len(p["expiry_date"]) == 8 else datetime.strptime(p["expiry_date"], "%Y-%m-%d").date()
                dte = (exp - date.today()).days
                if dte == 1:
                    flags.append({"label": "1DTE", "color": "amber"})
                elif dte <= 3:
                    flags.append({"label": f"{dte}DTE", "color": "blue"})
        except Exception:
            pass
        p["flags"] = flags

    return templates.TemplateResponse("health.html", {
        "request": request,
        "active_page": "health",
        # Card data
        "trading_status": trading_status,
        "trading_status_color": trading_status_color,
        "trading_reason": trading_reason,
        "daily_realized_pnl": daily_realized_pnl,
        "halt_distance": halt_distance,
        "session_label": session_label,
        "session_detail": session_detail,
        "open_positions": open_positions,
        "same_day_count": same_day_count,
        "positions_needing_attention": positions_needing_attention,
        "gateway_connected": gateway_connected,
        "avg_ack_ms": avg_ack_ms,
        "avg_fill_ms": avg_fill_ms,
        # Gates
        "gates": gates,
        "all_gates_pass": all_gates_pass,
        "gate_result": gate_result,
        "gate_result_color": gate_result_color,
        # Bot health
        "halted": halted,
        "last_updated": last_updated,
        "reconnect_count": reconnect_count,
        "is_market_hours": is_market_hours,
        "is_weekend": is_weekend,
        # Auto-close
        "close_label": close_label,
        "auto_close_count": auto_close_count,
        "auto_close_triggered": auto_close_triggered,
        # Attention
        "attention_items": attention_items,
        # Events
        "risk_events": risk_events,
        "today": today,
    })


@router.get("/broker-metrics", response_class=HTMLResponse)
async def broker_metrics_page(request: Request, start: str = "", end: str = "", ticker: str = ""):
    redirect = _require_auth(request)
    if redirect:
        return redirect

    from app.api.broker_metrics import get_broker_metrics
    data = await get_broker_metrics(request, start=start, end=end, ticker=ticker)

    # Default dates
    if not start:
        conn = get_db()
        latest = conn.execute(
            "SELECT MIN(trade_date) as s, MAX(trade_date) as e FROM orders WHERE submit_started_at IS NOT NULL"
        ).fetchone()
        start = latest["s"] or date.today().isoformat()
        end = latest["e"] or date.today().isoformat()

    return templates.TemplateResponse("broker_metrics.html", {
        "request": request,
        "active_page": "broker_metrics",
        "start_date": start,
        "end_date": end or start,
        "ticker_filter": ticker,
        "latency": data.get("latency", {}),
        "latency_split": data.get("latency_split", {}),
        "slippage": data.get("slippage", {}),
        "order_flow": data.get("order_flow", {}),
        "gateway_health": data.get("gateway_health", {}),
        "errors": data.get("errors", []),
        "error_sparkline": data.get("error_sparkline", []),
        "by_ticker": data.get("by_ticker", []),
        "latency_percentiles": data.get("latency_percentiles", []),
        "order_events": data.get("order_events", []),
        "fill_types": data.get("fill_types", []),
        "notes": data.get("notes", []),
        "ack_buckets": data.get("ack_buckets", {"under_500": 0, "_500_to_1s": 0, "_1s_to_2s": 0, "_2s_plus": 0}),
        "fill_buckets": data.get("fill_buckets", {"under_500": 0, "_500_to_1s": 0, "_1s_to_2s": 0, "_2s_to_5s": 0, "_5s_to_10s": 0, "_10s_plus": 0}),
        "p95_ack": data.get("p95_ack", 0),
        "p95_fill": data.get("p95_fill", 0),
        "ack_hist": data.get("ack_hist", []),
        "fill_hist": data.get("fill_hist", []),
        "hist_labels": data.get("hist_labels", []),
        "total_dur_hist": data.get("total_dur_hist", []),
        "total_dur_labels": data.get("total_dur_labels", []),
        "avg_total_dur": data.get("avg_total_dur", 0),
        "p95_total_dur": data.get("p95_total_dur", 0),
        "n_total_dur": data.get("n_total_dur", 0),
    })
