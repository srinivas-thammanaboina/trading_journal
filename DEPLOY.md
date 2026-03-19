# Deployment Guide — Lottoman Trade Bot + Journal

## Architecture

```
Droplet
├── $BOT_DIR/              # spx_trader (trading bot)
│   ├── docker-compose.yml # orchestrates all services
│   └── state/trading_journal.db
├── $JOURNAL_DIR/          # trading_journal (web dashboard)
│   └── .env               # journal secrets
├── IB Gateway             # IBKR connection (Docker container)
└── Caddy (optional)       # HTTPS reverse proxy
```

**Key principle**: Bot writes to SQLite, journal reads it (read-only mount). Journal can never affect trading.

---

## Variables

| Variable | Description | Example |
|---|---|---|
| `$DROPLET_IP` | Droplet public IP | `$DROPLET_IP` |
| `$BOT_DIR` | Bot repo path on droplet | `/app/spx_trader` |
| `$JOURNAL_DIR` | Journal repo path on droplet | `/app/trading_journal` |
| `$BOT_CONTAINER` | Bot container name | `spx_trader_spx-trader_1` |
| `$JOURNAL_CONTAINER` | Journal container name | `trading_journal` |
| `$GITHUB_USER` | GitHub username | `srinivas-thammanaboina` |
| `$PAT` | GitHub classic PAT (repo scope) | `ghp_xxxxx` |

---

## Initial Setup (one-time)

### 1. Clone repos on droplet

```bash
ssh root@$DROPLET_IP

cd /app
git clone https://$GITHUB_USER:$PAT@github.com/$GITHUB_USER/spx_trader.git
git clone https://$GITHUB_USER:$PAT@github.com/$GITHUB_USER/trading_journal.git

# Reset URLs to clean form
cd $BOT_DIR && git remote set-url origin https://github.com/$GITHUB_USER/spx_trader.git
cd $JOURNAL_DIR && git remote set-url origin https://github.com/$GITHUB_USER/trading_journal.git
```

### 2. Create journal .env

```bash
cat > $JOURNAL_DIR/.env << 'EOF'
ADMIN_PASSWORD=<strong-password-here>
SESSION_SECRET=<random-hex-string>
DB_PATH=/data/trading_journal.db
HOST=0.0.0.0
PORT=8001
EOF
chmod 600 $JOURNAL_DIR/.env
```

Generate session secret:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 3. Add journal service to docker-compose.yml

Add to `$BOT_DIR/docker-compose.yml`:

```yaml
  journal:
    build: $JOURNAL_DIR
    container_name: $JOURNAL_CONTAINER
    ports:
      - "127.0.0.1:8001:8001"
    volumes:
      - $BOT_DIR/state:/data:ro    # read-only mount
    env_file: $JOURNAL_DIR/.env
    restart: unless-stopped
```

### 4. Build and start all services

```bash
cd $BOT_DIR
docker-compose build
docker-compose up -d
```

### 5. Verify

```bash
docker-compose ps
docker-compose logs --tail=20 spx-trader
docker-compose logs --tail=10 journal
curl -s http://127.0.0.1:8001/login | head -3
```

### 6. One-time DB migration (if upgrading)

```bash
sqlite3 $BOT_DIR/state/trading_journal.db "PRAGMA table_info(system_state);" | grep gateway || \
sqlite3 $BOT_DIR/state/trading_journal.db "ALTER TABLE system_state ADD COLUMN gateway_connected INTEGER DEFAULT 1;"
```

---

## Routine Deployments

### Deploy bot only

```bash
cd $BOT_DIR && git pull
docker-compose build spx-trader
docker rm -f $BOT_CONTAINER
docker-compose up -d --no-deps spx-trader
```

### Deploy journal only

```bash
cd $JOURNAL_DIR && git pull
cd $BOT_DIR
docker-compose build journal
docker rm -f $JOURNAL_CONTAINER
docker-compose up -d journal
```

### Deploy both

