"""Tests for Broker Metrics page and API."""

import sys
sys.path.insert(0, "/Users/srinivasthammanaboina/spx_trader")

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def _login():
    client.post("/login", data={"password": "test123"})


def test_broker_metrics_api():
    """Broker metrics API returns expected structure."""
    _login()
    r = client.get("/api/broker-metrics")
    assert r.status_code == 200
    data = r.json()
    # Original keys
    assert "latency" in data
    assert "slippage" in data
    assert "by_ticker" in data
    assert "recent_orders" in data
    assert "notes" in data
    assert "fill_types" in data
    # New keys
    assert "latency_split" in data
    assert "order_flow" in data
    assert "gateway_health" in data
    assert "errors" in data
    assert "error_sparkline" in data
    print(f"  API: {data['latency']['total_orders']} orders, {len(data)} top-level keys")


def test_broker_metrics_latency_fields():
    """Latency metrics have all expected fields."""
    _login()
    data = client.get("/api/broker-metrics").json()
    lat = data["latency"]
    for field in ["total_orders", "avg_latency_ms", "min_latency_ms", "max_latency_ms",
                  "under_2s", "_2_to_5s", "_5_to_10s", "_10_to_20s", "over_20s", "escalated_count"]:
        assert field in lat, f"Missing latency field: {field}"
    print(f"  Latency: min={lat['min_latency_ms']}ms max={lat['max_latency_ms']}ms")


def test_broker_metrics_latency_split():
    """Latency split provides Submit→ACK, Submit→Fill, Cancel Confirm."""
    _login()
    data = client.get("/api/broker-metrics").json()
    ls = data["latency_split"]
    for field in ["avg_submit_to_ack_ms", "avg_submit_to_fill_ms", "avg_cancel_confirm_ms"]:
        assert field in ls, f"Missing latency_split field: {field}"
    print(f"  Latency split: ack={ls['avg_submit_to_ack_ms']}ms fill={ls['avg_submit_to_fill_ms']}ms cancel={ls['avg_cancel_confirm_ms']}ms")


def test_broker_metrics_order_flow():
    """Order flow summary has counts and rates."""
    _login()
    data = client.get("/api/broker-metrics").json()
    of = data["order_flow"]
    for field in ["total_submitted", "filled", "cancelled", "failed", "escalated",
                  "partial_fills", "fill_rate", "cancel_rate", "escalation_rate", "reject_rate"]:
        assert field in of, f"Missing order_flow field: {field}"
    print(f"  Order flow: {of['total_submitted']} submitted, {of['filled']} filled, fill_rate={of['fill_rate']}%")


def test_broker_metrics_gateway_health():
    """Gateway health returns connection status."""
    _login()
    data = client.get("/api/broker-metrics").json()
    gw = data["gateway_health"]
    for field in ["connected", "last_sync", "market_data"]:
        assert field in gw, f"Missing gateway_health field: {field}"
    assert isinstance(gw["connected"], bool)
    print(f"  Gateway: connected={gw['connected']}, market_data={gw['market_data']}")


def test_broker_metrics_errors():
    """Errors list returns array with expected fields."""
    _login()
    data = client.get("/api/broker-metrics").json()
    assert isinstance(data["errors"], list)
    if data["errors"]:
        e = data["errors"][0]
        assert "error_time" in e
        assert "error_code" in e
        assert "contract_symbol" in e or "ticker" in e
    print(f"  Errors: {len(data['errors'])} entries")


def test_broker_metrics_slippage_fields():
    """Slippage metrics have all expected fields."""
    _login()
    data = client.get("/api/broker-metrics").json()
    slip = data["slippage"]
    for field in ["total_with_quote", "avg_slippage", "avg_slippage_vs_signal",
                  "avg_spread", "avg_quote_age_ms", "stale_quotes",
                  "avg_fill_price", "avg_entry_price"]:
        assert field in slip, f"Missing slippage field: {field}"
    print(f"  Slippage: avg=${slip['avg_slippage']}, fill=${slip['avg_fill_price']}, entry=${slip['avg_entry_price']}")


