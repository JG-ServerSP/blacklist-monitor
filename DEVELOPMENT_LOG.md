# Blacklist Monitor — Development Log and Pending Work

**Last updated:** 2026-07-07 (language pack completed)
**Purpose of this file:** provide full context to resume development in another session
without needing to reread the whole conversation history. See also
`PLANEJAMENTO-blacklist-monitor.md` (original scope) and `README.md` (how to run).

---

## 1. Current production state

- Running via **systemd** (`/etc/systemd/system/blacklistmonitor.service`), enabled on
  boot, automatic restart on failure. **Docker is not installed** on this server — the real
  stack is native Python + SQLite, not the `docker-compose.yml` stack (which exists in the
  repo but was not used here).
- Logs: `/var/log/blacklistmonitor.log`.
- Real config (real generated secrets, out of git): `/root/blacklistmonitor/.env`.
- Database: SQLite at `/root/blacklistmonitor/blacklist_monitor.db` — **wiped of demo
  data**, contains only the 8 default blacklists (real engine config) and the admin user.
- Access: `http://<server-ip>:8000` — **plain HTTP, no TLS/domain configured**.
- **The entire backend (`/api/*`, except `/api/auth/login` and `/health`) requires a valid
  JWT.** This was a fix made in this session — initially read routes (`GET`) did not
  require a token, only create/edit/delete. It's now uniform: without login, nothing works
  (not even viewing).
- The admin login created in this session was delivered to the user in chat (randomly
  generated password, shown once in the log). **If you don't have this password, generate
  a new one:** delete the user row in the `users` table and restart the service (the seed
  recreates the admin with a new random password and logs it to
  `/var/log/blacklistmonitor.log`), or change it manually via Python
  (`app.security.hash_password`).
- **Git**: local repository (`git init` already done), but **nothing had been committed
  yet** at the time this note was written — all code was untracked. Ask the user before the
  first commit.

---

## 2. What has been implemented (tested end-to-end in this session)

Coverage of Phase 1 (MVP) of `PLANEJAMENTO-blacklist-monitor.md`:

- **Full data model** (`app/models.py`): clients, services, ip_groups, ip_blocks,
  monitored_ips, domains, blacklists, listings, check_runs, alert_rules, notifications,
  activity_log, users, settings — matching the design in section 5 of the plan.
- **IP registration**: CIDR, range (`a.b.c.d-e`), and single IP, with automatic expansion
  and a configurable safety limit (`MAX_CIDR_EXPANSION`, default /22). CSV import. Tested
  with real CIDRs, including rejection of `/8` for exceeding the limit.
- **DNSBL engine** (`app/services/dnsbl.py`): octet (IPv4) and nibble (IPv6) reversal,
  Spamhaus DQS key support (`{key}` in the zone template), per-zone rate limiting (token
  bucket), Spamhaus resolver-error detection (127.255.255.x) vs. real listing, return-code
  interpretation → sublist/severity via an editable `return_code_map`. Tested with real DNS
  queries against Barracuda/SpamCop/PSBL/SORBS/UCEPROTECT.
- **Ping pre-check** (`app/services/ping.py`): 3 modes (skip_unreachable, check_all,
  tcp_fallback), configurable cache, uses the system's `ping` binary (no root required).
  Tested with real ICMP.
- **Quick diagnostics** (`app/services/diagnostics.py`): rDNS/PTR, FCrDNS, SPF, DKIM, DMARC,
  port 25. Tested with real DNS against a public IP.
- **Listing lifecycle + deduplication**: alerts only fire on state transitions
  (entered/exited), never on every cycle (`app/services/checker.py`).
- **Notifications**: email (SMTP) and Pushover, with alert rules (conditions: minimum
  severity, blacklist, group, client, entry/exit) — `app/services/notifications.py`. The
  failure path was tested (SMTP not configured → notification recorded with "failed"
  status, does not crash the application).
- **Runtime settings**: SMTP/Pushover/DQS/DNS resolver editable via the UI and applied
  immediately (no restart) through `app/runtime_settings.py` — this was a real bug found
  and fixed in this session (saved settings had no effect at all before the fix).
