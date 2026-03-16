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

    return {"alerts": rows, "page": page, "total_pages": total_pages, "total": total}
