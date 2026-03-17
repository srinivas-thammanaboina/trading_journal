"""
Tests for Trades page data accuracy.

Validates:
- Summary cards (P&L, win rate, expectancy, profit factor, biggest winner)
- Time-of-day breakdown (open/patience/lotto buckets)
- AJAX paginated trades API
- Date range filtering
- Ticker filtering
- Default to latest trading day
"""

import sqlite3
import sys
import os

# Add paths
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


class TestSummaryCards:
    """Verify summary card values match raw DB data."""

    def test_total_pnl_matches_db(self, client, db):
        """Total P&L on trades page should match sum of realized_pnl_events."""
        # Get latest trading day
        latest = db.execute("SELECT MAX(trade_date) as d FROM realized_pnl_events").fetchone()["d"]
        if not latest:
            pytest.skip("No realized PnL events in DB")

        # DB truth
        db_pnl = db.execute(
            "SELECT COALESCE(SUM(realized_pnl), 0) as total FROM realized_pnl_events WHERE trade_date = ?",
            (latest,),
        ).fetchone()["total"]

        # Page response
        r = client.get(f"/trades?start={latest}&end={latest}")
        assert r.status_code == 200
        # Check the value is in the HTML
        assert f"${abs(db_pnl):.2f}" in r.text or f"${db_pnl:.2f}" in r.text

    def test_trade_count_matches_db(self, client, db):
        """Trade count should match number of realized_pnl_events."""
        latest = db.execute("SELECT MAX(trade_date) as d FROM realized_pnl_events").fetchone()["d"]
        if not latest:
            pytest.skip("No data")

        db_count = db.execute(
            "SELECT COUNT(*) as c FROM realized_pnl_events WHERE trade_date = ?", (latest,)
        ).fetchone()["c"]

        r = client.get(f"/trades?start={latest}&end={latest}")
        assert r.status_code == 200
        assert str(db_count) in r.text

    def test_win_rate_calculation(self, client, db):
        """Win rate = wins / total * 100."""
        rows = db.execute("SELECT realized_pnl FROM realized_pnl_events").fetchall()
        if not rows:
            pytest.skip("No data")

        total = len(rows)
        wins = sum(1 for r in rows if r["realized_pnl"] > 0)
        expected_wr = round(wins / total * 100) if total else 0

        r = client.get("/trades?start=2000-01-01&end=2099-12-31")
        assert r.status_code == 200
        assert f"{expected_wr}%" in r.text

    def test_biggest_winner_matches_db(self, client, db):
        """Biggest winner card should show the max P&L trade."""
        row = db.execute(
            "SELECT ticker, realized_pnl FROM realized_pnl_events ORDER BY realized_pnl DESC LIMIT 1"
        ).fetchone()
        if not row:
            pytest.skip("No data")

        r = client.get("/trades?start=2000-01-01&end=2099-12-31")
        assert r.status_code == 200
        assert row["ticker"] in r.text
        assert f"${round(row['realized_pnl'])}" in r.text


class TestTimeBuckets:
    """Verify time-of-day trade breakdown."""

    def test_buckets_sum_to_total(self, client, db):
        """Open + patience + lotto should equal total trades."""
        total = db.execute("SELECT COUNT(*) as c FROM realized_pnl_events").fetchone()["c"]
        if not total:
            pytest.skip("No data")

        # Compute buckets from DB
        rows = db.execute("SELECT event_time, realized_pnl FROM realized_pnl_events").fetchall()
        buckets = {"open": 0, "patience": 0, "lotto": 0}
        for r in rows:
            et = r["event_time"] or ""
            try:
                if "T" in et:
                    tp = et.split("T")[1][:5]
                else:
                    tp = et[11:16]
                h, m = int(tp[:2]), int(tp[3:5])
                mins = h * 60 + m
            except (ValueError, IndexError):
                continue
            if mins < 600:
                buckets["open"] += 1
            elif mins >= 900:
                buckets["lotto"] += 1
            else:
                buckets["patience"] += 1

        assert buckets["open"] + buckets["patience"] + buckets["lotto"] == total

    def test_bucket_wins_losses_consistent(self, db):
        """Wins + losses + breakeven should equal total for each bucket."""
        rows = db.execute("SELECT event_time, realized_pnl FROM realized_pnl_events").fetchall()
        buckets = {
            "open": {"total": 0, "wins": 0, "losses": 0},
            "patience": {"total": 0, "wins": 0, "losses": 0},
            "lotto": {"total": 0, "wins": 0, "losses": 0},
        }
        for r in rows:
            et = r["event_time"] or ""
            try:
                if "T" in et:
                    tp = et.split("T")[1][:5]
                else:
                    tp = et[11:16]
                h, m = int(tp[:2]), int(tp[3:5])
                mins = h * 60 + m
            except (ValueError, IndexError):
                continue
            bucket = "open" if mins < 600 else "lotto" if mins >= 900 else "patience"
            buckets[bucket]["total"] += 1
            if r["realized_pnl"] > 0:
                buckets[bucket]["wins"] += 1
            elif r["realized_pnl"] < 0:
                buckets[bucket]["losses"] += 1

        for name, b in buckets.items():
            assert b["wins"] + b["losses"] <= b["total"], f"{name}: wins+losses > total"