def test_broker_metrics_by_ticker():
    """Per-ticker breakdown returns data."""
    _login()
    data = client.get("/api/broker-metrics").json()
    assert len(data["by_ticker"]) > 0
    for t in data["by_ticker"]:
        assert "ticker" in t
        assert "orders" in t
        assert "avg_latency_ms" in t
    print(f"  Tickers: {[t['ticker'] for t in data['by_ticker']]}")


def test_broker_metrics_recent_orders():
    """Recent orders include instrumented fields."""
    _login()
    data = client.get("/api/broker-metrics").json()
    assert len(data["recent_orders"]) > 0
    o = data["recent_orders"][0]
    assert "reference_bid" in o
    assert "reference_mid" in o
    assert "total_latency_ms" in o
    assert "submit_started_at" in o
    print(f"  Recent: {len(data['recent_orders'])} orders, first={o['ticker']}")


def test_broker_metrics_filter_by_ticker():
    """Ticker filter works."""
    _login()
    data = client.get("/api/broker-metrics?ticker=SPX").json()
    for t in data["by_ticker"]:
        assert t["ticker"] == "SPX"
    for o in data["recent_orders"]:
        assert o["ticker"] == "SPX"
    print(f"  SPX filter: {data['latency']['total_orders']} orders")


def test_broker_metrics_system_notes():
    """System notes are auto-generated."""
    _login()
    data = client.get("/api/broker-metrics").json()
    assert len(data["notes"]) > 0
    print(f"  Notes: {data['notes'][:2]}")


def test_broker_metrics_page_renders():
    """Broker metrics HTML page renders without error."""
    _login()
    r = client.get("/broker-metrics")
    assert r.status_code == 200
    # New page title
    assert "Broker Metrics" in r.text
    # New panels
    assert "Gateway Status" in r.text or "GATEWAY STATUS" in r.text
    assert "Order Flow" in r.text or "ORDER FLOW" in r.text
    assert "Execution Latency Summary" in r.text
    assert "Recent Errors" in r.text
    assert "Execution Quality" in r.text
    assert "Per-Ticker Breakdown" in r.text
    print(f"  Page: {len(r.text)} bytes")


def test_broker_metrics_in_sidebar():
    """Broker Metrics link appears in sidebar."""
    _login()
    r = client.get("/dashboard")
    assert "Broker Metrics" in r.text
    print("  Sidebar: Broker Metrics link present")


def test_all_pages_still_render():
    """Regression: all existing pages still render after broker metrics redesign."""
    _login()
    pages = {
        "/dashboard": "Bot Trades Overview",
        "/trades": "Trade History",
        "/alerts": "Alert",
        "/analytics": "Analytics",
        "/guru": "Guru vs Bot",
        "/health": "Risk Dashboard",
        "/broker-metrics": "Broker Metrics",
    }
    for path, expected in pages.items():
        r = client.get(path)
        assert r.status_code == 200, f"{path} returned {r.status_code}"
        assert expected in r.text, f"{path} missing '{expected}'"
        print(f"  {path}: OK ({len(r.text)} bytes)")


if __name__ == "__main__":
    tests = [
        test_broker_metrics_api,
        test_broker_metrics_latency_fields,
        test_broker_metrics_latency_split,
        test_broker_metrics_order_flow,
        test_broker_metrics_gateway_health,
        test_broker_metrics_errors,
        test_broker_metrics_slippage_fields,
        test_broker_metrics_by_ticker,
        test_broker_metrics_recent_orders,
        test_broker_metrics_filter_by_ticker,
        test_broker_metrics_system_notes,
        test_broker_metrics_page_renders,
        test_broker_metrics_in_sidebar,
        test_all_pages_still_render,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            print(f"\n{t.__name__}:")
            t()
            passed += 1
            print(f"  PASSED")
        except Exception as e:
            failed += 1
            print(f"  FAILED: {e}")

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)}")
    if failed == 0:
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")