```bash
cd $BOT_DIR && git pull
cd $JOURNAL_DIR && git pull
cd $BOT_DIR
docker-compose build
docker rm -f $BOT_CONTAINER $JOURNAL_CONTAINER
docker-compose up -d
```

### Verify after deploy

```bash
docker-compose ps                              # all services Up
docker-compose logs --tail=30 spx-trader        # bot healthy
docker-compose logs --tail=10 journal           # journal started
curl -s http://127.0.0.1:8001/login | head -3   # journal responding
```

---

## Pushing Code (from Mac)

### Bot (spx_trader)

```bash
cd $LOCAL_BOT_DIR
git remote set-url origin "https://$GITHUB_USER:$PAT@github.com/$GITHUB_USER/spx_trader.git"
git push
git remote set-url origin "https://github.com/$GITHUB_USER/spx_trader.git"
```

### Journal (trading_journal)

```bash
cd $LOCAL_JOURNAL_DIR
git remote set-url origin "https://$GITHUB_USER:$PAT@github.com/$GITHUB_USER/trading_journal.git"
git push
git remote set-url origin "https://github.com/$GITHUB_USER/trading_journal.git"
```

---

## Accessing Journal

### SSH tunnel (no domain needed)

```bash
ssh -L 8001:127.0.0.1:8001 root@$DROPLET_IP
# Open http://127.0.0.1:8001 in browser
```

### HTTPS with Caddy (recommended for production)

```bash
# Install Caddy on droplet
apt install -y caddy

# Configure
cat > /etc/caddy/Caddyfile << 'EOF'
$JOURNAL_DOMAIN {
    reverse_proxy 127.0.0.1:8001
}
EOF

systemctl enable caddy
systemctl restart caddy
```

Requires DNS A record: `$JOURNAL_DOMAIN` → `$DROPLET_IP`

---

## Firewall

```bash
ufw allow 22    # SSH
ufw allow 80    # HTTP (Caddy redirect)
ufw allow 443   # HTTPS (Caddy)
ufw --force enable
```

**Never expose port 8001 directly** — always use Caddy or SSH tunnel.

---

## Monitoring

### Check bot status
```bash
docker-compose logs --tail=50 spx-trader
```

### Check journal status
```bash
docker-compose logs --tail=20 journal
```

### Query DB directly
```bash
sqlite3 $BOT_DIR/state/trading_journal.db "
SELECT trade_date, gateway_connected, updated_at FROM system_state ORDER BY updated_at DESC LIMIT 3;
SELECT COUNT(*) as positions FROM positions;
SELECT COUNT(*) as alerts FROM alerts;
SELECT COUNT(*) as executions FROM executions;
"
```

### Restart a single service
```bash
cd $BOT_DIR
docker-compose restart spx-trader   # bot
docker-compose restart journal      # journal
```

---

## Troubleshooting

| Issue | Fix |
|---|---|
| Journal shows "Offline" | Bot hasn't written `system_state` yet. Wait 30s or check bot logs |
| "Address already in use" on local | `lsof -ti:8001 \| xargs kill -9` |
| docker-compose ContainerConfig error | `docker rm -f $CONTAINER_NAME` then `docker-compose up -d` |
| DB locked error | Only one writer (bot). Check no stale processes: `fuser $BOT_DIR/state/trading_journal.db` |
| Gateway disconnected | Check IB Gateway container: `docker-compose logs --tail=20 ib-gateway` |
| Journal can't read DB | Verify volume mount is correct and `:ro` flag is set |

---

## Security Checklist

- [ ] Journal `.env` has `chmod 600`
- [ ] Journal binds to `127.0.0.1:8001` (not `0.0.0.0:8001` publicly)
- [ ] Firewall active (ports 22, 80, 443 only)
- [ ] Bot `.env` never committed to git
- [ ] Journal reads DB in read-only mode (`?mode=ro`)
- [ ] Caddy configured for HTTPS (if using domain)
- [ ] SSH key-only auth (password auth disabled)
- [ ] Strong `ADMIN_PASSWORD` in journal `.env`
