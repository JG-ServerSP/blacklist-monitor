# Blacklist Monitor

IP/domain reputation monitoring against DNSBLs (Spamhaus ZEN via DQS, Barracuda, SpamCop,
PSBL, SORBS, UCEPROTECT, SURBL, Spamhaus DBL): ping pre-check, listing lifecycle tracking,
email + Pushover notifications, quick diagnostics (rDNS/FCrDNS/SPF/DKIM/DMARC/port 25),
alert rules, IP/CIDR/CSV import, RBAC with 2FA, and a dark-themed dashboard. Built with
FastAPI + SQLAlchemy + a server-rendered UI (no Node/build step required).

This guide assumes no prior experience — every command is spelled out. If you get stuck,
see [Troubleshooting](#troubleshooting) near the end.

---

## 1. Requirements

- **Linux or macOS** (or Windows using WSL). Commands below assume a Debian/Ubuntu-style
  Linux shell; adjust the package-manager commands if you're on something else.
- **Python 3.12 or newer.**
- **A terminal.** On Linux, open "Terminal" from your applications menu. On macOS, open
  "Terminal" (search for it with Spotlight, `Cmd+Space`). On Windows, install
  [WSL](https://learn.microsoft.com/windows/wsl/install) first and use its Linux terminal —
  the commands in this guide won't work in plain `cmd.exe` or PowerShell.
- **git** — only needed if you pick Option B below to download the code; you can skip
  installing it if you use Option A.

Check what you already have:

```bash
python3 --version
git --version
```

If `python3` says "command not found", install it:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
```

---

## 2. Install — step by step (local/dev, SQLite)

### Step 1 — Download the code

Pick **one** of the two options below.

#### Option A — Download the ZIP (no git needed, easiest)

1. Open **https://github.com/JG-ServerSP/blacklist-monitor** in your browser.
2. Click the green **`<> Code`** button, then click **Download ZIP**.
3. Find the downloaded file (usually in your `Downloads` folder) and extract it:
   - **Linux/macOS terminal:**
     ```bash
     cd ~/Downloads
     unzip blacklist-monitor-main.zip
     cd blacklist-monitor-main
     ```
     (If `unzip` says "command not found": `sudo apt install -y unzip`, then try again.)
   - **Or using a file manager:** right-click the ZIP file → "Extract Here" / "Extract
     All", then open a terminal inside the extracted folder (most file managers have an
     "Open Terminal Here" option when you right-click inside the folder).
4. Confirm you're in the right place — this command should list files like `app`,
   `requirements.txt`, `README.md`:
   ```bash
   ls
   ```

#### Option B — Clone with git

If you have `git` installed (see [Requirements](#1-requirements)):

```bash
git clone https://github.com/JG-ServerSP/blacklist-monitor.git
cd blacklist-monitor
```

### Step 2 — Create an isolated Python environment ("virtual environment")

This keeps this project's Python packages separate from the rest of your system.

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Your terminal prompt should now start with `(.venv)`. You'll need to run
`source .venv/bin/activate` again every time you open a new terminal to work on this
project.

### Step 3 — Install the Python dependencies

```bash
pip install -r requirements.txt
```

This downloads and installs everything the app needs (FastAPI, SQLAlchemy, etc.) — it can
take a minute or two.

### Step 4 — Create your configuration file

The app reads its settings from a file named `.env`. A template is provided:

```bash
cp .env.example .env
```

### Step 5 — Generate real secret keys

`.env` ships with placeholder values for `SECRET_KEY` and `FERNET_KEY`. These protect login
sessions and encrypted data at rest — **do not skip this step**, even for local testing.

Generate a `SECRET_KEY`:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Generate a `FERNET_KEY`:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Each command prints one line of random text. Open `.env` in a text editor (e.g.
`nano .env`) and replace the placeholder value after `SECRET_KEY=` and `FERNET_KEY=` with
the values you just generated. Save and close the file.

### Step 6 — Start the app

```bash
uvicorn app.main:app --reload
```

You should see log lines ending with something like:

```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
...
=== Admin user created: admin@example.com / generated password: aB3xY... ===
Save this password now — it will not be shown again. Change it after your first login.
```

**Copy that generated password somewhere safe right now** — it's shown only once. If you
missed it, see [Troubleshooting](#troubleshooting) below on how to reset it.

### Step 7 — Open the app and log in

Open your browser at **http://localhost:8000** (or `http://<server-ip>:8000` if you
installed this on a remote server). Log in with:

- **Email:** `admin@example.com` (or whatever you set as `ADMIN_EMAIL` in `.env`)
- **Password:** the one printed in the terminal in Step 6

### Step 8 — Change the admin password

Go to **Settings → My Account** and set a new password immediately.

That's it — the app is running with an empty inventory (no demo IPs/clients), just the 8
default blacklists. Keep the terminal window open (or move on to [running it as a
background service](#4-running-permanently-systemd) so it survives closing the terminal /
server reboots).

---

## 3. Setting things up

### Add IPs or domains to monitor

Use the **Monitored IPs** / **Domains** pages in the UI. You can add a single IP, a CIDR
block (e.g. `203.0.113.0/24`), an IP range (e.g. `203.0.113.1-203.0.113.50`), or import a
CSV file. Large CIDR blocks are capped by `MAX_CIDR_EXPANSION` in `.env` (default: 1024
addresses, i.e. a `/22`) as a safety net against accidentally importing something like a
`/8`.

### Spamhaus DQS key (required for Spamhaus ZEN/DBL)

Spamhaus ZEN and Spamhaus DBL require a free DQS (Data Query Service) key to work — without
it, those two blacklists will show a resolution error instead of a result (this is safe: it
just means "not checked", never a false positive). Get a key at
[spamhaus.org](https://www.spamhaus.org/) and set it under **Settings → Spamhaus DQS**, or
per individual blacklist.

### Email / Pushover notifications

Under **Settings**, configure SMTP (for email alerts) and/or a Pushover application token.
Then create at least one **Alert Rule** (severity, blacklist, client, or group conditions +
which channel to notify) so the app knows when and where to send alerts.

### Dedicated DNS resolver (recommended for real use)

Spamhaus, SORBS, and other lists block or degrade queries coming from public DNS resolvers
(8.8.8.8, 1.1.1.1) or from resolvers that get high query volume. If you're monitoring more
than a handful of IPs, set `DNS_RESOLVERS` in `.env` to point at a dedicated resolver (e.g.
a local [Unbound](https://nlnetlabs.nl/projects/unbound/about/) instance — one is already
wired up in `docker-compose.yml`), never at a shared public resolver.

---

## 4. Running permanently (systemd)

Running `uvicorn` directly in a terminal stops as soon as you close that terminal. For a
server that should keep running, use `systemd`.

### Step 1 — Create the service file

```bash
sudo nano /etc/systemd/system/blacklistmonitor.service
```

Paste this in, replacing `/path/to/blacklist-monitor` and `youruser` with your actual
install path and the Linux user that should run it (using `root` works too, but a
dedicated non-root user is safer):

```ini
[Unit]
Description=Blacklist Monitor (FastAPI)
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/blacklist-monitor
EnvironmentFile=/path/to/blacklist-monitor/.env
ExecStart=/path/to/blacklist-monitor/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5
StandardOutput=append:/var/log/blacklistmonitor.log
StandardError=append:/var/log/blacklistmonitor.log

[Install]
WantedBy=multi-user.target
```

### Step 2 — Enable and start it

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now blacklistmonitor
```

### Step 3 — Check it's running

```bash
sudo systemctl status blacklistmonitor
tail -f /var/log/blacklistmonitor.log
```

From now on, the app starts automatically on boot and restarts itself if it crashes. After
editing code or `.env`, apply changes with:

```bash
sudo systemctl restart blacklistmonitor
```

---

## 5. Running with Docker Compose (Postgres + Unbound, alternative to systemd)

If you have Docker installed and want the fuller production stack (Postgres instead of
SQLite, plus a dedicated Unbound DNS resolver):

```bash
cp .env.example .env   # if you haven't already; then set SECRET_KEY/FERNET_KEY as in step 2.5 above
docker compose up -d --build
```

This starts three containers: `api` (the app + scheduler), `postgres`, and `unbound`. Check
logs with `docker compose logs -f api`.

The `api` image runs as an unprivileged user (not root), with `CAP_NET_RAW` granted only to
the `ping` binary it shells out to for reachability checks.

---

## 6. Environment variables reference

All variables live in `.env` (copied from `.env.example`). Full list with defaults:

| Variable | Default | What it does |
|---|---|---|
| `SECRET_KEY` | *(placeholder — change it)* | Signs JWT login tokens. |
| `FERNET_KEY` | *(placeholder — change it)* | Encrypts secrets at rest (blacklist API keys, etc.). |
| `DATABASE_URL` | `sqlite:///./blacklist_monitor.db` | SQLite by default; use a `postgresql+psycopg2://...` URL for Postgres. |
| `ADMIN_EMAIL` | `admin@example.com` | Email of the admin account auto-created on first boot. |
| `ADMIN_PASSWORD` | *(empty = random)* | Set this to choose the initial admin password; leave empty to get a random one printed in the log. |
| `DNS_RESOLVERS` | *(empty = system resolver)* | Comma-separated resolver IPs; point at a dedicated resolver in production. |
| `SPAMHAUS_DQS_KEY` | *(empty)* | Required for Spamhaus ZEN/DBL to work; can also be set per-blacklist in the UI. |
| `DEFAULT_CHECK_INTERVAL_MINUTES` | `60` | How often each IP/domain is re-checked. |
| `LISTED_IP_RECHECK_MINUTES` | `15` | Faster re-check interval for IPs currently listed. |
| `MAX_CIDR_EXPANSION` | `1024` | Safety cap on addresses expanded from one CIDR/range import. |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_USE_TLS` / `SMTP_FROM` | *(empty)* | Outbound email for notifications. |
| `PUSHOVER_APP_TOKEN` | *(empty)* | Pushover application token for push notifications. |
| `CORS_ORIGINS` | `*` | Allowed origins for the API. |
| `LANGUAGE` | `en` | UI language: `pt-BR`, `en`, `es`, `fr`, or `de`. Users can override this individually under Settings → My Account. |
| `LOG_LEVEL` | `info` | Log verbosity: `off`, `error`, `info`, or `debug`. Changeable at runtime under Settings, no restart needed. |

---

## Troubleshooting

**"command not found: python3" / "command not found: git"**
Install them first — see [Requirements](#1-requirements).

**I lost the generated admin password**
Stop the app, delete the admin user row from the database, and restart — a new random
password will be generated and printed to the log:

```bash
sqlite3 blacklist_monitor.db "DELETE FROM users;"
```

(Or, if you're using Postgres, run the equivalent `DELETE FROM users;` against that
database.) Then restart the app and check the terminal/log output again for the new
password.

**"Address already in use" when starting uvicorn**
Something is already listening on port 8000. Either stop that process, or start on a
different port: `uvicorn app.main:app --reload --port 8001`.

**Spamhaus ZEN / Spamhaus DBL always show a DNS error**
You need a Spamhaus DQS key — see [Spamhaus DQS key](#spamhaus-dqs-key-required-for-spamhaus-zendbl)
above. This is expected/safe behavior without a key, not a bug.

**Notifications aren't being sent**
Check three things, in order: (1) SMTP/Pushover credentials are filled in under Settings,
(2) you have at least one enabled Alert Rule matching the severity/blacklist/client you
expect, (3) the **Activity** page or the notification's `error` field for the specific
failure reason.

**`pip install` fails compiling `psycopg2-binary`**
That package is only needed for Postgres. If you're using SQLite (the default), you can
remove the `psycopg2-binary` line from `requirements.txt`, or install build tools first:
`sudo apt install -y build-essential python3-dev libpq-dev`.

---

## Project structure

```
app/
  main.py              # FastAPI app, page routes, startup (seed + scheduler)
  config.py            # Settings (env vars)
  models.py            # SQLAlchemy ORM (the full data model)
  schemas.py           # Pydantic (request/response)
  security.py          # JWT, bcrypt, TOTP (2FA), RBAC (admin/operator/readonly)
  crypto.py            # Fernet for keys/passwords at rest
  seed.py              # First-boot setup: default blacklists + admin user (idempotent)
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
  templates/, static/   # Server-rendered UI (dark theme)
```

## API

All read routes used by the dashboard are public read-only within an authenticated
session; create/update/delete requires a JWT token (`POST /api/auth/login`) with
`operator` or `admin` role depending on the resource. Auto-generated interactive docs at
`/docs` once the app is running.

## License

MIT — see [LICENSE](LICENSE).