- **Authentication**: JWT + bcrypt, RBAC (admin/operator/readonly), TOTP 2FA **at login**
  (see the pending item below — enrollment is still missing). Self password change is
  implemented (`POST /api/auth/change-password`) with a UI under Settings → My Account.
- **All of `/api/*` requires authentication** (fix made in this session — see section 1).
- **Scheduler** (`app/services/scheduler.py`, in-process APScheduler): general check
  (configurable interval) + accelerated re-check of currently listed IPs.
- **Server-rendered UI** (Jinja2 + vanilla JS + Chart.js/Tailwind via CDN, same dark theme
  as the mockup): Dashboard, Monitored IPs (+ CIDR/CSV import), Domains, Clients, IP
  Groups, Blacklists (CRUD), Alert Rules (basic CRUD), Settings, Activity, Login.
- **CSV export** of listings by period (`/api/reports/export.csv`, downloaded via JS with a
  token, not a direct link).
- **Language pack** (`app/static/js/i18n.js`): interface translated into PT-BR (default),
  English, Spanish, French, and German, selectable under Settings → Language (the switch is
  global, saved to the database via `app/runtime_settings.py`, reloads the page). The
  client-side engine (`t()`/`applyI18n()`/`data-i18n*`) covers navigation, all CRUD pages
  (IPs, domains, clients, groups, blacklists, alert rules, users, logs, activity), and the
  dashboard, including text generated dynamically in JS (toasts, confirms, modal titles).
  This session resumed work that had stopped halfway: the i18n engine and the
  navigation/settings strings already existed, but almost no page-content keys
  (`dashboard.*`, `ips.*`, `clients.*`, `groups.*`, `blacklists.*`, `domains.*`) had been
  filled in the translations file — templates referenced keys that didn't exist, so those
  pages displayed the raw key instead of text. Also fixed real bugs found along the way:
  `ips.js` referenced `STATUS_LABEL`/`PING_LABEL`, which no longer existed anywhere (now
  uses `statusLabel()`/`pingLabel()` from `app.js`), and `alert-rules.js` referenced a
  `SEVERITY_LABEL` that never existed (now uses `severityLabel()`).

---

## 3. What's missing (known gaps, not yet implemented)

### 3.1 Gaps within Phase 1 scope itself (should exist in a "complete" MVP)

- **User management**: there is no `/api/users` or a users screen. You can only log in
  with the admin created by the seed. RBAC (admin/operator/readonly) exists in the model
  and is checked on routes, but there's no way to create operator/readonly accounts via
  UI/API yet.
- **2FA enrollment**: login already validates TOTP if `totp_enabled=True`, but there's no
  endpoint to generate the secret, show a QR code, and let the user enable 2FA.
  `generate_totp_secret()` exists in `app/security.py` but is never called.
- **Per-user API tokens**: the `api_token_hash` field exists on the `User` model but is
  unused — there's no way to generate/use an API token (only a session JWT via login).
- **"Tickets" page**: the sidebar item exists but isn't clickable (just a badge). There's
  no ticket listing, only the `ticket_ref` field (a string like `#8421`) filled in when
  clicking "Open Ticket" on a listing — not a real integration with a ticketing system.
- **Dedicated "Reputation" / "Reports" pages**: the original mockup has sidebar items for
  these; today only `/api/reports/top-offenders` exists (endpoint ready, no UI consuming
  it) plus CSV export. Missing: per-client report, per-group/datacenter report, average
  delist time, repeat-offender IPs (the `risk_score` field exists and increments on every
  new listing, but no screen/report exposes it).
- **"Templates" page**: notifications use a fixed HTML template in code
  (`render_listing_email` in `notifications.py`). There's no template editor in the UI.
- **Dedicated "Delist Requests" page**: the "Request Delist" action exists per listing, but
  there's no central screen listing all requested/pending delists.
- **"Block SMTP" button**: present in the original mockup, not implemented (not even as a
  stub) — fine as-is, it's a Phase 3 item in the plan (real blocking via
  firewall/hypervisor).
- **Diagnostics as a standalone tool**: today diagnostics only exist *for an already
  registered IP* (drilldown from the dashboard). The mockup suggests a separate
  "Diagnostics" screen where you could type any ad-hoc IP/domain and run diagnostics
  without registering it first.

