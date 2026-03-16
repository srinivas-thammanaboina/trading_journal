# Trading Journal — Droplet Operations Guide

Quick reference for managing the Trading Journal on the DigitalOcean droplet.

## Variables

| Variable | Description | Example |
|---|---|---|
| `DROPLET_IP` | Your droplet's public IP | `24.199.94.205` |
| `BOT_DIR` | Bot code directory (has docker-compose.yml) | `/app/spx_trader` |
| `JOURNAL_DIR` | Journal code directory | `/app/trading_journal` |
| `DB_PATH` | SQLite database (written by bot, read by journal) | `BOT_DIR/state/trading_journal.db` |

---

## Access

### SSH tunnel (no domain setup)
```bash
ssh -L 8001:127.0.0.1:8001 root@DROPLET_IP
# Open http://127.0.0.1:8001 in browser
```

### With domain + HTTPS (Caddy)
```
https://journal.yourdomain.com
```

---

## Deploy

### First-time setup

```bash
# 1. Clone on droplet
cd /app
git clone https://github.com/YOUR_USERNAME/trading_journal.git

# 2. Create .env
cat > JOURNAL_DIR/.env << 'EOF'
ADMIN_PASSWORD=YOUR_STRONG_PASSWORD
SESSION_SECRET=RANDOM_HEX_STRING
DB_PATH=/data/trading_journal.db
HOST=0.0.0.0
PORT=8001
EOF
chmod 600 JOURNAL_DIR/.env

# Generate session secret:
python3 -c "import secrets; print(secrets.token_hex(32))"

# 3. Add journal service to BOT_DIR/docker-compose.yml:
#   journal:
#     build: /app/trading_journal
#     container_name: trading_journal
#     ports:
#       - "127.0.0.1:8001:8001"
#     volumes:
#       - /app/spx_trader/state:/data:ro
#     env_file: /app/trading_journal/.env
#     restart: unless-stopped

# 4. Build and start
cd BOT_DIR
docker-compose build journal
docker-compose up -d journal
```

### Update (after pushing new code)

```bash
cd JOURNAL_DIR && git pull
cd BOT_DIR
docker-compose build journal
docker rm -f trading_journal
docker-compose up -d journal
```

---

## Health Checks

### Container status
```bash
cd BOT_DIR && docker-compose ps
```

### Journal logs
```bash
docker-compose logs --tail=20 journal
```

### Test endpoint
```bash
curl -s http://127.0.0.1:8001/login | head -3
```

### Check database connectivity
```bash
sqlite3 DB_PATH "SELECT trade_date, gateway_connected, updated_at FROM system_state ORDER BY updated_at DESC LIMIT 1;"
```

---

## Common Operations

### Restart without rebuild
```bash
cd BOT_DIR
docker rm -f trading_journal
docker-compose up -d journal
```

### Rebuild after code change
```bash
cd JOURNAL_DIR && git pull
cd BOT_DIR
docker-compose build journal
docker rm -f trading_journal
docker-compose up -d journal
```

### Change password
```bash
nano JOURNAL_DIR/.env
# Update ADMIN_PASSWORD
cd BOT_DIR && docker rm -f trading_journal && docker-compose up -d journal
```

---

## Security Checklist

- [ ] `.env` has `chmod 600` permissions
- [ ] Journal binds to `127.0.0.1:8001` only (not `0.0.0.0:8001`)
- [ ] Firewall active: only ports 22, 80, 443 open
- [ ] HTTPS via Caddy (if using domain)
- [ ] Strong admin password (not default `test123`)
- [ ] Journal DB connection is read-only (`?mode=ro`)
- [ ] Bot and journal use separate `.env` files

---

## HTTPS Setup (Caddy)

```bash
# Install
apt install -y caddy

# Configure
cat > /etc/caddy/Caddyfile << 'EOF'
journal.yourdomain.com {
    reverse_proxy 127.0.0.1:8001
}
EOF
systemctl restart caddy
```

Requires: DNS A record `journal.yourdomain.com → DROPLET_IP`

---

## Troubleshooting

### "Internal Server Error" on a page
```bash
docker-compose logs --tail=30 journal
# Look for Python traceback
```

### Journal shows stale data
- Journal reads SQLite in read-only mode — it shows what the bot wrote
- If bot is stopped/disconnected, data stops updating
- Check bot health: `docker-compose logs --tail=10 spx-trader`

### "Address already in use" on port 8001
```bash
docker rm -f trading_journal
docker-compose up -d journal
```

### Schema mismatch after bot upgrade
- Bot adds new columns on startup
- Journal reads whatever columns exist
- If journal crashes on missing column, restart the bot first to run migrations

### Database locked error
- SQLite WAL mode allows concurrent read + write
- If persistent, check for zombie processes: `fuser DB_PATH`
