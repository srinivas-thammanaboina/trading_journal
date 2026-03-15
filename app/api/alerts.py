"""GET /api/alerts — alert history with parse/risk/outcome."""

from datetime import date

from fastapi import APIRouter, Query

from app.db import get_db

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/alerts")
async def get_alerts(
    trade_date: str | None = Query(None, description="YYYY-MM-DD"),
    outcome: str | None = Query(None, description="filled, rejected, ignored, duplicate"),
    limit: int = Query(100, ge=1, le=1000),
):
    conn = get_db()
    sql = "SELECT * FROM alerts WHERE 1=1"
    params: list = []

    if trade_date:
        sql += " AND trade_date = ?"
        params.append(trade_date)

    if outcome:
        sql += " AND outcome = ?"
        params.append(outcome)

    sql += " ORDER BY alert_time DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]
