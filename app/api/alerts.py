"""GET /api/alerts — alert history with parse/risk/outcome."""

from datetime import date

from fastapi import APIRouter, Query

from app.db import get_db

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/alerts")
async def get_alerts(
    start: str | None = Query(None),
    end: str | None = Query(None),
    outcome: str | None = Query(None),
    page: int = Query(1, ge=1, le=25),
    per_page: int = Query(15, ge=1, le=50),
):
    conn = get_db()
    sql = "SELECT * FROM alerts WHERE 1=1"
    count_sql = "SELECT COUNT(*) as cnt FROM alerts WHERE 1=1"
    params: list = []

    if start:
        sql += " AND trade_date >= ?"
        count_sql += " AND trade_date >= ?"
        params.append(start)
    if end:
        sql += " AND trade_date <= ?"
        count_sql += " AND trade_date <= ?"
        params.append(end)
    if outcome:
        sql += " AND outcome = ?"
        count_sql += " AND outcome = ?"
        params.append(outcome)

    total = conn.execute(count_sql, params).fetchone()["cnt"]
    total_pages = min(25, max(1, (min(total, 500) + per_page - 1) // per_page))
    page = min(page, total_pages) if total_pages > 0 else 1
    offset = (page - 1) * per_page

    sql += f" ORDER BY alert_time DESC LIMIT {per_page} OFFSET {offset}"
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

    # Fix stale outcomes: SELL/CLOSE marked "filled" but no order exists = "no_position"
    for row in rows:
        if row.get("outcome") == "filled" and row.get("action") in ("SELL", "CLOSE", "PARTIAL_CLOSE"):
            sig_id = row.get("signal_id")
            if sig_id:
                has_order = conn.execute(
                    "SELECT COUNT(*) as cnt FROM orders WHERE signal_id = ? AND status = 'filled'",
                    (sig_id,)
                ).fetchone()["cnt"]
                if has_order == 0:
                    row["outcome"] = "no_position"

    return {"alerts": rows, "page": page, "total_pages": total_pages, "total": total}


@router.get("/alerts/{alert_id}/execution-detail")
async def get_execution_detail(alert_id: int):
    """Get full execution timeline for an alert — orders + order_events."""
    conn = get_db()

    # Get the alert
    alert = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    if not alert:
        return {"error": "Alert not found"}
    alert_dict = dict(alert)

    # Find orders linked to this alert via signal_id
    signal_id = alert_dict.get("signal_id")
    orders = []
    events = []

    if signal_id:
        order_rows = conn.execute(
            """SELECT id, order_time, ticker, contract_symbol, order_type, order_action,
                      order_purpose, contracts, limit_price, ibkr_order_id, status,
                      fill_price, filled_at, submit_started_at, ack_received_at,
                      first_fill_at, escalated, total_latency_ms, signal_price,
                      reference_bid, reference_ask, reference_mid
               FROM orders WHERE signal_id = ? ORDER BY order_time""",
            (signal_id,)
        ).fetchall()
        orders = [dict(r) for r in order_rows]

        # Get all order_events for these orders
        order_ids = [o["id"] for o in orders]
        if order_ids:
            placeholders = ",".join("?" * len(order_ids))
            event_rows = conn.execute(
                f"""SELECT oe.id, oe.order_id, oe.event_type, oe.event_time,
                           oe.price, oe.contracts, oe.metadata
                    FROM order_events oe
                    WHERE oe.order_id IN ({placeholders})
                    ORDER BY oe.event_time""",
                order_ids
            ).fetchall()
            events = [dict(r) for r in event_rows]

    # For orders without detailed events, infer a summary from order data
    inferred_summary = None
    if orders and not any(e.get("metadata") for e in events):
        o = orders[0]
        parts = []
        if o.get("status") == "failed":
            latency = o.get("total_latency_ms")
            if latency:
                parts.append(f"Order failed after {latency}ms ({latency/1000:.1f}s)")
            if o.get("escalated"):
                parts.append("Escalated to market order but still did not fill")
            if not parts:
                parts.append("Order failed — no fill received from IBKR")
            # Check if it was a market data issue (common on paper)
            if latency and latency > 30000:
                parts.append("Likely cause: no market data subscription on paper account (Error 354)")
        elif o.get("status") == "filled":
            parts.append(f"Filled at ${o['fill_price']:.2f}" if o.get("fill_price") else "Filled")
            if o.get("total_latency_ms"):
                parts.append(f"Total execution time: {o['total_latency_ms']}ms")
        inferred_summary = " | ".join(parts) if parts else None

    # For SELL/CLOSE with no orders — explain why
    if not orders and alert_dict.get("action") in ("SELL", "CLOSE", "PARTIAL_CLOSE"):
        if alert_dict.get("outcome") in ("filled", "no_position"):
            inferred_summary = "No matching open position found — sell signal had nothing to close"

    return {
        "alert": alert_dict,
        "orders": orders,
        "events": events,
        "inferred_summary": inferred_summary,
    }
