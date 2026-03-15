"""GET /api/pnl — P&L queries (daily, weekly, monthly)."""

from datetime import date, timedelta

from fastapi import APIRouter, Query

from app.db import get_db

router = APIRouter(prefix="/api/pnl", tags=["pnl"])


@router.get("/daily")
async def daily_pnl(
    start: str | None = Query(None),
    end: str | None = Query(None),
    days: int = Query(30, ge=1, le=365),
):
    conn = get_db()
    if not start:
        start = (date.today() - timedelta(days=days)).isoformat()
    if not end:
        end = date.today().isoformat()

    rows = conn.execute(
        """SELECT trade_date,
                  SUM(realized_pnl) as total_pnl,
                  COUNT(*) as trade_count
           FROM realized_pnl_events
           WHERE trade_date BETWEEN ? AND ?
           GROUP BY trade_date
           ORDER BY trade_date""",
        (start, end),
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/weekly")
async def weekly_pnl(weeks: int = Query(12, ge=1, le=52)):
    conn = get_db()
    start = (date.today() - timedelta(weeks=weeks)).isoformat()

    rows = conn.execute(
        """SELECT strftime('%Y-W%W', trade_date) as week,
                  SUM(realized_pnl) as total_pnl,
                  COUNT(*) as trade_count
           FROM realized_pnl_events
           WHERE trade_date >= ?
           GROUP BY week
           ORDER BY week""",
        (start,),
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/monthly")
async def monthly_pnl(months: int = Query(6, ge=1, le=24)):
    conn = get_db()
    start = (date.today() - timedelta(days=months * 30)).isoformat()

    rows = conn.execute(
        """SELECT strftime('%Y-%m', trade_date) as month,
                  SUM(realized_pnl) as total_pnl,
                  COUNT(*) as trade_count
           FROM realized_pnl_events
           WHERE trade_date >= ?
           GROUP BY month
           ORDER BY month""",
        (start,),
    ).fetchall()
    return [dict(r) for r in rows]
