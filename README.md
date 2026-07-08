# Blacklist Monitor

Blacklist Monitor is a web-based reputation monitoring system for IP addresses and domains. It checks monitored assets against DNSBL/RBL lists, stores historical results, sends alerts, and provides DNS/mail diagnostics.

The project runs with FastAPI + SQLAlchemy and can be installed in two ways:

- **Docker Compose**, recommended for production, with API, PostgreSQL, and Unbound.
- Local/development installation with Python and SQLite.

This README focuses mainly on the Docker Compose installation.

## What the system monitors

- Individual IP addresses.
- CIDR blocks, for example `/24`.
- IP ranges.
- Domains.
- IPv4 blacklists and domain blacklists.
- Listing lifecycle: listed, clean, error, and not checked.
- rDNS, FCrDNS, SPF, DKIM, DMARC, and port 25 diagnostics.
- Email and Pushover alerts.
- Users, permissions, 2FA, and admin panel settings.

## Requirements

For the Docker installation:

- Updated Debian or Ubuntu server.
- Root access or a user with sudo privileges.
- Git.
- Docker Engine.
- Docker Compose plugin, using the `docker compose` command.

## 1. Install Docker and Docker Compose

On Debian/Ubuntu, run as root:

```bash
apt update
apt install -y ca-certificates curl git openssl
install -m 0755 -d /etc/apt/keyrings
```

Add the official Docker repository:

```bash
. /etc/os-release

curl -fsSL https://download.docker.com/linux/$ID/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

cat > /etc/apt/sources.list.d/docker.sources <<EOF_DOCKER
Types: deb
URIs: https://download.docker.com/linux/$ID
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF_DOCKER

apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Test the installation:

```bash
docker --version
docker compose version
docker run --rm hello-world
```

## 2. Download the project

```bash
cd /opt
git clone https://github.com/JG-ServerSP/blacklist-monitor.git
cd /opt/blacklist-monitor
```

## 3. Create the `.env` file

Copy the example file:

```bash
cp .env.example .env
```

Or create a new `.env` file with secure keys:

```bash
SECRET_KEY=$(openssl rand -base64 48)

FERNET_KEY=$(docker run --rm python:3.12-slim python -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())")

ADMIN_PASSWORD=$(openssl rand -base64 18)

cat > .env <<EOF_ENV
APP_NAME="Blacklist Monitor"

SECRET_KEY=$SECRET_KEY
FERNET_KEY=$FERNET_KEY

ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=$ADMIN_PASSWORD

SPAMHAUS_DQS_KEY=

DEFAULT_CHECK_INTERVAL_MINUTES=60
LISTED_IP_RECHECK_MINUTES=15
MAX_CIDR_EXPANSION=1024

SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_USE_TLS=true
SMTP_FROM=blacklist-monitor@localhost

PUSHOVER_APP_TOKEN=

CORS_ORIGINS=*
LANGUAGE=en
LOG_LEVEL=info
EOF_ENV

echo "Initial admin password: $ADMIN_PASSWORD"
```

Save the displayed password.

Important variables:

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Signs login/session tokens. |
| `FERNET_KEY` | Encrypts sensitive data stored in the database. |
| `ADMIN_EMAIL` | Initial administrator email address. |
| `ADMIN_PASSWORD` | Initial administrator password. |
| `SPAMHAUS_DQS_KEY` | Spamhaus DQS key, required for Spamhaus ZEN/DBL. |
| `LANGUAGE` | Default UI language. Use `en`, `pt-BR`, `es`, `fr`, or `de`. |

## 4. Configure `docker-compose.yml` with a fixed Unbound IP

For production, use a dedicated DNS resolver. Do not use public resolvers such as `8.8.8.8`, `1.1.1.1`, or other high-volume shared resolvers for DNSBL queries.

The application must receive the DNS resolver as an **IP address**. Therefore, the Docker Compose setup should create a dedicated network and assign a fixed IP to the `unbound` container.

Replace your `docker-compose.yml` with this recommended model:

```bash
cat > docker-compose.yml <<'EOF_COMPOSE'
services:
  api:
    build: .
    restart: unless-stopped
    env_file: .env
    environment:
      DATABASE_URL: postgresql+psycopg2://blacklist:blacklist@postgres:5432/blacklist_monitor
      DNS_RESOLVERS: 172.28.53.53
    ports:
      - "8000:8000"
    depends_on:
      - postgres
      - unbound
    networks:
      - bmnet

  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: blacklist
      POSTGRES_PASSWORD: blacklist
      POSTGRES_DB: blacklist_monitor
    volumes:
      - pgdata:/var/lib/postgresql/data
    networks:
      - bmnet

  unbound:
    image: mvance/unbound:latest
    restart: unless-stopped
    networks:
      bmnet:
        ipv4_address: 172.28.53.53

volumes:
  pgdata:

networks:
  bmnet:
    ipam:
      config:
        - subnet: 172.28.53.0/24