### 3.2 Phase 2 of the plan (not started)

- Alert escalation: the `escalation` field (jsonb) exists on the `AlertRule` model and in
  the creation UI/API, but **nothing processes this field** — there's no worker/logic that
  checks "critical listing not acknowledged within N minutes → notify second tier".
- Silencing/snooze by IP, block, or blacklist (maintenance window) — not implemented, no
  field in the model for this yet.
- Daily/weekly email digest — not implemented.
- Additional channels: Telegram, Slack/Discord, generic HMAC webhook, SMS — not
  implemented (only email and Pushover exist, see `app/services/notifications.py`).
- Real integration with a ticketing system (WHMCS/osTicket/HubSpot/internal) — not
  implemented (see 3.1).
- Delist automation where an API exists (e.g. Barracuda's form) — not implemented, today
  it's just a delist link configured per blacklist (`delist_url`) that the operator opens
  manually.
- PDF/XLSX reports — only CSV exists today.

### 3.3 Phase 3 of the plan (not started, expected)

- Documented public API + automatic provisioning (new VPS → IP automatically monitored via
  an external provisioning API).
- Client portal (access restricted to their own IPs).
- Aggregated risk/repeat-offender score per client (today only exists per individual IP).
- Automatic SMTP blocking via firewall/hypervisor with dual approval.
- Prometheus metrics + health alerts for the system itself (today only a simple `/health`
  exists).
- ~~Multi-language (PT-BR/EN) — today it's PT-BR only.~~ Done in this session (see section
  2), with 5 languages instead of 2.

### 3.4 Infrastructure / production (technical pending items)

- **Real vs. planned stack**: running natively (systemd + SQLite + system DNS resolver),
  not the full `docker-compose.yml` stack (Postgres 16 + dedicated Unbound +
  Celery/Redis). If IP volume grows, or if Spamhaus starts blocking/degrading queries for
  coming from a shared resolver, the following will be needed:
  1. Install Docker (not available in this session's build environment).
  2. Bring up `docker compose up -d --build` (already testable, but not tested in this
     session due to lack of Docker).
  3. Migrate data from SQLite to Postgres (no ready-made migration script for this yet).
- **No TLS/domain**: access is plain HTTP on `IP:8000`. Needs a domain pointing to the IP +
  Nginx as a reverse proxy + Let's Encrypt.
- **No Spamhaus DQS key configured**: `Spamhaus ZEN`/`Spamhaus DBL` are registered but will
  always fail to resolve until someone configures the key under Settings (or per individual
  blacklist). Confirmed via a real test in this session ("A DNS label is empty" error
  without a key — correct/safe behavior, does not generate a false positive, it just stays
  unchecked).
- **No automated tests**: all verification in this session was manual (curl + ad-hoc Python
  scripts). There is no pytest suite in the repo.
- **No CI/CD.**
- **No automated backup** of SQLite (or of Postgres, when/if migrated).
- **No rate-limit/exponential backoff on DNS failures** — per-blacklist QPS rate limiting
  exists, but not progressive backoff when a zone starts failing repeatedly (e.g. temporary
  resolver block).

---

## 4. Suggested priority for the next session

Suggested order (gaps that matter most for real use as an IaaS provider):

1. **User management + 2FA enrollment** — today there's only 1 admin; NOC teams need their
   own accounts with real RBAC.
2. **Configure the Spamhaus DQS key** (real customer data, not code) + validate that the
   DNS resolver in use isn't being blocked due to volume (consider a dedicated Unbound if
   monitoring hundreds/thousands of IPs).
3. **Reputation/Reports page** consuming `top-offenders` + adding a per-client report and
   repeat-offender IPs (the data already exists, only the screen is missing).
4. **Alert escalation** (process the `escalation` field that already exists in the schema).
5. **TLS + domain**, once the user has a domain available.
6. Additional notification channels (Telegram is the cheapest/fastest to add value).
7. Basic automated tests (at least the DNSBL engine, CIDR, and listing lifecycle, which are
   the most critical logic).
