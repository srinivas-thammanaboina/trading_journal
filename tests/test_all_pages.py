"""
Tests for all journal pages: Dashboard, Analytics, Guru, Health, Alerts, Trade Detail.

Validates:
- Pages render without errors (200 status)
- API endpoints return valid JSON
- Edge cases: empty data, missing parameters
- Key data structures present in responses

Run: python -m pytest tests/test_all_pages.py -v
"""

import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/Users/srinivasthammanaboina/spx_trader")

import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture(scope="module")
def client():
    """Authenticated test client."""
    c = TestClient(app)
    c.post("/login", data={"password": "test123"})
    return c


@pytest.fixture(scope="module")
def db():
    """Direct DB connection for verification."""
    conn = sqlite3.connect("/Users/srinivasthammanaboina/spx_trader/state/trading_journal.db")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# ── Dashboard ──────────────────────────────────────────────────────────


class TestDashboardPage:
    """Dashboard / Overview page."""

    def test_dashboard_renders(self, client):
        r = client.get("/dashboard")
        assert r.status_code == 200
        assert "Overview" in r.text or "Dashboard" in r.text

    def test_dashboard_has_pnl_section(self, client):
        r = client.get("/dashboard")
        assert r.status_code == 200
        assert "P&L" in r.text or "PnL" in r.text or "pnl" in r.text.lower()

    def test_dashboard_has_open_positions(self, client):
        r = client.get("/dashboard")
        assert r.status_code == 200
        assert "Open Position" in r.text or "position" in r.text.lower()

    def test_dashboard_has_recent_trades(self, client):
        r = client.get("/dashboard")
        assert r.status_code == 200
        assert "Recent Trades" in r.text or "trades" in r.text.lower()

    def test_dashboard_has_auto_refresh(self, client):
        """Dashboard should have 30-second auto-refresh."""
        r = client.get("/dashboard")
        assert r.status_code == 200
        assert "refresh-indicator" in r.text
        assert "setInterval" in r.text

    def test_root_redirects_to_dashboard(self, client):
        r = client.get("/", follow_redirects=False)
        assert r.status_code in (302, 307)


# ── Analytics ──────────────────────────────────────────────────────────


class TestAnalyticsPage:
    """Analytics page — charts and statistics."""

    def test_analytics_renders(self, client):
        r = client.get("/analytics")
        assert r.status_code == 200
        assert "Analytics" in r.text

    def test_analytics_has_win_rate(self, client):
        r = client.get("/analytics")
        assert r.status_code == 200
        assert "Win Rate" in r.text or "win_rate" in r.text.lower() or "win" in r.text.lower()

    def test_analytics_has_charts(self, client):
        """Should have Chart.js canvases."""
        r = client.get("/analytics")
        assert r.status_code == 200
        assert "canvas" in r.text.lower()

    def test_stats_api(self, client):
        r = client.get("/api/stats")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)

    def test_pnl_daily_api(self, client):
        r = client.get("/api/pnl/daily")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    def test_pnl_weekly_api(self, client):
        r = client.get("/api/pnl/weekly")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    def test_pnl_monthly_api(self, client):
        r = client.get("/api/pnl/monthly")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)


# ── Guru Board ─────────────────────────────────────────────────────────


class TestGuruPage:
    """Guru Board — signal quality analysis."""

    def test_guru_renders(self, client):
        r = client.get("/guru")
        assert r.status_code == 200
        assert "Guru" in r.text

    def test_guru_signals_api(self, client):
        r = client.get("/api/guru/signals")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)
        assert "signals" in data
        assert isinstance(data["signals"], list)

    def test_guru_stats_api(self, client):
        r = client.get("/api/guru/stats")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)

    def test_guru_comparison_api(self, client):
        r = client.get("/api/guru/comparison")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)

    def test_guru_signals_with_date_filter(self, client):
        r = client.get("/api/guru/signals?start=2026-03-18&end=2026-03-20")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)
        assert "signals" in data


# ── Risk & Health ──────────────────────────────────────────────────────


