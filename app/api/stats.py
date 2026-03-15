"""GET /api/stats — win/loss statistics, per-ticker breakdown."""

from fastapi import APIRouter, Query

from app.db import get_db

router = APIRouter(prefix="/api", tags=["api"])


def _compute_stats(rows) -> dict:
    pnls = [r["realized_pnl"] for r in rows]
    if not pnls:
        return {
            "wins": 0, "losses": 0, "breakeven": 0, "total": 0,
            "win_rate": 0.0, "total_pnl": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
            "best_trade": 0.0, "worst_trade": 0.0,
        }
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    return {
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len([p for p in pnls if p == 0]),
        "total": len(pnls),
        "win_rate": round(len(wins) / len(pnls) * 100, 1),
        "total_pnl": round(sum(pnls), 2),
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "best_trade": round(max(pnls), 2),
        "worst_trade": round(min(pnls), 2),
    }


@router.get("/stats")
async def get_stats(
    start: str | None = Query(None),
    end: str | None = Query(None),
):
    conn = get_db()
    sql = "SELECT realized_pnl, ticker FROM realized_pnl_events WHERE 1=1"
    params: list = []
    if start:
        sql += " AND trade_date >= ?"
        params.append(start)
    if end:
        sql += " AND trade_date <= ?"
        params.append(end)

    rows = conn.execute(sql, params).fetchall()
    overall = _compute_stats(rows)

    # Per-ticker breakdown
    tickers: dict[str, list] = {}
    for r in rows:
        tickers.setdefault(r["ticker"], []).append(r)

    by_ticker = {t: _compute_stats(rs) for t, rs in tickers.items()}

    return {"overall": overall, "by_ticker": by_ticker}