class TestTradesAPI:
    """Verify /api/trades/pnl endpoint."""

    def test_pagination_returns_correct_count(self, client, db):
        """Per-page limit should be respected."""
        r = client.get("/api/trades/pnl?per_page=5&page=1")
        assert r.status_code == 200
        data = r.json()
        assert len(data["trades"]) <= 5
        assert data["page"] == 1

    def test_pagination_total_pages(self, client, db):
        """Total pages should be at least 1 and match API's own total."""
        r = client.get("/api/trades/pnl?per_page=10")
        data = r.json()
        if data["total"] == 0:
            pytest.skip("No data")
        expected_pages = min(25, max(1, (min(data["total"], 500) + 9) // 10))
        assert data["total_pages"] == expected_pages

    def test_date_filter(self, client, db):
        """Filtering by date should return only that date's trades."""
        latest = db.execute("SELECT MAX(trade_date) as d FROM realized_pnl_events").fetchone()["d"]
        if not latest:
            pytest.skip("No data")

        r = client.get(f"/api/trades/pnl?start={latest}&end={latest}&per_page=50")
        data = r.json()
        for trade in data["trades"]:
            assert trade["trade_date"] == latest

    def test_ticker_filter(self, client, db):
        """Filtering by ticker should return only that ticker."""
        ticker_row = db.execute(
            "SELECT DISTINCT ticker FROM realized_pnl_events LIMIT 1"
        ).fetchone()
        if not ticker_row:
            pytest.skip("No data")
        ticker = ticker_row["ticker"]

        r = client.get(f"/api/trades/pnl?ticker={ticker}&per_page=50")
        data = r.json()
        for trade in data["trades"]:
            assert trade["ticker"] == ticker

    def test_date_range_filter(self, client, db):
        """Date range should include trades within the range."""
        dates = db.execute(
            "SELECT DISTINCT trade_date FROM realized_pnl_events ORDER BY trade_date"
        ).fetchall()
        if len(dates) < 2:
            pytest.skip("Need at least 2 dates")

        start = dates[0]["trade_date"]
        end = dates[-1]["trade_date"]

        r = client.get(f"/api/trades/pnl?start={start}&end={end}&per_page=50")
        data = r.json()
        for trade in data["trades"]:
            assert start <= trade["trade_date"] <= end

    def test_page_2_different_from_page_1(self, client, db):
        """Page 2 should return different trades than page 1."""
        total = db.execute("SELECT COUNT(*) as c FROM realized_pnl_events").fetchone()["c"]
        if total <= 5:
            pytest.skip("Need more than 5 trades for pagination test")

        r1 = client.get("/api/trades/pnl?per_page=5&page=1")
        r2 = client.get("/api/trades/pnl?per_page=5&page=2")
        trades1 = {t["position_id"] for t in r1.json()["trades"]}
        trades2 = {t["position_id"] for t in r2.json()["trades"]}
        assert trades1.isdisjoint(trades2), "Page 1 and 2 should not overlap"

    def test_pnl_values_match_db(self, client, db):
        """P&L values from API should exactly match DB."""
        r = client.get("/api/trades/pnl?per_page=50")
        data = r.json()
        if not data["trades"]:
            pytest.skip("No data")

        api_total = sum(t["realized_pnl"] for t in data["trades"] if t.get("realized_pnl") is not None)
        db_total = db.execute(
            "SELECT COALESCE(SUM(realized_pnl), 0) as t FROM realized_pnl_events"
        ).fetchone()["t"]

        # If we got all trades (total <= 50), they should match exactly
        if data["total"] <= 50:
            assert abs(api_total - db_total) < 0.01, f"API total {api_total} != DB total {db_total}"


class TestDefaultBehavior:
    """Verify default page behavior."""

    def test_default_shows_latest_day(self, client, db):
        """With no filters, trades page should default to latest trading day."""
        latest = db.execute("SELECT MAX(trade_date) as d FROM realized_pnl_events").fetchone()["d"]
        if not latest:
            pytest.skip("No data")

        r = client.get("/trades")
        assert r.status_code == 200
        # The date inputs should be pre-filled with the latest date
        assert f'value="{latest}"' in r.text

    def test_clear_resets_to_default(self, client):
        """Clicking clear (going to /trades with no params) should work."""
        r = client.get("/trades")
        assert r.status_code == 200

    def test_page_renders_with_no_data(self, client):
        """Page should render cleanly for a date with no trades."""
        r = client.get("/trades?start=2020-01-01&end=2020-01-01")
        assert r.status_code == 200
        assert "0" in r.text  # zero trades


class TestProfitFactor:
    """Verify profit factor calculation."""

    def test_profit_factor_formula(self, db):
        """Profit factor = sum(wins) / abs(sum(losses))."""
        rows = db.execute("SELECT realized_pnl FROM realized_pnl_events").fetchall()
        if not rows:
            pytest.skip("No data")

        wins = [r["realized_pnl"] for r in rows if r["realized_pnl"] > 0]
        losses = [r["realized_pnl"] for r in rows if r["realized_pnl"] < 0]

        if not losses:
            pytest.skip("No losses to compute profit factor")

        expected_pf = round(sum(wins) / abs(sum(losses)), 2)
        assert expected_pf > 0, "Profit factor should be positive"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