EOF_COMPOSE
```

In this example:

- `api`: application container.
- `postgres`: persistent PostgreSQL database.
- `unbound`: dedicated DNS resolver for DNSBL queries.
- Unbound IP address: `172.28.53.53`.

Important: do not set `DNS_RESOLVERS=unbound`. The container name may be `unbound`, but the application DNS library expects an IP address, not the Docker service hostname.

## 5. Start the application

```bash
docker compose up -d --build
```

Check the containers:

```bash
docker compose ps
```

View API logs:

```bash
docker compose logs -f api
```

Open the panel:

```text
http://SERVER-IP:8000
```

Initial login:

```text
Email: admin@example.com
Password: password displayed when the .env file was created
```

After the first login, change the administrator password.

## 6. Check the Unbound container IP

If you used the recommended `docker-compose.yml`, the Unbound IP should be:

```text
172.28.53.53
```

Confirm it with Docker:

```bash
UNBOUND_CONTAINER=$(docker compose ps -q unbound)
docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$UNBOUND_CONTAINER"
```

You can also inspect the Docker network:

```bash
docker network inspect blacklist-monitor_bmnet | grep -A5 -B2 unbound
```

The output should show `172.28.53.53` assigned to the `unbound` container.

## 7. Test DNS resolution from the API container

Test whether the DNS library accepts the resolver:

```bash
docker compose exec -T api python - <<'PY'
import dns.asyncresolver

r = dns.asyncresolver.Resolver(configure=False)

try:
    r.nameservers = ["172.28.53.53"]
    print("OK: resolver accepted:", r.nameservers)
except Exception as e:
    print("ERROR:", repr(e))
PY
```

Test a normal DNS query:

```bash
docker compose exec -T api python - <<'PY'
import dns.resolver

r = dns.resolver.Resolver(configure=False)
r.nameservers = ["172.28.53.53"]
r.timeout = 5
r.lifetime = 10

try:
    ans = r.resolve("example.com", "A")
    print("OK:", [x.to_text() for x in ans])
except Exception as e:
    print("ERROR:", repr(e))
PY
```

If this test works, the API container can resolve DNS through Unbound.

## 8. Configure the resolver in the admin panel

Important: settings saved in the admin panel can override `.env` and Docker Compose environment variables.

After starting the application, open the admin panel and go to:

```text
Settings > DNS Resolver / Scheduler
```

If your UI is in Portuguese, the path is:

```text
Configurações > Resolver DNS / Agendador
```

In the field:

```text
DNS resolvers / Resolvers DNS
```

Set:

```text
172.28.53.53
```

Save the settings.

If this field is set to `unbound`, empty, or a public resolver, IP checks may return **Error**.

Recommended final flow:

```text
Unbound container: 172.28.53.53
Docker Compose: DNS_RESOLVERS=172.28.53.53
Admin panel: DNS resolvers = 172.28.53.53
```

## 9. Confirm the effective application settings

Run:

```bash
docker compose exec -T api python - <<'PY'
from app.database import SessionLocal
from app.runtime_settings import effective_settings

db = SessionLocal()
s = effective_settings(db)

print("Effective DNS_RESOLVERS =", s.dns_resolvers)
print("SPAMHAUS_DQS_KEY configured?", bool(s.spamhaus_dqs_key))

db.close()
PY
```

Expected resolver result:

```text
Effective DNS_RESOLVERS = 172.28.53.53
```

If it shows `unbound`, `8.8.8.8`, `1.1.1.1`, or another value, update the admin panel setting in **Settings > DNS Resolver / Scheduler**.

## 10. Spamhaus DQS key

The **Spamhaus ZEN** and **Spamhaus DBL** blacklists require a Spamhaus DQS key.

Without the key, these blacklists may return DNS resolution errors. This does not mean the IP is listed; it only means that the query could not be completed correctly.

You can configure the key in two ways.

### Option A: through `.env`

```bash
nano .env
```

Set:

```env
SPAMHAUS_DQS_KEY=your-dqs-key-here
```

Restart the API:

```bash
docker compose restart api
```

### Option B: through the admin panel

Go to:

```text
Settings > Spamhaus DQS
```

Enter the DQS key and save.

If you do not have a DQS key yet, temporarily disable the Spamhaus lists in the panel:

```text
Blacklists > Spamhaus ZEN > Disable
Blacklists > Spamhaus DBL > Disable
```

## 11. Import IP addresses or blocks

In the panel, go to:

```text
Monitored IPs > Add IP/Block
```

You can add:

- Individual IP address, for example `203.0.113.10`.
- CIDR block, for example `203.0.113.0/24`.
- IP range.
- CSV file.

CIDR expansion is controlled by:

```env
MAX_CIDR_EXPANSION=1024
```

After importing, run:

```text
Check all
```

or:

```text
Check selected
```

## 12. IP status meanings

Main statuses:

| Status | Meaning |
|---|---|
| Clean | No enabled blacklist returned a listing. |
| Listed | At least one enabled blacklist confirmed a listing. |
| Error | One or more DNSBL queries failed. |
| Not checked | The IP has not been checked yet or was skipped by a rule/pre-check. |

Notes:

- **Error** does not necessarily mean that the IP is listed.
- **No response** on ping does not mean blacklist; it only means that the IP did not answer ICMP.
- In large IP blocks, many addresses may not reply to ping. Configure the group to check all IPs when needed.

## 13. Useful commands

Show containers:

```bash
docker compose ps
```

View API logs:

```bash
docker compose logs -f api
```

View PostgreSQL logs:

```bash
docker compose logs -f postgres
```

View Unbound logs:

```bash
docker compose logs -f unbound
```

Restart the API:

```bash
docker compose restart api
```

Restart all services:

```bash
docker compose restart
```

Stop services:

```bash
docker compose down
```

Start again:

```bash
docker compose up -d
```

Update the code:

```bash
cd /opt/blacklist-monitor
git pull
docker compose up -d --build
```

Warning: do not run `docker compose down -v` in production, because it removes the PostgreSQL volume and deletes the database data.

## 14. Backup

Simple PostgreSQL backup:

```bash
mkdir -p /opt/backups/blacklist-monitor

