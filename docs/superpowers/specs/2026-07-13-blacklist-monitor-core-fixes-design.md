# Blacklist Monitor — Correções do núcleo (concorrência, detecção e integridade)

- **Data:** 2026-07-13
- **Escopo:** itens 1–10 da auditoria (críticos + médios). Sem testes automatizados nesta fase.
- **Fora de escopo:** refatoração da duplicação email/pushover além do mínimo (item 13), features mortas de alerta (item 11), testes (item 12).

## Contexto

Monitor de reputação DNSBL/RBL em FastAPI + SQLAlchemy (SQLite em dev, Postgres em prod), UI Jinja2 + JS vanilla, scheduler APScheduler, notificações SMTP/Pushover. A auditoria identificou bugs estruturais de concorrência, detecção com falso positivo, e ausência de integridade no nível do banco. Este documento especifica as correções aprovadas.

Princípio geral: **correções cirúrgicas seguindo os padrões existentes**, sem introduzir dependências novas (mantém `smtplib`/`httpx` síncronos, sem Alembic, sem async ORM).

---

## A) Modelo de execução e concorrência (itens 1, 2, 5, 7)

### A1. Sessão por worker (item 1)

**Problema:** `run_check_batch` (`app/services/checker.py:199-214`) roda `asyncio.gather` com `Semaphore(20)` mas todos os workers compartilham a mesma `Session`. Os `await` internos (ping, DNS) intercalam corrotinas → uso concorrente da Session, que **não é thread/async-safe**: commits de estado meio-construído, erros esporádicos, status trocados entre IPs.

**Solução:**
- `run_check_batch(db, ip_rows, ...)` passa a trabalhar por **id**. A `Session` externa (`db`) é usada **apenas** para criar/atualizar o `CheckRun`.
- Cada `worker` abre a própria `SessionLocal()`, recarrega o `MonitoredIP` por `id` naquela sessão, chama `check_single_ip(worker_db, row)`, e no `finally` fecha a sessão.
- Contadores (`skipped`, `errors`) permanecem via `nonlocal`, protegidos por serem atualizações atômicas simples no event loop (int += 1 entre awaits — sem risco de corrupção de int em asyncio single-thread).
- `check_single_ip` e `check_single_domain` continuam recebendo a sessão como parâmetro (não abrem a própria) — quem gerencia o ciclo de vida é o chamador (worker, request handler ou task de fundo).

**Assinatura alvo:**
```python
async def run_check_batch(db: Session, ip_ids: list[int], concurrency: int = 20) -> CheckRun:
    ...
    async def worker(ip_id: int):
        async with sem:
            wdb = SessionLocal()
            try:
                row = wdb.query(MonitoredIP).get(ip_id)
                if row is None:
                    return
                before = row.current_status
                await check_single_ip(wdb, row)
                if row.current_status == IPStatus.unchecked and before != IPStatus.unchecked:
                    skipped += 1
            except Exception:
                errors += 1
                wdb.rollback()
            finally:
                wdb.close()
```

**Impacto nos chamadores:** `run_check_batch` passa a receber `list[int]` em vez de `list[MonitoredIP]`. Ajustar `ips.py` (`bulk_check`, `check_all`) e `scheduler.py` para passar ids (`[r.id for r in rows]` ou selecionar só ids).

### A2. Envio de notificação fora do event loop (item 2)

**Problema:** `send_email` (`app/services/notifications.py:27`, `smtplib`, timeout 10s) e `send_pushover` (`:52`, `httpx.post` síncrono) são chamados dentro de `check_single_ip` (async). Bloqueiam o event loop inteiro por até 10s por envio.

**Solução:**
- Separar **rede** de **banco** dentro de `dispatch_for_listing`/`dispatch_check_error`:
  - As chamadas de rede (`send_email`, `send_pushover`) passam a ser invocadas via `await asyncio.to_thread(send_email, ...)`. Isso exige que os dispatchers virem `async def`.
  - A gravação das linhas `Notification` continua na thread do event loop, usando a sessão do worker.
