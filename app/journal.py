"""
Read-only trading journal queries.

All methods return plain dicts/lists — no ORM, no dependencies.
The sqlite3.Connection is shared with TradeState (same DB file).
"""

import sqlite3
from datetime import date, timedelta
from typing import Optional


class TradingJournal:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ------------------------------------------------------------------ #
    #  Trade queries                                                       #
    # ------------------------------------------------------------------ #

    def trades_by_date(self, trade_date: str) -> list[dict]:
        """All executions for a given date (YYYY-MM-DD)."""
        rows = self.conn.execute(
            "SELECT * FROM executions WHERE trade_date = ? ORDER BY execution_time",
            (trade_date,),
        ).fetchall()
        return [dict(r) for r in rows]

    def trades_by_ticker(
        self, ticker: str, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> list[dict]:
        """All executions for a ticker, optionally within a date range."""
        sql = "SELECT * FROM executions WHERE ticker = ?"
        params: list = [ticker]
        if start_date:
            sql += " AND trade_date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND trade_date <= ?"
            params.append(end_date)
        sql += " ORDER BY execution_time"
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def trades_by_date_range(self, start: str, end: str) -> list[dict]:
        """All executions within a date range."""
        rows = self.conn.execute(
            "SELECT * FROM executions WHERE trade_date BETWEEN ? AND ? ORDER BY execution_time",
            (start, end),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    #  P&L queries                                                         #
    # ------------------------------------------------------------------ #

    def pnl_events_by_date(self, trade_date: str) -> list[dict]:
        """All realized P&L events for a given date."""
        rows = self.conn.execute(
            "SELECT * FROM realized_pnl_events WHERE trade_date = ? ORDER BY event_time",
            (trade_date,),
        ).fetchall()
        return [dict(r) for r in rows]

    def daily_pnl(self, trade_date: str) -> float:
        """Total realized P&L for a given date."""
        row = self.conn.execute(
            "SELECT COALESCE(SUM(realized_pnl), 0.0) as total FROM realized_pnl_events WHERE trade_date = ?",
            (trade_date,),
        ).fetchone()
        return row["total"]

    def pnl_by_period(self, period: str = "daily", start_date: Optional[str] = None) -> list[dict]:
        """Aggregate P&L by period ('daily', 'weekly', 'monthly').

        Returns list of {period_key, total_pnl, trade_count} dicts.
        """
        if period == "daily":
            group_expr = "trade_date"
        elif period == "weekly":
            # ISO week: YYYY-Www
            group_expr = "strftime('%Y-W%W', trade_date)"
        elif period == "monthly":
            group_expr = "strftime('%Y-%m', trade_date)"
        else:
            raise ValueError(f"Unknown period: {period}")

        sql = f"""
            SELECT {group_expr} as period_key,
                   SUM(realized_pnl) as total_pnl,
                   COUNT(*) as trade_count
            FROM realized_pnl_events
        """
        params: list = []
        if start_date:
            sql += " WHERE trade_date >= ?"
            params.append(start_date)
        sql += f" GROUP BY {group_expr} ORDER BY period_key"

        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    # ------------------------------------------------------------------ #
    #  Win/loss stats                                                      #
    # ------------------------------------------------------------------ #

    def win_loss_stats(
        self, start_date: Optional[str] = None, end_date: Optional[str] = None,
        ticker: Optional[str] = None
    ) -> dict:
        """Compute win/loss statistics from realized P&L events.

        Returns: {wins, losses, breakeven, total, win_rate, total_pnl, avg_win, avg_loss}
        """
        sql = "SELECT realized_pnl FROM realized_pnl_events WHERE 1=1"
        params: list = []
        if start_date:
            sql += " AND trade_date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND trade_date <= ?"
            params.append(end_date)
        if ticker:
            sql += " AND ticker = ?"
            params.append(ticker)

        rows = self.conn.execute(sql, params).fetchall()
        pnls = [r["realized_pnl"] for r in rows]

        if not pnls:
            return {
                "wins": 0, "losses": 0, "breakeven": 0, "total": 0,
                "win_rate": 0.0, "total_pnl": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
            }

        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        breakeven = [p for p in pnls if p == 0]

        return {
            "wins": len(wins),
            "losses": len(losses),
            "breakeven": len(breakeven),
            "total": len(pnls),
            "win_rate": round(len(wins) / len(pnls) * 100, 1) if pnls else 0.0,
            "total_pnl": round(sum(pnls), 2),
            "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
        }

    # ------------------------------------------------------------------ #
    #  Position history                                                    #
    # ------------------------------------------------------------------ #

    def position_history(self, position_id: str) -> list[dict]:
        """All events for a given position (entry through exit)."""
        rows = self.conn.execute(
            """SELECT 'execution' as source, execution_time as event_time,
                      side, contracts, fill_price, NULL as realized_pnl
               FROM executions WHERE position_id = ?
             UNION ALL
             SELECT 'pnl' as source, event_time,
                    event_type as side, contracts_closed as contracts,
                    exit_price as fill_price, realized_pnl
               FROM realized_pnl_events WHERE position_id = ?
             ORDER BY event_time""",
            (position_id, position_id),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    #  Trade detail                                                        #
    # ------------------------------------------------------------------ #

    def trade_detail(self, position_id: str) -> dict | None:
        """Full trade detail: position + executions + orders + pnl + linked alert + guru signal.

        Returns a dict with keys:
            position, executions, orders, pnl_events, alert, guru_signal, timeline
        """
        # Position (may be closed / removed from positions table)
        position = self.conn.execute(
            "SELECT * FROM positions WHERE position_id = ?", (position_id,)
        ).fetchone()
        position = dict(position) if position else None

        # All executions for this position
        executions = [dict(r) for r in self.conn.execute(
            "SELECT * FROM executions WHERE position_id = ? ORDER BY execution_time",
            (position_id,),
        ).fetchall()]

        # All orders for this position (by position_id, or by time-proximity if position_id is NULL)
        orders = [dict(r) for r in self.conn.execute(
            "SELECT * FROM orders WHERE position_id = ? ORDER BY order_time",
            (position_id,),
        ).fetchall()]

        if not orders and executions:
            # position_id may be NULL in orders table — match by time proximity to entry fill
            entry_exec = next((e for e in executions if e.get("side") == "BOT"), None)
            if entry_exec and entry_exec.get("execution_time") and trade_date:
                orders = [dict(r) for r in self.conn.execute(
                    """SELECT * FROM orders
                       WHERE trade_date = ? AND order_purpose = 'entry'
                       ORDER BY ABS(julianday(submit_started_at) - julianday(?))
                       LIMIT 1""",
                    (trade_date, entry_exec["execution_time"]),
                ).fetchall()]

        # All P&L events
        pnl_events = [dict(r) for r in self.conn.execute(
            "SELECT * FROM realized_pnl_events WHERE position_id = ? ORDER BY event_time",
            (position_id,),
        ).fetchall()]

        if not position and not executions and not pnl_events:
            return None

        # Derive ticker and contract from executions, pnl, or position
        ticker = None
        contract = None
        trade_date = None
        if executions:
            ticker = executions[0].get("ticker")
            contract = executions[0].get("contract_symbol")
            trade_date = executions[0].get("trade_date")
        elif pnl_events:
            ticker = pnl_events[0].get("ticker")
            contract = pnl_events[0].get("contract_symbol")
            trade_date = pnl_events[0].get("trade_date")
        elif position:
            ticker = position.get("ticker")
            contract = position.get("contract_symbol", "")
            trade_date = position.get("opened_at", "")[:10] if position.get("opened_at") else ""

        # Find entry execution for time-proximity matching
        entry_exec = next((e for e in executions if e.get("side") == "BOT"), None)

        # Linked alert (match by signal_id from order, or by time-proximity)
        alert = None
        if orders and orders[0].get("signal_id"):
            alert = self.conn.execute(
                "SELECT * FROM alerts WHERE signal_id = ?",
                (orders[0]["signal_id"],),
            ).fetchone()
        if not alert and trade_date and ticker and entry_exec:
            # Use time-proximity to find the alert closest to the actual fill
            alert = self.conn.execute(
                """SELECT * FROM alerts WHERE trade_date = ? AND ticker = ? AND outcome = 'filled'
                   ORDER BY ABS(julianday(alert_time) - julianday(?))
                   LIMIT 1""",
                (trade_date, ticker, entry_exec["execution_time"]),
            ).fetchone()
        elif not alert and trade_date and ticker:
            alert = self.conn.execute(
                "SELECT * FROM alerts WHERE trade_date = ? AND ticker = ? AND outcome = 'filled' ORDER BY alert_time DESC LIMIT 1",
                (trade_date, ticker),
            ).fetchone()
        alert = dict(alert) if alert else None

        # Linked guru signal
        guru_signal = None
        if trade_date and ticker:
            # Find the BUY guru signal closest to this position
            if entry_exec:
                guru_signal = self.conn.execute(
                    """SELECT * FROM guru_signals
                       WHERE trade_date = ? AND ticker = ? AND action = 'BUY'
                       ORDER BY ABS(julianday(signal_time) - julianday(?))
                       LIMIT 1""",
                    (trade_date, ticker, entry_exec["execution_time"]),
                ).fetchone()
            else:
                guru_signal = self.conn.execute(
                    "SELECT * FROM guru_signals WHERE trade_date = ? AND ticker = ? AND action = 'BUY' LIMIT 1",
                    (trade_date, ticker),
                ).fetchone()
        guru_signal = dict(guru_signal) if guru_signal else None

        # Build unified timeline
        # Note: alert_time is a DB-write timestamp (recorded AFTER order placement).
        # Use submit_started_at from the first entry order as the anchor — alert/parse/risk
        # logically happened before order submission.
        timeline = []

        # Find the earliest order submit time to anchor pre-trade events
        entry_order = next((o for o in orders if o.get("order_purpose") == "entry"), None)
        anchor_time = (
            (entry_order.get("submit_started_at") or entry_order.get("order_time", ""))
            if entry_order else ""
        )

        if alert:
            # Use anchor time (order submit) if available, else alert_time
            alert_time = anchor_time or alert.get("alert_time", "")
            timeline.append({
                "time": alert_time,
                "event": "ALERT RECEIVED",
                "detail": alert.get("raw_text", "")[:120],
                "type": "alert",
                "_priority": 0,
            })
            if alert.get("parse_result"):
                timeline.append({
                    "time": alert_time,
                    "event": f"PARSED → {alert.get('parse_result', '').upper()}",
                    "detail": f"{alert.get('action', '')} {ticker} {alert.get('strike', '')} {alert.get('right', '')} @ ${alert.get('entry_price', 0):.2f}" if alert.get("action") else "",
                    "type": "parse",
                    "_priority": 1,
                })
            if alert.get("risk_result"):
                timeline.append({
                    "time": alert_time,
                    "event": f"RISK → {alert.get('risk_result', '').upper()}",
                    "detail": alert.get("risk_reason", "") or "Approved",
                    "type": "risk_approved" if alert.get("risk_result") == "approved" else "risk_rejected",
                    "_priority": 2,
                })

        for o in orders:
            timeline.append({
                "time": o.get("submit_started_at") or o.get("order_time", ""),
                "event": f"ORDER {o.get('order_action', '')} ({o.get('order_type', '')})",
                "detail": f"{o.get('contracts', 0)} × {o.get('contract_symbol', '')} @ limit ${o.get('limit_price', 0):.2f}" if o.get("limit_price") else f"{o.get('contracts', 0)} × {o.get('contract_symbol', '')}",
                "type": "order",
                "_priority": 3,
            })
            if o.get("status") and o.get("filled_at"):
                timeline.append({
                    "time": o.get("filled_at", ""),
                    "event": f"ORDER {o.get('status', '').upper()}",
                    "detail": f"Fill @ ${o.get('fill_price', 0):.2f}" if o.get("fill_price") else "",
                    "type": "fill",
                    "_priority": 5,
                })

        for e in executions:
            timeline.append({
                "time": e.get("execution_time", ""),
                "event": f"FILL {e.get('side', '')}",
                "detail": f"{e.get('contracts', 0)} × ${e.get('fill_price', 0):.2f}" + (f" (commission: ${e.get('commission', 0):.2f})" if e.get("commission") else ""),
                "type": "fill_bot" if e.get("side") == "BOT" else "fill_sld",
                "_priority": 4,
            })

        for p in pnl_events:
            timeline.append({
                "time": p.get("event_time", ""),
                "event": f"P&L {p.get('event_type', '')}",
                "detail": f"${p.get('realized_pnl', 0):+.2f} (entry ${p.get('entry_price', 0):.2f} → exit ${p.get('exit_price', 0):.2f})",
                "type": "pnl_win" if (p.get("realized_pnl") or 0) > 0 else "pnl_loss",
                "_priority": 6,
            })

        # Sort by time, then by logical pipeline order (_priority) for same-second events
        timeline.sort(key=lambda x: (x["time"] or "", x.get("_priority", 99)))

        # Compute summary
        entry_price = None
        exit_price = None
        total_pnl = 0.0
        contracts = 0
        side_entries = [e for e in executions if e.get("side") == "BOT"]
        side_exits = [e for e in executions if e.get("side") == "SLD"]

        if side_entries:
            entry_price = side_entries[0].get("fill_price")
            contracts = sum(e.get("contracts", 0) for e in side_entries)
        elif position:
            entry_price = position.get("entry_price")
            contracts = position.get("contracts", 0)
        if side_exits:
            exit_price = side_exits[-1].get("fill_price")
        total_pnl = sum(p.get("realized_pnl", 0) for p in pnl_events)

        summary = {
            "position_id": position_id,
            "ticker": ticker,
            "contract": contract,
            "trade_date": trade_date,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "contracts": contracts,
            "total_pnl": round(total_pnl, 2),
            "is_win": total_pnl > 0,
            "is_open": position is not None,
        }

        return {
            "summary": summary,
            "position": position,
            "executions": executions,
            "orders": orders,
            "pnl_events": pnl_events,
            "alert": alert,
            "guru_signal": guru_signal,
            "timeline": timeline,
        }

    # ------------------------------------------------------------------ #
    #  Alert history                                                       #
    # ------------------------------------------------------------------ #

    def alerts_by_date(self, trade_date: str) -> list[dict]:
        """All alerts received on a given date."""
        rows = self.conn.execute(
            "SELECT * FROM alerts WHERE trade_date = ? ORDER BY alert_time",
            (trade_date,),
        ).fetchall()
        return [dict(r) for r in rows]

    def alert_outcomes(self, start_date: Optional[str] = None) -> dict:
        """Aggregate alert outcomes (filled, rejected, ignored, etc.)."""
        sql = "SELECT outcome, COUNT(*) as cnt FROM alerts"
        params: list = []
        if start_date:
            sql += " WHERE trade_date >= ?"
            params.append(start_date)
        sql += " GROUP BY outcome"
        rows = self.conn.execute(sql, params).fetchall()
        return {r["outcome"]: r["cnt"] for r in rows}

    # ------------------------------------------------------------------ #
    #  Daily summaries                                                     #
    # ------------------------------------------------------------------ #

    def daily_summary(self, trade_date: str) -> Optional[dict]:
        """Get the EOD summary for a specific date."""
        row = self.conn.execute(
            "SELECT * FROM daily_summaries WHERE trade_date = ?", (trade_date,)
        ).fetchone()
        return dict(row) if row else None

    def weekly_pnl(self, as_of: Optional[str] = None) -> float:
        """Total P&L for the current (or specified) week."""
        if as_of is None:
            as_of = date.today().isoformat()
        ref = date.fromisoformat(as_of)
        week_start = (ref - timedelta(days=ref.weekday())).isoformat()
        row = self.conn.execute(
            "SELECT COALESCE(SUM(total_pnl), 0.0) as total FROM daily_summaries WHERE trade_date >= ? AND trade_date <= ?",
            (week_start, as_of),
        ).fetchone()
        return row["total"]

    def monthly_pnl(self, as_of: Optional[str] = None) -> float:
        """Total P&L for the current (or specified) month."""
        if as_of is None:
            as_of = date.today().isoformat()
        month_start = as_of[:8] + "01"
        row = self.conn.execute(
            "SELECT COALESCE(SUM(total_pnl), 0.0) as total FROM daily_summaries WHERE trade_date >= ? AND trade_date <= ?",
            (month_start, as_of),
        ).fetchone()
        return row["total"]

    # ------------------------------------------------------------------ #
    #  Order history                                                       #
    # ------------------------------------------------------------------ #

    def orders_by_date(self, trade_date: str) -> list[dict]:
        """All orders placed on a given date."""
        rows = self.conn.execute(
            "SELECT * FROM orders WHERE trade_date = ? ORDER BY order_time",
            (trade_date,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    #  Guru signal queries                                                 #
    # ------------------------------------------------------------------ #

    def guru_signals(
        self, start_date: Optional[str] = None, end_date: Optional[str] = None,
        ticker: Optional[str] = None, action: Optional[str] = None,
    ) -> list[dict]:
        """All guru signals with optional filters."""
        sql = "SELECT * FROM guru_signals WHERE 1=1"
        params: list = []
        if start_date:
            sql += " AND trade_date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND trade_date <= ?"
            params.append(end_date)
        if ticker:
            sql += " AND ticker = ?"
            params.append(ticker)
        if action:
            sql += " AND action = ?"
            params.append(action)
        sql += " ORDER BY signal_time DESC"
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def guru_stats(
        self, start_date: Optional[str] = None, end_date: Optional[str] = None,
        ticker: Optional[str] = None,
    ) -> dict:
        """Guru performance stats: total signals, by action, by outcome."""
        sql = "SELECT action, we_executed, our_outcome, ticker FROM guru_signals WHERE 1=1"
        params: list = []
        if start_date:
            sql += " AND trade_date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND trade_date <= ?"
            params.append(end_date)
        if ticker:
            sql += " AND ticker = ?"
            params.append(ticker)

        rows = self.conn.execute(sql, params).fetchall()

        total = len(rows)
        buys = [r for r in rows if r["action"] == "BUY"]
        closes = [r for r in rows if r["action"] in ("CLOSE", "SELL", "PARTIAL_CLOSE")]
        executed = [r for r in rows if r["we_executed"]]
        rejected = [r for r in rows if r["our_outcome"] == "rejected"]

        # Per-ticker breakdown
        tickers: dict[str, dict] = {}
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
            "buys": len(buys),
            "closes": len(closes),
            "executed": len(executed),
            "rejected": len(rejected),
            "execution_rate": round(len(executed) / total * 100, 1) if total else 0.0,
            "by_ticker": tickers,
        }

    def guru_vs_bot_comparison(
        self, start_date: Optional[str] = None, end_date: Optional[str] = None,
        ticker: Optional[str] = None,
    ) -> dict:
        """Compare guru signals vs bot execution by ticker.

        Returns per-ticker: guru calls, bot executions, bot rejections, bot P&L.
        """
        # Guru side
        guru = self.guru_stats(start_date, end_date, ticker)

        # Bot side — realized P&L by ticker
        sql = "SELECT ticker, realized_pnl FROM realized_pnl_events WHERE 1=1"
        params: list = []
        if start_date:
            sql += " AND trade_date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND trade_date <= ?"
            params.append(end_date)
        if ticker:
            sql += " AND ticker = ?"
            params.append(ticker)

        bot_rows = self.conn.execute(sql, params).fetchall()
        bot_by_ticker: dict[str, dict] = {}
        for r in bot_rows:
            t = r["ticker"]
            if t not in bot_by_ticker:
                bot_by_ticker[t] = {"trades": 0, "total_pnl": 0.0, "wins": 0, "losses": 0}
            bot_by_ticker[t]["trades"] += 1
            bot_by_ticker[t]["total_pnl"] += r["realized_pnl"]
            if r["realized_pnl"] > 0:
                bot_by_ticker[t]["wins"] += 1
            elif r["realized_pnl"] < 0:
                bot_by_ticker[t]["losses"] += 1

        # Merge into comparison
        all_tickers = set(guru["by_ticker"].keys()) | set(bot_by_ticker.keys())
        comparison = {}
        for t in sorted(all_tickers):
            g = guru["by_ticker"].get(t, {"total": 0, "buys": 0, "closes": 0, "executed": 0, "rejected": 0})
            b = bot_by_ticker.get(t, {"trades": 0, "total_pnl": 0.0, "wins": 0, "losses": 0})
            comparison[t] = {
                "guru_signals": g["total"],
                "guru_buys": g["buys"],
                "guru_closes": g["closes"],
                "bot_executed": g["executed"],
                "bot_rejected": g["rejected"],
                "bot_trades": b["trades"],
                "bot_pnl": round(b["total_pnl"], 2),
                "bot_wins": b["wins"],
                "bot_losses": b["losses"],
                "bot_win_rate": round(b["wins"] / b["trades"] * 100, 1) if b["trades"] else 0.0,
            }

        return {
            "guru_summary": guru,
            "bot_by_ticker": bot_by_ticker,
            "comparison": comparison,
        }
