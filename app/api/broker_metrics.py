"""Broker performance metrics API — latency, slippage, fill quality, gateway health."""

import json

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

    # --- Latency split: Submit→ACK, Submit→Fill, Cancel Confirmation ---
    latency_split_sql = f"""
        SELECT
            ROUND(AVG(
                CASE WHEN ack_received_at IS NOT NULL AND submit_started_at IS NOT NULL
                THEN (julianday(ack_received_at) - julianday(submit_started_at)) * 86400000
                ELSE NULL END
            ), 0) as avg_submit_to_ack_ms,
            MIN(
                CASE WHEN ack_received_at IS NOT NULL AND submit_started_at IS NOT NULL
                THEN (julianday(ack_received_at) - julianday(submit_started_at)) * 86400000
                ELSE NULL END
            ) as min_submit_to_ack_ms,
            MAX(
                CASE WHEN ack_received_at IS NOT NULL AND submit_started_at IS NOT NULL
                THEN (julianday(ack_received_at) - julianday(submit_started_at)) * 86400000
                ELSE NULL END
            ) as max_submit_to_ack_ms,
            ROUND(AVG(
                CASE WHEN first_fill_at IS NOT NULL AND submit_started_at IS NOT NULL
                THEN (julianday(first_fill_at) - julianday(submit_started_at)) * 86400000
                ELSE NULL END
            ), 0) as avg_submit_to_fill_ms,
            MIN(
                CASE WHEN first_fill_at IS NOT NULL AND submit_started_at IS NOT NULL
                THEN (julianday(first_fill_at) - julianday(submit_started_at)) * 86400000
                ELSE NULL END
            ) as min_submit_to_fill_ms,
            MAX(
                CASE WHEN first_fill_at IS NOT NULL AND submit_started_at IS NOT NULL
                THEN (julianday(first_fill_at) - julianday(submit_started_at)) * 86400000
                ELSE NULL END
            ) as max_submit_to_fill_ms
        FROM orders o {where}
    """
    latency_split = dict(conn.execute(latency_split_sql, params).fetchone() or {})

    # Cancel confirmation latency (from order_events: cancel_requested → canceled)
    cancel_conditions = []
    cancel_params = []
    if start:
        cancel_conditions.append("oe1.event_time >= ?")
        cancel_params.append(start)
    if end:
        cancel_conditions.append("oe1.event_time <= ?")
        cancel_params.append(end + "T23:59:59")
    cancel_where = f"AND {' AND '.join(cancel_conditions)}" if cancel_conditions else ""

    cancel_sql = f"""
        SELECT ROUND(AVG(
            (julianday(oe2.event_time) - julianday(oe1.event_time)) * 86400000
        ), 0) as avg_cancel_confirm_ms
        FROM order_events oe1
        JOIN order_events oe2 ON oe1.order_id = oe2.order_id
        WHERE oe1.event_type = 'cancel_requested'
          AND oe2.event_type = 'canceled'
          {cancel_where}
    """
    try:
        cancel_row = conn.execute(cancel_sql, cancel_params).fetchone()
        latency_split["avg_cancel_confirm_ms"] = (cancel_row["avg_cancel_confirm_ms"] or 0) if cancel_row else 0
    except Exception:
        latency_split["avg_cancel_confirm_ms"] = 0

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
            COUNT(CASE WHEN o.quote_age_ms > 2000 THEN 1 END) as stale_quotes,
            ROUND(AVG(o.fill_price), 2) as avg_fill_price,
            ROUND(AVG(o.signal_price), 2) as avg_entry_price
        FROM orders o {slippage_where}
    """
    slippage = dict(conn.execute(slippage_sql, slippage_params).fetchone() or {})

    # --- Order flow summary ---
    all_orders_conditions = []
    all_orders_params = []
    if start:
        all_orders_conditions.append("o.trade_date >= ?")
        all_orders_params.append(start)
    if end:
        all_orders_conditions.append("o.trade_date <= ?")
        all_orders_params.append(end)
    if ticker:
        all_orders_conditions.append("o.ticker = ?")
        all_orders_params.append(ticker)
    all_orders_where = f"WHERE {' AND '.join(all_orders_conditions)}" if all_orders_conditions else ""

    order_flow_sql = f"""
        SELECT
            COUNT(*) as total_submitted,
            COUNT(CASE WHEN o.status = 'filled' THEN 1 END) as filled,
            COUNT(CASE WHEN o.status = 'cancelled' OR o.status = 'canceled' THEN 1 END) as cancelled,
            COUNT(CASE WHEN o.status = 'failed' THEN 1 END) as failed,
            COUNT(CASE WHEN o.escalated = 1 THEN 1 END) as escalated,
            MAX(o.filled_at) as last_fill_time
        FROM orders o {all_orders_where}
    """
    order_flow = dict(conn.execute(order_flow_sql, all_orders_params).fetchone() or {})

    # Partial fills count from order_events
    partial_conditions = []
    partial_params = []
    if start:
        partial_conditions.append("oe.event_time >= ?")
        partial_params.append(start)
    if end:
        partial_conditions.append("oe.event_time <= ?")
        partial_params.append(end + "T23:59:59")
    partial_where = f"WHERE {' AND '.join(partial_conditions)}" if partial_conditions else ""
    if partial_where:
        partial_where += " AND oe.event_type = 'partial_fill'"
    else:
        partial_where = "WHERE oe.event_type = 'partial_fill'"

    try:
        partial_row = conn.execute(
            f"SELECT COUNT(*) as count FROM order_events oe {partial_where}", partial_params
        ).fetchone()
        order_flow["partial_fills"] = partial_row["count"] if partial_row else 0
    except Exception:
        order_flow["partial_fills"] = 0

    # Compute rates
    total = order_flow.get("total_submitted", 0) or 1
    order_flow["fill_rate"] = round(order_flow.get("filled", 0) / total * 100, 1)
    order_flow["cancel_rate"] = round(order_flow.get("cancelled", 0) / total * 100, 1)
    order_flow["escalation_rate"] = round(order_flow.get("escalated", 0) / total * 100, 1)
    order_flow["reject_rate"] = round(order_flow.get("failed", 0) / total * 100, 1)

    # --- Gateway health ---
    # system_state table has: trade_date, daily_realized_pnl, daily_unrealized_pnl,
    # halted, halt_reason, last_reconcile_time, updated_at
    # gateway_connected column does NOT exist yet — derive status from updated_at recency
    try:
        gw_row = conn.execute(
            "SELECT updated_at, trade_date, halted FROM system_state ORDER BY trade_date DESC LIMIT 1"
        ).fetchone()
        if gw_row:
            last_sync = gw_row["updated_at"]
            # Consider "connected" if last state update was within the last 5 minutes
            from datetime import datetime, timedelta, timezone
            try:
                sync_time = datetime.fromisoformat(last_sync) if last_sync else None
                # Ensure timezone-aware for comparison
                if sync_time and sync_time.tzinfo is None:
                    sync_time = sync_time.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                is_recent = sync_time and (now - sync_time) < timedelta(minutes=5)
            except Exception:
                is_recent = False
            gateway_health = {
                "connected": is_recent,
                "last_sync": last_sync,
                "trade_date": gw_row["trade_date"],
                "market_data": "Live" if is_recent else "Stale",
                "halted": bool(gw_row["halted"]),
                "reconnects": None,  # Not tracked in DB yet (Phase 2)
                "disconnect_duration": None,  # Not tracked in DB yet (Phase 2)
                "uptime_pct": None,  # Not tracked in DB yet (Phase 2)
            }
        else:
            gateway_health = {
                "connected": False, "last_sync": None, "trade_date": None,
                "market_data": "Unknown", "halted": False, "reconnects": None,
                "disconnect_duration": None, "uptime_pct": None,
            }
    except Exception:
        gateway_health = {
            "connected": False, "last_sync": None, "trade_date": None,
            "market_data": "Unknown", "halted": False, "reconnects": None,
            "disconnect_duration": None, "uptime_pct": None,
        }

    # --- Recent errors ---
    error_conditions = []
    error_params = []
    if start:
        error_conditions.append("o.trade_date >= ?")
        error_params.append(start)
    if end:
        error_conditions.append("o.trade_date <= ?")
        error_params.append(end)
    if ticker:
        error_conditions.append("o.ticker = ?")
        error_params.append(ticker)
    error_where = f"AND {' AND '.join(error_conditions)}" if error_conditions else ""

    errors_sql = f"""
        SELECT
            COALESCE(oe.event_time, o.order_time) as error_time,
            oe.event_type as error_type,
            oe.metadata as error_metadata,
            o.ticker,
            o.contract_symbol,
            o.status as order_status,
            o.order_type,
            o.order_action
        FROM orders o
        LEFT JOIN order_events oe ON o.id = oe.order_id
            AND oe.event_type IN ('rejected', 'canceled', 'escalated')
        WHERE (o.status IN ('failed', 'cancelled', 'canceled') OR oe.event_type IS NOT NULL)
            {error_where}
        ORDER BY COALESCE(oe.event_time, o.order_time) DESC
        LIMIT 20
    """
    try:
        errors = [dict(r) for r in conn.execute(errors_sql, error_params).fetchall()]
        # Parse metadata JSON for error codes/messages
        for e in errors:
            if e.get("error_metadata"):
                try:
                    meta = json.loads(e["error_metadata"])
                    e["error_code"] = meta.get("error_code", meta.get("code", ""))
                    e["error_message"] = meta.get("error_message", meta.get("message", meta.get("reason", "")))
                except (json.JSONDecodeError, TypeError):
                    e["error_code"] = ""
                    e["error_message"] = str(e["error_metadata"])[:100]
            else:
                e["error_code"] = ""
                e["error_message"] = e.get("error_type", e.get("order_status", ""))
    except Exception:
        errors = []

    # Error count by date (for sparkline — last 7 days)
    try:
        error_sparkline_sql = """
            SELECT o.trade_date, COUNT(*) as count
            FROM orders o
            WHERE o.status IN ('failed', 'cancelled', 'canceled')
            GROUP BY o.trade_date
            ORDER BY o.trade_date DESC
            LIMIT 7
        """
        error_sparkline = [dict(r) for r in conn.execute(error_sparkline_sql).fetchall()]
        error_sparkline.reverse()  # chronological order
    except Exception:
        error_sparkline = []

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
    total_orders = latency.get("total_orders", 0)
    if total_orders > 0:
        avg_lat = latency.get("avg_latency_ms", 0) or 0
        escalated_count = latency.get("escalated_count", 0) or 0
        over_20 = latency.get("over_20s", 0) or 0
        esc_pct = round(escalated_count / total_orders * 100, 1) if total_orders else 0
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
        "latency_split": latency_split,
        "slippage": slippage,
        "order_flow": order_flow,
        "gateway_health": gateway_health,
        "errors": errors,
        "error_sparkline": error_sparkline,
        "by_ticker": by_ticker,
        "recent_orders": recent,
        "order_events": events,
        "fill_types": fill_types,
        "notes": notes,
    }