- `check_single_ip`/`check_single_domain` passam a `await` os dispatchers (hoje chamam sem await).
- Sem dependência nova: `smtplib`/`httpx` continuam síncronos, apenas deslocados para thread.

**Nota de sessão:** como o envio de rede roda em thread mas o `db.add(Notification(...))` roda no loop, a `Session` nunca é tocada por duas threads — o `to_thread` envolve **somente** a função de envio (que não recebe a sessão).

### A3. Checagens longas em background (item 5)

**Problema:** `bulk_check` (`app/routers/ips.py:177`), `check_all` (`:186`) fazem `await run_check_batch(...)` na requisição — a request fica pendurada durante toda a batch.

**Solução:**
- `bulk-check` e `check-all` **selecionam os ids**, criam o `CheckRun` (started), disparam a batch com `asyncio.create_task(run_check_batch_bg(ids, run_id))` e retornam **202** com `{"run_id": ..., "queued": N}`.
- `run_check_batch_bg` abre a própria sessão (a sessão da request fecha ao terminar o handler), executa a batch e atualiza o `CheckRun`.
- `force_check` (1 IP, `:251`) permanece **síncrono** (latência aceitável para um IP), mas usando a sessão da própria request — sem mudança estrutural além de herdar as correções de A1/A2 no `check_single_ip`.
- Guardar referência das tasks de fundo num set de módulo para evitar coleta prematura pelo GC (`task.add_done_callback(tasks.discard)`).

**[decisão registrada]** `asyncio.create_task` com sessão dedicada, não fila/worker externo (overkill para o porte).

### A4. Scheduler unificado (item 7)

**Problema:** `scheduler.py` mantém dois jobs (`job_check_due_ips` + `job_recheck_listed_ips`) que podem checar os mesmos IPs concorrentemente (sessões separadas) → trabalho e listagens duplicadas; e `listed_ip_recheck_minutes` é lido **uma vez no startup** (`:68,81`) — mudança em Settings não tem efeito.

**Solução:**
- **Remover** `job_recheck_listed_ips` e o segundo `add_job`.
- Um único tick (`job_check_due_ips`, a cada `TICK_MINUTES=1`) calcula "vencido" por IP:
  - status `listed` → usa `listed_ip_recheck_minutes` (lido fresco via `effective_settings(db)` a cada tick).
  - demais → usa `_effective_interval_minutes(ip, default_minutes)` como hoje.
- `_effective_interval_minutes` ganha um parâmetro/ramo para o caso `listed`, ou o filtro no tick trata os dois casos:
  ```python
  def _due_interval(ip, s):
      if ip.current_status == IPStatus.listed:
          return s.listed_ip_recheck_minutes
      return _effective_interval_minutes(ip, s.default_check_interval_minutes)
  ```
- Guarda contra `listed_ip_recheck_minutes <= 0` (fallback para 1) para não zerar o intervalo.
- `run_check_batch` recebe ids (ver A1).

---

## B) Correção de detecção DNSBL (item 3)

**Problema:** `check_zone` (`app/services/dnsbl.py:156-174`) trata só o prefixo de erro do Spamhaus; qualquer outra resposta A vira `listed=True`. Sequestro de NXDOMAIN por resolver (portal cativo, wildcard, ISP) → **falso positivo** de listagem.

**Solução:**
- Após obter `codes`, uma resposta só conta como listagem se **≥1 código estiver em `127.0.0.0/8`**.
- Regras, em ordem:
  1. Se algum código começa com `127.255.255.` → erro Spamhaus (comportamento atual, mantido).
  2. Senão, se **nenhum** código está em `127.0.0.0/8` → `DNSBLResult(listed=False, codes=codes)` + `logger.warning` (provável sequestro de resolver). **Não** é tratado como erro (para não gerar alerta de falha).
  3. Senão (≥1 código em 127/8) → `listed=True` e busca TXT (comportamento atual).
