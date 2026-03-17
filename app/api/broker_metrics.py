"""Broker performance metrics API — latency, slippage, fill quality."""

from fastapi import APIRouter, Request
from app.db import get_db

router = APIRouter()


@router.get("/api/broker-metrics")
async def get_broker_metrics(request: Request, start: str = "", end: str = "", ticker: str = ""):
    conn = get_db()

    # Build WHERE clause
    conditions = []
    params = []
    if start:
        conditions.append("o.trade_date >= ?")
        params.append(start)
    if end:
        conditions.append("o.trade_date <= ?")
        params.append(end)
    if ticker:
        conditions.append("o.ticker = ?")
        params.append(ticker)
    # Only include orders with metrics (have submit_started_at)
    conditions.append("o.submit_started_at IS NOT NULL")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    # --- Latency metrics ---
    latency_sql = f"""
        SELECT
            COUNT(*) as total_orders,
            ROUND(AVG(total_latency_ms), 0) as avg_latency_ms,
            MIN(total_latency_ms) as min_latency_ms,
            MAX(total_latency_ms) as max_latency_ms,
            COUNT(CASE WHEN total_latency_ms < 2000 THEN 1 END) as under_2s,
            COUNT(CASE WHEN total_latency_ms >= 2000 AND total_latency_ms < 5000 THEN 1 END) as _2_to_5s,
            COUNT(CASE WHEN total_latency_ms >= 5000 AND total_latency_ms < 10000 THEN 1 END) as _5_to_10s,
            COUNT(CASE WHEN total_latency_ms >= 10000 AND total_latency_ms < 20000 THEN 1 END) as _10_to_20s,
            COUNT(CASE WHEN total_latency_ms >= 20000 THEN 1 END) as over_20s,
            COUNT(CASE WHEN escalated = 1 THEN 1 END) as escalated_count
        FROM orders o {where}
    """
    latency = dict(conn.execute(latency_sql, params).fetchone() or {})

    # --- Slippage metrics (only for filled orders with reference_mid) ---
    slippage_conditions = conditions + ["o.fill_price IS NOT NULL", "o.reference_mid IS NOT NULL", "o.reference_mid > 0"]
    slippage_where = f"WHERE {' AND '.join(slippage_conditions)}"
    slippage_params = params[:]

    slippage_sql = f"""
        SELECT
            COUNT(*) as total_with_quote,
            ROUND(AVG(
                CASE WHEN o.order_action = 'BUY' THEN o.fill_price - o.reference_mid
                     ELSE o.reference_mid - o.fill_price END
            ), 4) as avg_slippage,
            ROUND(AVG(
                CASE WHEN o.order_action = 'BUY' THEN o.fill_price - o.signal_price
                     ELSE o.signal_price - o.fill_price END
            ), 4) as avg_slippage_vs_signal,
            ROUND(AVG(o.reference_ask - o.reference_bid), 4) as avg_spread,
            ROUND(AVG(o.quote_age_ms), 0) as avg_quote_age_ms,
            COUNT(CASE WHEN o.quote_age_ms > 2000 THEN 1 END) as stale_quotes
        FROM orders o {slippage_where}
    """
    slippage = dict(conn.execute(slippage_sql, slippage_params).fetchone() or {})

    # --- Per-ticker breakdown ---
    ticker_sql = f"""
        SELECT
            o.ticker,
            COUNT(*) as orders,
            ROUND(AVG(total_latency_ms), 0) as avg_latency_ms,
            COUNT(CASE WHEN escalated = 1 THEN 1 END) as escalated,
            ROUND(AVG(
                CASE WHEN o.fill_price IS NOT NULL AND o.reference_mid IS NOT NULL AND o.reference_mid > 0
                     THEN CASE WHEN o.order_action = 'BUY' THEN o.fill_price - o.reference_mid
                               ELSE o.reference_mid - o.fill_price END
                     ELSE NULL END
            ), 4) as avg_slippage,
            ROUND(AVG(
                CASE WHEN o.fill_price IS NOT NULL AND o.signal_price IS NOT NULL AND o.signal_price > 0
                     THEN CASE WHEN o.order_action = 'BUY' THEN o.fill_price - o.signal_price
                               ELSE o.signal_price - o.fill_price END
                     ELSE NULL END
            ), 4) as avg_slippage_vs_signal,
            COUNT(CASE WHEN o.status = 'filled' THEN 1 END) as filled,
            COUNT(CASE WHEN o.status = 'failed' THEN 1 END) as failed
        FROM orders o {where}
        GROUP BY o.ticker
        ORDER BY orders DESC
    """
    by_ticker = [dict(r) for r in conn.execute(ticker_sql, params).fetchall()]

    # --- Recent orders with full metrics ---
    recent_sql = f"""
        SELECT
            o.order_time, o.ticker, o.contract_symbol, o.order_type, o.order_action,
            o.order_purpose, o.contracts, o.limit_price, o.fill_price, o.status,
            o.reference_bid, o.reference_ask, o.reference_mid, o.signal_price,
            o.quote_age_ms, o.submit_started_at, o.ack_received_at, o.first_fill_at,
            o.filled_at, o.escalated, o.filled_contracts, o.total_latency_ms, o.trade_date
        FROM orders o {where}
        ORDER BY o.order_time DESC
        LIMIT 50
    """
    recent = [dict(r) for r in conn.execute(recent_sql, params).fetchall()]

    # --- Order events for timeline ---
    events_sql = """
        SELECT oe.order_id, oe.event_type, oe.event_time, oe.price, oe.contracts, oe.metadata
        FROM order_events oe
        ORDER BY oe.event_time DESC
        LIMIT 100
    """
    try:
        events = [dict(r) for r in conn.execute(events_sql).fetchall()]
    except Exception:
        events = []

    # --- Fill type distribution ---
    fill_type_sql = f"""
        SELECT
            COALESCE(e.fill_type, 'unknown') as fill_type,
            COUNT(*) as count
        FROM executions e
        WHERE e.trade_date >= COALESCE(?, e.trade_date)
          AND e.trade_date <= COALESCE(?, e.trade_date)
        GROUP BY fill_type
        ORDER BY count DESC
    """
    fill_params = [start or None, end or None]
    try:
        fill_types = [dict(r) for r in conn.execute(fill_type_sql, fill_params).fetchall()]
    except Exception:
        fill_types = []

    # --- System notes ---
    notes = []
    total = latency.get("total_orders", 0)
    if total > 0:
        avg_lat = latency.get("avg_latency_ms", 0) or 0
        escalated = latency.get("escalated_count", 0) or 0
        over_20 = latency.get("over_20s", 0) or 0
        esc_pct = round(escalated / total * 100, 1) if total else 0
        stale = slippage.get("stale_quotes", 0) or 0

        if avg_lat < 5000:
            notes.append(f"Average latency {avg_lat:.0f}ms — within acceptable range for paper account")
        elif avg_lat < 15000:
            notes.append(f"Average latency {avg_lat:.0f}ms — moderate, check gateway connectivity")
        else:
            notes.append(f"Average latency {avg_lat:.0f}ms — HIGH, investigate gateway/network issues")

        if esc_pct > 30:
            notes.append(f"Escalation rate {esc_pct}% — limit prices may need adjustment")
        elif esc_pct > 0:
            notes.append(f"Escalation rate {esc_pct}% — normal for volatile contracts")

        if over_20 > 0:
            notes.append(f"{over_20} orders took 20+ seconds — may indicate gateway delays")

        if stale > 0:
            notes.append(f"{stale} orders had stale quotes (>2s) — slippage numbers may be noisy")

        avg_slip = slippage.get("avg_slippage")
        if avg_slip is not None:
            if abs(avg_slip) < 0.05:
                notes.append(f"Average slippage ${avg_slip:+.4f} — excellent execution quality")
            elif abs(avg_slip) < 0.15:
                notes.append(f"Average slippage ${avg_slip:+.4f} — acceptable for options")
            else:
                notes.append(f"Average slippage ${avg_slip:+.4f} — consider tighter limit offsets")
    else:
        notes.append("No instrumented orders yet — metrics will populate as trades execute")

    return {
        "latency": latency,
        "slippage": slippage,
        "by_ticker": by_ticker,
        "recent_orders": recent,
        "order_events": events,
        "fill_types": fill_types,
        "notes": notes,
    }
