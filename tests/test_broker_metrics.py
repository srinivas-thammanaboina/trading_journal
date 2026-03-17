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
    assert "latency" in data
    assert "slippage" in data
    assert "by_ticker" in data
    assert "recent_orders" in data
    assert "notes" in data
    assert "fill_types" in data
    print(f"  API: {data['latency']['total_orders']} orders, avg latency {data['latency']['avg_latency_ms']}ms")


def test_broker_metrics_latency_fields():
    """Latency metrics have all expected fields."""
    _login()
    data = client.get("/api/broker-metrics").json()
    lat = data["latency"]
    for field in ["total_orders", "avg_latency_ms", "min_latency_ms", "max_latency_ms",
                  "under_2s", "_2_to_5s", "_5_to_10s", "_10_to_20s", "over_20s", "escalated_count"]:
        assert field in lat, f"Missing latency field: {field}"
    assert lat["total_orders"] > 0
    print(f"  Latency: min={lat['min_latency_ms']}ms max={lat['max_latency_ms']}ms")


def test_broker_metrics_slippage_fields():
    """Slippage metrics have all expected fields."""
    _login()
    data = client.get("/api/broker-metrics").json()
    slip = data["slippage"]
    for field in ["total_with_quote", "avg_slippage", "avg_slippage_vs_signal",
                  "avg_spread", "avg_quote_age_ms", "stale_quotes"]:
        assert field in slip, f"Missing slippage field: {field}"
    print(f"  Slippage: avg=${slip['avg_slippage']}, spread=${slip['avg_spread']}")


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
    assert "Broker Execution Metrics" in r.text
    assert "Latency Distribution" in r.text
    assert "Slippage Analysis" in r.text
    assert "Per-Ticker Breakdown" in r.text
    assert "System Notes" in r.text
    print(f"  Page: {len(r.text)} bytes")


def test_broker_metrics_in_sidebar():
    """Broker Metrics link appears in sidebar."""
    _login()
    r = client.get("/dashboard")
    assert "Broker Metrics" in r.text
    print("  Sidebar: Broker Metrics link present")


def test_all_pages_still_render():
    """Regression: all existing pages still render after adding broker metrics."""
    _login()
    pages = {
        "/dashboard": "Bot Trades Overview",
        "/trades": "Trade History",
        "/alerts": "Alert",
        "/analytics": "Analytics",
        "/guru": "Guru vs Bot",
        "/health": "Risk Dashboard",
        "/broker-metrics": "Broker Execution Metrics",
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