- Validação via `ipaddress.ip_address(code) in ipaddress.ip_network("127.0.0.0/8")`, com try/except para códigos não-IP.
- Adicionar `logger = logging.getLogger("dnsbl")` ao módulo (hoje não há logger).

**[decisão registrada]** não-127 = "não listado" (com log), não "erro".

---

## C) Integridade das listagens (itens 4, 9, 6)

### C1. Unicidade no banco (item 4)

**Problema:** dedup só em Python (`checker.py:59-61`). Duas checagens concorrentes do mesmo IP inserem duas listagens abertas → listagem e notificação duplicadas. Sem constraint no banco.

**Solução:**
- Índices únicos **parciais** criados em `run_lightweight_migrations` (`app/database.py`), idempotentes, compatíveis com SQLite e Postgres:
  - `CREATE UNIQUE INDEX IF NOT EXISTS uq_open_listing_ip ON listings (ip_id, blacklist_id) WHERE removed_at IS NULL`
  - `CREATE UNIQUE INDEX IF NOT EXISTS uq_open_listing_domain ON listings (domain_id, blacklist_id) WHERE removed_at IS NULL`
- A migração deve **detectar e tratar duplicatas pré-existentes** antes de criar o índice (senão a criação falha): manter a listagem aberta mais antiga por `(ip_id/domain_id, blacklist_id)` e fechar (`removed_at = now`, `status = removed`) as demais. Rodar essa limpeza dentro de `run_lightweight_migrations`, antes do `CREATE UNIQUE INDEX`.
- No `checker`, ao inserir uma `Listing` nova, envolver o `flush`/`commit` em try/`except IntegrityError`: em corrida, `rollback`, recarregar a listagem aberta existente e seguir como "já listado" (não dispara notificação duplicada).

### C2. Notificação de domínio (item 9)

**Problema:** `check_single_domain` (`checker.py:157-175`) não chama `dispatch_for_listing` em listagem/remoção — domínios listam/deslistam em silêncio. `dispatch_for_listing` é 100% IP-cêntrico (`listing.ip_id`, `ip.ip`).

**Solução:**
- Generalizar `dispatch_for_listing` para resolver o **alvo** a partir da própria `Listing`:
  - se `listing.ip_id` → alvo = `MonitoredIP.ip`, com `group_id`/`client_id` do IP.
  - se `listing.domain_id` → alvo = `Domain.domain`, com `client_id` do domínio (sem group).
- `_matches_conditions` já lida com `ip is None`; estender para receber um objeto de contexto com `group_id`/`client_id` genérico (ou passar o próprio IP/Domain e ler os campos condicionalmente).
- `render_listing_email`/títulos passam a usar o rótulo genérico (o parâmetro hoje se chama `ip`; renomear para `target` ou reutilizar sem renomear campos de template). Manter a assinatura de e-mail estável.
- `check_single_domain` passa a `await dispatch_for_listing(db, listing, resolved=False)` na detecção e `await dispatch_for_listing(db, existing, resolved=True)` na remoção, espelhando o caminho de IP.

### C3. `risk_score` determinístico (item 6)

**Problema:** `checker.py:115` faz `risk_score = min(100, risk_score + 10)` — só cresce, nunca decai; trava em 100.

**Solução:**
- Substituir o acumulador por **recálculo** a partir das listagens abertas do IP a cada checagem:
  ```python
  WEIGHT = {Severity.low: 10, Severity.medium: 25, Severity.high: 50, Severity.critical: 100}
  risk = min(100, sum(WEIGHT[l.severity] for l in open_listings_after_update))
  # 0 quando não há listagem aberta
  ```
- Calcular após atualizar o conjunto de listagens no ciclo (usar as listagens abertas resultantes, não o dicionário pré-checagem).
- **[decisão registrada]** `risk_score` permanece só para IP; adicionar coluna a `Domain` fica fora do escopo.

---

## D) Robustez (itens 8, 10)

