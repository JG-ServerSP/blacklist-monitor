# Blacklist Monitor

Implementação do MVP descrito em `PLANEJAMENTO-blacklist-monitor.md`: monitoramento de
reputação de IPs/domínios contra DNSBLs (Spamhaus ZEN via DQS, Barracuda, SpamCop, PSBL,
SORBS, UCEPROTECT, SURBL, Spamhaus DBL), com pré-verificação por ping, ciclo de vida de
listagens, notificações (e-mail + Pushover), diagnóstico rápido (rDNS/FCrDNS/SPF/DKIM/DMARC/
porta 25), regras de alerta, importação de IPs/CIDR/CSV, RBAC com 2FA e um dashboard no
padrão do mockup fornecido.

## Diferenças em relação à stack sugerida no planejamento

O documento original sugere Postgres + Celery/Redis + React/Vite + Docker + Unbound. Este
MVP foi construído para rodar em um ambiente **somente com Python 3.12** (sem Node/Docker
disponíveis durante o desenvolvimento), então:

- **Scheduler**: APScheduler in-process em vez de Celery + Redis. Funcionalmente equivalente
  para o volume do MVP (verificação geral + reverificação acelerada de IPs listados); trocar
  por Celery é direto se o volume crescer (a lógica de verificação já está isolada em
  `app/services/checker.py`, independente do agendador).
- **Banco**: SQLite por padrão (`DATABASE_URL`), mas o código já é Postgres-ready (basta
  trocar a URL — ver `docker-compose.yml`, que já sobe Postgres 16 em produção).
- **Frontend**: em vez de React/Vite, é uma UI servidor-renderizada (FastAPI + Jinja2 +
  JS puro + Chart.js/Tailwind via CDN, sem build step) no mesmo tema escuro e mesma
  estrutura de telas do mockup. A API REST (`/api/...`) é a mesma que um frontend React
  consumiria — trocar a camada de apresentação depois não exige mudanças no backend.

Tudo relacionado a **Spamhaus DQS, Unbound dedicado, rate limiting, RBAC, 2FA, ciclo de vida
de listagem, deduplicação de alertas e diagnóstico** segue exatamente o que está no
documento de planejamento.

## Status neste servidor

Rodando em produção via **systemd** (sem Docker), banco limpo — sem dados de demonstração,
apenas as 8 blacklists padrão (configuração real do motor, não "demo"):

- Serviço: `systemctl status blacklistmonitor` (habilitado no boot)
- Logs: `tail -f /var/log/blacklistmonitor.log`
- Config real: `/root/blacklistmonitor/.env` (com `SECRET_KEY`/`FERNET_KEY` gerados, fora do git)
- Banco: SQLite em `/root/blacklistmonitor/blacklist_monitor.db`
- Acesso: `http://<ip-do-servidor>:8000` (HTTP puro por enquanto — sem domínio/TLS configurado)

O usuário admin (`admin@seudominio.com`) foi criado com senha aleatória, exibida uma única
vez no log de inicialização. Troque-a em **Configurações → Minha Conta** assim que logar
(endpoint `POST /api/auth/change-password`, já implementado).

Para ir além (Postgres + Unbound via Docker Compose, ou TLS com domínio próprio via Nginx +
Let's Encrypt), veja as seções abaixo — não configurados aqui por padrão para evitar abrir
portas/instalar Docker sem confirmação.

## Rodando localmente (dev, SQLite)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # ajuste SECRET_KEY/FERNET_KEY em produção
uvicorn app.main:app --reload
```

Acesse `http://localhost:8000`. No primeiro start, o banco é criado e populado com dados de
demonstração (`app/seed.py`): 5 clientes, blacklists padrão, IPs de exemplo com listagens
ativas e um usuário administrador:

- **E-mail:** `admin@seudominio.com`
- **Senha:** `admin123`

> Troque essa senha (ou crie outro admin e desative este) antes de qualquer uso real.

## Rodando com Docker Compose (produção: Postgres + Unbound)

```bash
cp .env.example .env
docker compose up -d --build
```

Isso sobe `api` (FastAPI + scheduler), `postgres` e `unbound` (resolver DNS dedicado,
essencial para Spamhaus/SORBS — ver nota de produção abaixo).

## Notas de produção importantes

- **Resolver DNS dedicado**: Spamhaus, SORBS e outras bloqueiam ou degradam consultas vindas
  de resolvers públicos (8.8.8.8, 1.1.1.1) ou de alto volume. Configure `DNS_RESOLVERS` para
  apontar exclusivamente para o Unbound local (já incluído no `docker-compose.yml`), nunca
  para um resolver público.
- **Chave Spamhaus DQS**: obrigatória para Spamhaus ZEN/DBL. Configure em
  Configurações → Spamhaus DQS, ou por blacklist individual (o campo é criptografado em
  repouso com Fernet).
- **Ping/ICMP**: o pré-check usa o binário `ping` do sistema (não requer socket raw/root);
  o `Dockerfile` já instala `iputils-ping`. Em ambientes que bloqueiam ICMP de saída, use o
  modo `tcp_fallback` por grupo.
- **Segredos**: `SECRET_KEY` (JWT) e `FERNET_KEY` (criptografia de chaves/senhas em repouso)
  têm valores de exemplo em `.env.example` — gere valores novos antes de produção:
  ```bash
  python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```
- **Backups**: configure backup diário do Postgres (retenção sugerida: 30 dias) — não
  incluído neste MVP.
- **CIDR**: importação tem limite de segurança (`MAX_CIDR_EXPANSION`, padrão 1024 endereços
  = /22) para evitar expansão acidental de blocos grandes (ex.: /8).

## Estrutura

```
app/
  main.py              # FastAPI app, rotas de página, startup (seed + scheduler)
  config.py            # Settings (env vars)
  models.py            # SQLAlchemy ORM (todo o modelo de dados do planejamento)
  schemas.py           # Pydantic (request/response)
  security.py          # JWT, bcrypt, TOTP (2FA), RBAC (admin/operator/readonly)
  crypto.py            # Fernet para chaves/senhas em repouso
  seed.py              # Dados de demonstração (idempotente)
  services/
    cidr.py            # Expansão de CIDR/range/IP com limite de segurança
    ping.py            # Pré-check ICMP (3 modos) com cache
    dnsbl.py           # Motor de consulta DNSBL (reversão de octetos/nibbles,
                       # rate limiting por zona, DQS, detecção de erro do resolver)
    diagnostics.py     # rDNS/FCrDNS/SPF/DKIM/DMARC/porta 25
    notifications.py   # SMTP + Pushover + avaliação de regras de alerta
    checker.py          # Orquestra ping + DNSBL + ciclo de vida de listagem + notificação
    scheduler.py        # APScheduler: verificação geral + reverificação acelerada
  routers/              # Um módulo por recurso (auth, clients, ips, blacklists, ...)
  templates/, static/   # UI server-rendered (dark theme do mockup)
```

## API

Todas as rotas de leitura usadas pelo dashboard são públicas (somente leitura); criação/
edição/remoção exige um token JWT (`POST /api/auth/login`) com papel `operator` ou `admin`
conforme o recurso. Documentação automática em `/docs`.
