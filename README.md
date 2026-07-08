# Blacklist Monitor

Implementation of the MVP described in `PLANEJAMENTO-blacklist-monitor.md`: IP/domain
reputation monitoring against DNSBLs (Spamhaus ZEN via DQS, Barracuda, SpamCop, PSBL,
SORBS, UCEPROTECT, SURBL, Spamhaus DBL), with ping pre-check, listing lifecycle,
notifications (email + Pushover), quick diagnostics (rDNS/FCrDNS/SPF/DKIM/DMARC/port 25),
alert rules, IP/CIDR/CSV import, RBAC with 2FA, and a dashboard matching the provided
mockup.

## Differences from the stack suggested in the plan

The original document suggests Postgres + Celery/Redis + React/Vite + Docker + Unbound.
This MVP was built to run in an environment with **only Python 3.12** (no Node/Docker
available during development), so:

- **Scheduler**: in-process APScheduler instead of Celery + Redis. Functionally equivalent
  for the MVP's volume (general check + accelerated re-check of listed IPs); swapping in
  Celery is straightforward if volume grows (the check logic is already isolated in
  `app/services/checker.py`, independent of the scheduler).
- **Database**: SQLite by default (`DATABASE_URL`), but the code is already Postgres-ready
  (just swap the URL — see `docker-compose.yml`, which already runs Postgres 16 in
  production).
- **Frontend**: instead of React/Vite, this is a server-rendered UI (FastAPI + Jinja2 +
  vanilla JS + Chart.js/Tailwind via CDN, no build step) using the same dark theme and
  screen structure as the mockup. The REST API (`/api/...`) is the same one a React
  frontend would consume — swapping the presentation layer later requires no backend
  changes.

Everything related to **Spamhaus DQS, a dedicated Unbound resolver, rate limiting, RBAC,
2FA, listing lifecycle, alert deduplication, and diagnostics** follows exactly what is in
the planning document.

## Status on this server

Running in production via **systemd** (no Docker), clean database — no demo data, just the
8 default blacklists (real engine configuration, not "demo"):

- Service: `systemctl status blacklistmonitor` (enabled on boot)
- Logs: `tail -f /var/log/blacklistmonitor.log`
- Real config: `/root/blacklistmonitor/.env` (with generated `SECRET_KEY`/`FERNET_KEY`, out
  of git)
- Database: SQLite at `/root/blacklistmonitor/blacklist_monitor.db`
- Access: `http://<server-ip>:8000` (plain HTTP for now — no domain/TLS configured)

The admin user (`admin@seudominio.com`) was created with a random password, shown once in
the startup log. Change it under **Settings → My Account** as soon as you log in (endpoint
`POST /api/auth/change-password`, already implemented).

To go further (Postgres + Unbound via Docker Compose, or TLS with your own domain via
Nginx + Let's Encrypt), see the sections below — not configured here by default to avoid
opening ports/installing Docker without confirmation.

## Running locally (dev, SQLite)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set SECRET_KEY/FERNET_KEY for production
uvicorn app.main:app --reload
```

Visit `http://localhost:8000`. On first start, the database is created and seeded with
demo data (`app/seed.py`): 5 clients, default blacklists, sample IPs with active listings,
and an admin user:

- **Email:** `admin@seudominio.com`
- **Password:** `admin123`

> Change this password (or create another admin and disable this one) before any real use.

## Running with Docker Compose (production: Postgres + Unbound)

```bash
cp .env.example .env
docker compose up -d --build
```

This brings up `api` (FastAPI + scheduler), `postgres`, and `unbound` (dedicated DNS
resolver, essential for Spamhaus/SORBS — see the production note below).

## Important production notes

- **Dedicated DNS resolver**: Spamhaus, SORBS, and other lists block or degrade queries
  coming from public resolvers (8.8.8.8, 1.1.1.1) or high-volume sources. Set
  `DNS_RESOLVERS` to point exclusively to the local Unbound (already included in
  `docker-compose.yml`), never to a public resolver.
- **Spamhaus DQS key**: required for Spamhaus ZEN/DBL. Configure it under
  Settings → Spamhaus DQS, or per individual blacklist (the field is encrypted at rest
  with Fernet).
- **Ping/ICMP**: the pre-check uses the system's `ping` binary (no raw socket/root
  required); the `Dockerfile` already installs `iputils-ping`. In environments that block
  outbound ICMP, use `tcp_fallback` mode per group.
- **Secrets**: `SECRET_KEY` (JWT) and `FERNET_KEY` (encryption of keys/passwords at rest)
  have example values in `.env.example` — generate new values before production:
  ```bash
  python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```
- **Backups**: set up daily Postgres backups (suggested retention: 30 days) — not included
  in this MVP.
- **CIDR**: import has a safety limit (`MAX_CIDR_EXPANSION`, default 1024 addresses = /22)
  to avoid accidentally expanding large blocks (e.g. /8).

## Structure

```
app/
  main.py              # FastAPI app, page routes, startup (seed + scheduler)
  config.py            # Settings (env vars)
  models.py            # SQLAlchemy ORM (the full data model from the plan)
  schemas.py           # Pydantic (request/response)
  security.py          # JWT, bcrypt, TOTP (2FA), RBAC (admin/operator/readonly)
  crypto.py            # Fernet for keys/passwords at rest
  seed.py              # Demo data (idempotent)
  services/
    cidr.py            # CIDR/range/IP expansion with a safety limit
    ping.py            # ICMP pre-check (3 modes) with cache
    dnsbl.py           # DNSBL query engine (octet/nibble reversal,
                       # per-zone rate limiting, DQS, resolver error detection)
    diagnostics.py     # rDNS/FCrDNS/SPF/DKIM/DMARC/port 25
    notifications.py   # SMTP + Pushover + alert rule evaluation
    checker.py          # Orchestrates ping + DNSBL + listing lifecycle + notification
    scheduler.py        # APScheduler: general check + accelerated re-check
  routers/              # One module per resource (auth, clients, ips, blacklists, ...)
  templates/, static/   # Server-rendered UI (dark theme from the mockup)
```

## API

All read routes used by the dashboard are public (read-only); create/update/delete
requires a JWT token (`POST /api/auth/login`) with `operator` or `admin` role depending on
the resource. Auto-generated docs at `/docs`.