docker compose exec -T postgres pg_dump -U blacklist blacklist_monitor > /opt/backups/blacklist-monitor/blacklist_monitor_$(date +%F_%H%M).sql
```

Restore a backup:

```bash
cat /opt/backups/blacklist-monitor/FILE.sql | docker compose exec -T postgres psql -U blacklist blacklist_monitor
```

## 15. Troubleshooting

### IP status remains Error

First check the effective resolver:

```bash
docker compose exec -T api python - <<'PY'
from app.database import SessionLocal
from app.runtime_settings import effective_settings

db = SessionLocal()
s = effective_settings(db)
print("Effective DNS_RESOLVERS =", s.dns_resolvers)
print("SPAMHAUS_DQS_KEY configured?", bool(s.spamhaus_dqs_key))
db.close()
PY
```

If the resolver is not `172.28.53.53`, update it in the admin panel:

```text
Settings > DNS Resolver / Scheduler
```

### `DNS_RESOLVERS = unbound`

This is incorrect for the application.

The container may be named `unbound`, but the application must receive the **resolver IP address**, for example:

```text
172.28.53.53
```

Fix it in `docker-compose.yml` and in the admin panel.

### Error when running heredoc commands

If you see:

```text
cannot attach stdin to a TTY-enabled container because stdin is not a terminal
```

Use `-T`:

```bash
docker compose exec -T api python - <<'PY'
print("ok")
PY
```

### Spamhaus ZEN/DBL always returns errors

Configure the Spamhaus DQS key or temporarily disable the Spamhaus ZEN/DBL blacklists.

### Port 8000 is not accessible

Check whether the container is running:

```bash
docker compose ps
```

Check logs:

```bash
docker compose logs --tail=200 api
```

If you use a firewall, allow the port:

```bash
ufw allow 8000/tcp
```

Or restrict access to your public IP:

```bash
ufw allow from YOUR_PUBLIC_IP to any port 8000 proto tcp
```

### Show detailed error per blacklist

Replace the IP below with one of your monitored IP addresses:

```bash
docker compose exec -T api python - <<'PY'
import asyncio
from app.database import SessionLocal
from app.models import Blacklist, BLType
from app.runtime_settings import effective_settings
from app.services.dnsbl import check_ip_against_blacklists

ip = "203.0.113.10"

db = SessionLocal()
settings = effective_settings(db)
blacklists = db.query(Blacklist).filter(
    Blacklist.enabled == True,
    Blacklist.type == BLType.ipv4
).all()

async def main():
    results = await check_ip_against_blacklists(ip, blacklists, settings=settings, concurrency=1)

    for bl in blacklists:
        r = results.get(bl.id)
        print(f"{bl.id} | {bl.name}")
        print(f"  listed: {r.listed if r else None}")
        print(f"  codes: {r.codes if r else None}")
        print(f"  error: {r.error if r else None}")
        print()

asyncio.run(main())
db.close()
PY
```

This test shows exactly which blacklist is returning an error.

## 16. Local/development installation with Python and SQLite

For a simple local development setup:

```bash
cd /opt
git clone https://github.com/JG-ServerSP/blacklist-monitor.git
cd blacklist-monitor

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Generate keys:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Edit `.env` and configure `SECRET_KEY` and `FERNET_KEY`.

Start the app:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open:

```text
http://localhost:8000
```

For production, prefer Docker Compose with PostgreSQL and Unbound.

## 17. Recommended security practices

- Change the administrator password after the first login.
- Use a strong password.
- Enable 2FA for administrative users.
- Do not expose the panel publicly without a firewall, reverse proxy, or access control.
- Back up PostgreSQL regularly.
- Use a dedicated Unbound resolver for DNSBL queries.
- Do not use public resolvers for high-volume DNSBL checks.
- Configure the Spamhaus DQS key if you want to use Spamhaus ZEN/DBL.
