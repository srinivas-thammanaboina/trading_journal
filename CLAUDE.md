# Trading Journal — Claude Instructions

## Project
Read-only web dashboard for the SPX Trader bot's trading journal.
FastAPI + Jinja2 + Chart.js. Reads from the bot's SQLite database in read-only mode.

## Critical Rules
- **Never write to the trading database** — always open with `?mode=ro`
- **Never commit `.env`** — contains secrets
- **Journal is read-only** — no trade placement, no risk config changes, no bot control

## Architecture
- FastAPI serves both JSON API and HTML pages (Jinja2 templates)
- SQLite connection is read-only (`file:path?mode=ro`)
- Auth: bcrypt password hash + secure session cookie
- Rate limiting on login (5 attempts/minute)
- Dark theme dashboard with Chart.js charts

## Key Files
- `app/main.py` — FastAPI app entry point
- `app/config.py` — settings from .env
- `app/db.py` — read-only SQLite connection
- `app/auth/` — login, session, rate limiting
- `app/api/` — JSON API endpoints
- `app/pages/routes.py` — HTML page routes
- `app/templates/` — Jinja2 templates
- `app/static/` — CSS + JS

## Development
```bash
cd /Users/srinivasthammanaboina/trading_journal
source venv/bin/activate
python run.py
```

## Deployment
On Droplet, runs alongside spx_trader via docker-compose.
Caddy reverse-proxies HTTPS → 127.0.0.1:8001.
