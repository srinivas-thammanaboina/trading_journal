# Trading Journal

Read-only web dashboard for the [SPX Trader](https://github.com/srinivas-thammanaboina/spx_trader) automated options trading bot. Provides trade audit, performance analytics, guru signal tracking, and operational health monitoring.

## Architecture

```
Internet → Caddy (HTTPS) → FastAPI on 127.0.0.1:8001
                                 ↓
                    SQLite (read-only connection)
                                 ↑
                    SPX Trader bot (writes)
```

- **Read-only** — journal never writes to the bot's database
- **Single SQLite file** — no separate database server
- **Auth** — bcrypt password + rate-limited login + session cookies
- **Dark theme** — sidebar layout, Chart.js charts

## Pages

| Page | Route | Description |
|------|-------|-------------|
| Overview | `/dashboard` | Today's P&L, equity curve, daily bars, open position monitor, recent trades |
| Trades | `/trades` | Trade history with filters + click-to-preview snapshot panel |
| Trade Detail | `/trade/{id}` | Full audit: alert → parse → risk → order → fill → P&L timeline |
| Alert Pipeline | `/alerts` | Parse quality, risk outcome, broker outcome, system notes, alert audit log |
| Analytics | `/analytics` | Win rate, expectancy, profit factor, max drawdown, per-ticker breakdown, trade calendar |
| Guru Board | `/guru` | Signal quality vs execution quality, gap analysis, per-ticker comparison |
| Risk & Health | `/health` | Gateway status, risk controls, auto-close countdown, deployment blueprint |

## Quick Start

```bash
# 1. Clone and setup
git clone https://github.com/srinivas-thammanaboina/trading_journal.git
cd trading_journal
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env: set ADMIN_PASSWORD, SESSION_SECRET, DB_PATH

# 3. Run
python run.py
# Open http://127.0.0.1:8001
```

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `ADMIN_PASSWORD` | Login password (bcrypt hashed internally) | `test123` |
| `SESSION_SECRET` | Cookie signing key | random |
| `DB_PATH` | Path to SPX Trader's SQLite journal DB | `../spx_trader/state/trading_journal.db` |
| `HOST` | Bind address | `127.0.0.1` |
| `PORT` | Bind port | `8001` |

## Project Structure

```
trading_journal/
├── app/
│   ├── main.py              # FastAPI app entry point
│   ├── config.py             # Settings from .env
│   ├── db.py                 # Read-only SQLite connection
│   ├── auth/
│   │   ├── routes.py         # POST /login, /logout
│   │   ├── security.py       # bcrypt + rate limiter
│   │   └── middleware.py     # Session auth check
│   ├── api/                  # JSON API endpoints
│   │   ├── trades.py         # GET /api/trades, /api/trade/{id}
│   │   ├── alerts.py         # GET /api/alerts
│   │   ├── health.py         # GET /api/health
│   │   ├── pnl.py            # GET /api/pnl/daily|weekly|monthly
│   │   ├── positions.py      # GET /api/positions
│   │   ├── stats.py          # GET /api/stats
│   │   └── guru.py           # GET /api/guru/stats|comparison
│   ├── pages/
│   │   └── routes.py         # Server-rendered HTML (Jinja2)
│   ├── templates/            # Jinja2 HTML templates
│   └── static/
│       ├── css/style.css     # Dark theme styles
│       └── js/charts.js      # Chart.js helpers
├── run.py                    # Uvicorn launcher
├── Dockerfile
├── requirements.txt
└── .env.example
```

## SQLite Tables (read from bot)

| Table | Purpose |
|-------|---------|
| `alerts` | Every raw alert with parse result and outcome |
| `positions` | Currently open positions |
| `orders` | Every order placed with IBKR |
| `executions` | Fill events (deduped by execution ID) |
| `realized_pnl_events` | One row per realized P&L event |
| `guru_signals` | Every guru BUY/CLOSE signal with execution status |
| `system_state` | Daily bot status (P&L, halt flag, timestamps) |
| `daily_summaries` | EOD report cards |

## Deployment

Add to existing `docker-compose.yml` alongside the bot:

```yaml
journal:
  build: ./trading_journal
  ports:
    - "127.0.0.1:8001:8001"
  volumes:
    - ./spx_trader/state:/data:ro
  env_file: ./trading_journal/.env
```

Then reverse-proxy with Caddy:

```
journal.yourdomain.com {
    reverse_proxy 127.0.0.1:8001
}
```

## Security

- Journal has **no write access** to bot state — even if compromised, trading is unaffected
- All services bind to `127.0.0.1` — only Caddy is public-facing
- Login rate-limited to 5 attempts/minute
- Session cookies are signed and expire

## Related

- [spx_trader](https://github.com/srinivas-thammanaboina/spx_trader) — the trading bot this journal monitors
