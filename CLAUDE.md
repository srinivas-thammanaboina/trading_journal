# Trading Journal — Claude Instructions

## Project
Read-only web dashboard (Lottoman Journal) for the SPX Trader bot's trading journal.
FastAPI + Jinja2 + Chart.js. Reads from the bot's SQLite database in read-only mode.

## Critical Rules
- **Never write to the trading database** — always open with `?mode=ro`
- **Never commit `.env`** — contains secrets
- **Journal is read-only** — no trade placement, no risk config changes, no bot control
- **Never use `git add .` or `git add -A`** — always stage specific files

## Git / Push Workflow
Same as spx_trader. No `gh` CLI on Mac. Push using PAT embedded in remote URL:
```
git remote set-url origin "https://srinivas-thammanaboina:TOKEN@github.com/srinivas-thammanaboina/trading_journal.git"
git push
git remote set-url origin "https://github.com/srinivas-thammanaboina/trading_journal.git"
```

## Architecture
- FastAPI serves both JSON API and HTML pages (Jinja2 templates)
- SQLite connection is read-only (`file:path?mode=ro`)
- Auth: bcrypt password hash + secure session cookie
- Rate limiting on login (5 attempts/minute)
- Dark theme sidebar layout with Chart.js charts
- Reads from `spx_trader/state/trading_journal.db`

## Key Files
- `app/main.py` — FastAPI app entry point
- `app/config.py` — settings from .env
- `app/db.py` — read-only SQLite connection
- `app/auth/` — login, session, rate limiting
- `app/api/` — JSON API endpoints (trades, alerts, health, pnl, positions, stats, guru)
- `app/pages/routes.py` — HTML page routes (7 pages)
- `app/templates/` — Jinja2 templates
- `app/static/css/style.css` — dark theme styles (bump `?v=N` in base.html after CSS changes)
- `app/static/js/charts.js` — Chart.js helpers (equity curve, daily bars, donut)

## Pages
- `/dashboard` — Overview: P&L, equity curve, daily bars, open position monitor, recent trades
- `/trades` — Trade history with snapshot panel (click preview, double-click full detail)
- `/trade/{id}` — Full audit: alert → parse → risk → order → fill → P&L timeline
- `/alerts` — Alert Pipeline: parse quality, risk outcome, broker outcome, system notes
- `/analytics` — Win rate, expectancy, profit factor, max DD, per-ticker, trade calendar
- `/guru` — Signal quality vs execution quality, gap analysis, per-ticker comparison
- `/health` — Gateway status, risk controls, auto-close countdown, deployment blueprint

## Development (Local Mac)
```bash
cd /Users/srinivasthammanaboina/trading_journal
source venv/bin/activate
python run.py
# Open http://127.0.0.1:8001 — password: test123
```

## Docker / Droplet Deployment

### Droplet Info
- Droplet path: `/app/trading_journal/`
- Bot path: `/app/spx_trader/`
- docker-compose location: `/app/spx_trader/docker-compose.yml`
- docker-compose v1.29.2 (use `docker-compose`, not `docker compose`)
- Journal container name: `trading_journal`

### docker-compose.yml (journal service)
```yaml
journal:
  build: /app/trading_journal
  container_name: trading_journal
  ports:
    - "127.0.0.1:8001:8001"
  volumes:
    - /app/spx_trader/state:/data:ro
  env_file: /app/trading_journal/.env
  restart: unless-stopped
```

### .env on Droplet (`/app/trading_journal/.env`)
```
ADMIN_PASSWORD=your_strong_password
SESSION_SECRET=random_hex_string
DB_PATH=/data/trading_journal.db
HOST=0.0.0.0
PORT=8001
```
Generate session secret: `python3 -c "import secrets; print(secrets.token_hex(32))"`

### First-time Deploy
```bash
ssh root@DROPLET_IP
cd /app
git clone https://srinivas-thammanaboina:TOKEN@github.com/srinivas-thammanaboina/trading_journal.git
cd trading_journal
git remote set-url origin https://github.com/srinivas-thammanaboina/trading_journal.git

# Create .env
cat > .env << 'EOF'
ADMIN_PASSWORD=your_strong_password
SESSION_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
DB_PATH=/data/trading_journal.db
HOST=0.0.0.0
PORT=8001
EOF
chmod 600 .env

# Build and start
cd /app/spx_trader
docker-compose build journal
docker-compose up -d journal

# Verify
docker-compose ps
docker-compose logs --tail=20 journal
curl -s http://127.0.0.1:8001/login | head -5
```

### Update Deploy (after code changes)
```bash
cd /app/trading_journal && git pull
cd /app/spx_trader && docker-compose build journal && docker rm -f trading_journal && docker-compose up -d journal
```

### Caddy (HTTPS reverse proxy)
Caddy is installed on droplet (v2.11.2). Configure with domain:
```bash
cat > /etc/caddy/Caddyfile << 'EOF'
journal.yourdomain.com {
    reverse_proxy 127.0.0.1:8001
}
EOF
systemctl restart caddy
```
Requires DNS A record pointing to droplet IP. Caddy auto-provisions SSL.

### SSH Tunnel (no domain needed)
```bash
# From Mac
ssh -L 8001:127.0.0.1:8001 root@DROPLET_IP
# Then open http://127.0.0.1:8001 on Mac
```

### Firewall (UFW)
```bash
ufw allow 22    # SSH
ufw allow 80    # HTTP (Caddy redirect)
ufw allow 443   # HTTPS (Caddy)
ufw --force enable
```

### Troubleshooting
- **Container won't start**: `docker-compose logs journal` — check DB_PATH
- **"DB not found"**: Verify volume mount — `/app/spx_trader/state/trading_journal.db` must exist (created by bot on first run)
- **CSS not updating**: Bump `?v=N` in `app/templates/base.html`, rebuild container
- **ContainerConfig bug**: Same as bot — `docker rm -f trading_journal && docker-compose up -d journal`
- **Login not working**: Check `ADMIN_PASSWORD` in `.env` — it's plaintext, bcrypt hashing is done internally

## Security Notes
- Journal binds `127.0.0.1:8001` — never exposed directly to internet
- Only Caddy is public-facing (ports 80/443)
- Read-only SQLite mount (`:ro` in docker-compose)
- Separate `.env` from bot — journal never sees IBKR/Telegram/Anthropic keys
- Login rate limited: 5 attempts/minute
- Session cookies signed with SESSION_SECRET