class TestHealthPage:
    """Risk & Health page — gateway status, risk controls."""

    def test_health_renders(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert "Health" in r.text or "Risk" in r.text

    def test_health_api(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)

    def test_health_has_gateway_status(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert "Gateway" in r.text or "gateway" in r.text.lower()

    def test_positions_api(self, client):
        r = client.get("/api/positions")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, (list, dict))


# ── Alert Pipeline ─────────────────────────────────────────────────────


class TestAlertsPage:
    """Alert Pipeline — parse quality, risk outcomes."""

    def test_alerts_renders(self, client):
        r = client.get("/alerts")
        assert r.status_code == 200
        assert "Alert" in r.text or "Pipeline" in r.text

    def test_alerts_api(self, client):
        r = client.get("/api/alerts")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)

    def test_alerts_has_parse_quality(self, client):
        r = client.get("/alerts")
        assert r.status_code == 200
        assert "Parse" in r.text or "parse" in r.text.lower()

    def test_alerts_with_date_filter(self, client):
        r = client.get("/alerts?start=2026-03-18&end=2026-03-20")
        assert r.status_code == 200

    def test_alerts_with_outcome_filter(self, client):
        r = client.get("/alerts?outcome=filled")
        assert r.status_code == 200

    def test_alerts_api_structure(self, client):
        """API should return alerts with expected keys."""
        r = client.get("/api/alerts")
        data = r.json()
        if "alerts" in data and len(data["alerts"]) > 0:
            alert = data["alerts"][0]
            assert "alert_time" in alert or "raw_text" in alert


# ── Trade Detail ───────────────────────────────────────────────────────


class TestTradeDetailPage:
    """Trade detail — full audit trail for a position."""

    def test_trade_detail_with_valid_id(self, client, db):
        """Render trade detail for a real position."""
        row = db.execute("SELECT position_id FROM executions LIMIT 1").fetchone()
        if not row:
            pytest.skip("No executions in DB")
        pid = row["position_id"]
        r = client.get(f"/trade/{pid}")
        assert r.status_code == 200
        assert pid in r.text or "Trade" in r.text

    def test_trade_detail_with_invalid_id(self, client):
        """Invalid position ID should not crash."""
        r = client.get("/trade/nonexistent-id-12345")
        # Should either 404 or render with "not found" message
        assert r.status_code in (200, 404)

    def test_trade_detail_has_fill_details(self, client, db):
        """Trade detail should show fill information."""
        row = db.execute("SELECT position_id FROM executions LIMIT 1").fetchone()
        if not row:
            pytest.skip("No executions in DB")
        pid = row["position_id"]
        r = client.get(f"/trade/{pid}")
        assert r.status_code == 200
        assert "Fill" in r.text or "fill" in r.text.lower()

    def test_trade_detail_has_timeline(self, client, db):
        """Trade detail should show order timeline."""
        row = db.execute("SELECT position_id FROM executions LIMIT 1").fetchone()
        if not row:
            pytest.skip("No executions in DB")
        pid = row["position_id"]
        r = client.get(f"/trade/{pid}")
        assert r.status_code == 200
        assert "Timeline" in r.text or "timeline" in r.text.lower()


# ── Cross-Page ─────────────────────────────────────────────────────────


class TestCrossPage:
    """Tests that span multiple pages."""

    def test_all_sidebar_links_work(self, client):
        """Every page linked in sidebar should render."""
        pages = ["/dashboard", "/trades", "/alerts", "/analytics", "/guru", "/health", "/broker-metrics"]
        for page in pages:
            r = client.get(page)
            assert r.status_code == 200, f"{page} returned {r.status_code}"

    def test_unauthenticated_redirects_to_login(self):
        """Unauthenticated requests should redirect to login."""
        c = TestClient(app)  # No login
        r = c.get("/dashboard", follow_redirects=False)
        assert r.status_code in (302, 307)

    def test_all_api_endpoints_return_json(self, client):
        """API endpoints should return valid JSON, not crash."""
        apis = [
            "/api/stats",
            "/api/pnl/daily",
            "/api/pnl/weekly",
            "/api/pnl/monthly",
            "/api/positions",
            "/api/health",
            "/api/alerts",
            "/api/guru/signals",
            "/api/guru/stats",
            "/api/guru/comparison",
        ]
        for api in apis:
            r = client.get(api)
            assert r.status_code == 200, f"{api} returned {r.status_code}"
            # Should be valid JSON
            try:
                r.json()
            except Exception:
                pytest.fail(f"{api} did not return valid JSON")