### D1. `decrypt()` à prova de falha (item 8)

**Problema:** `crypto.decrypt` (`app/crypto.py:18`) levanta `InvalidToken`; `runtime_settings.py:34` e `dnsbl.py:189` chamam sem proteção. Uma linha corrompida em `settings` ou uma `api_key` de blacklist quebra `effective_settings()` em **toda** requisição (500 global).

**Solução:**
- Novo helper em `app/crypto.py`:
  ```python
  def safe_decrypt(token: str) -> str | None:
      try:
          return decrypt(token)
      except (InvalidToken, Exception):
          return None
  ```
  (capturar `cryptography.fernet.InvalidToken` explicitamente + fallback genérico defensivo).
- `runtime_settings.effective_settings`: usar `safe_decrypt`; se `None`, pular a linha e `logger.warning` (não derrubar o merge de settings).
- `dnsbl.check_ip_against_blacklists` (`:189`): usar `safe_decrypt` na `api_key_encrypted`; se `None`, cair para `settings.spamhaus_dqs_key`; se ainda vazio e `requires_key`, retornar `DNSBLResult(error=...)` claro para aquela blacklist (não quebrar a batch).

### D2. Caches limitados (item 10)

**Problema:** `_ping_cache` (`app/services/ping.py:17`) e os `_buckets`/`_locks` do `RateLimiter` (`app/services/dnsbl.py:43-44`) nunca são limpos → crescimento lento de memória.

**Solução:**
- `_ping_cache`: remoção preguiçosa de entradas expiradas em `_cache_set` (varredura leve quando o dict passa de um limite, ex. 10 000 entradas) **e** teto de tamanho (descartar as mais antigas). TTL já existe via `ping_cache_minutes`.
- `RateLimiter`: os buckets são por **zona** (conjunto pequeno e limitado = nº de blacklists), então o risco real é baixo; adicionar apenas remoção de buckets ociosos há muito tempo se o dict passar de um limite defensivo. `_locks` idem. Documentar que o crescimento é limitado pelo nº de zonas.

---

## Ordem de implementação sugerida

1. **A1 + A2** (sessão por worker + envio em thread) — base de tudo; muda assinaturas de `run_check_batch` e dos dispatchers.
2. **A3 + A4** (background + scheduler unificado) — dependem de A1.
3. **B** (validação 127/8) — isolado, baixo acoplamento.
4. **C1** (índice único + limpeza de duplicatas + `IntegrityError`) — migração + checker.
5. **C2** (notificação de domínio) — depende de A2 (dispatch async).
6. **C3** (risk_score) — isolado no checker.
7. **D1 + D2** (robustez) — isolados.

## Verificação (manual, sem suíte automatizada)

Após cada bloco, exercitar o fluxo real (não só import):
- Subir o app local (SQLite), rodar um `check-all`/`bulk-check` e confirmar 202 + `CheckRun` populado sem erros no `server.log`.
- Forçar concorrência (vários IPs) e confirmar ausência de erros de Session concorrente e de listagens duplicadas.
- Simular resposta DNS fora de 127/8 (mock/resolver de teste) e confirmar "não listado" + warning.
- Corromper uma linha de `settings` e confirmar que a app segue de pé (sem 500 global).
- Confirmar que mudar `listed_ip_recheck_minutes` nas Settings passa a valer sem restart.

## Riscos e mitigação

- **Mudança de assinatura de `run_check_batch` (obj → id):** localizada; todos os chamadores estão em `ips.py` e `scheduler.py`. Grep por `run_check_batch` antes de fechar.
- **Migração de índice único com duplicatas pré-existentes:** a limpeza prévia é obrigatória, senão `CREATE UNIQUE INDEX` falha no startup. Testar contra o `blacklist_monitor.db` atual.
- **Dispatchers virando `async`:** todos os pontos de chamada estão no `checker.py`; garantir o `await`.
- **`to_thread` + sessão:** o envio em thread nunca recebe a `Session`; apenas funções puras de rede.
