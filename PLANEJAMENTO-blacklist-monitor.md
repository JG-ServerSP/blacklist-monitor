# Blacklist Monitor — Documento de Planejamento

**Projeto:** Sistema de Monitoramento de Blacklists (DNSBL/RBL) para provedor IaaS
**Versão do documento:** 1.0
**Data:** 06/07/2026
**Status:** Planejamento — aprovado para desenvolvimento

---

## 1. Visão Geral

### 1.1 Objetivo

Desenvolver uma aplicação web (script + UI) para cadastrar, monitorar e gerenciar a reputação de blocos de IPs (IPv4 e IPv6) e domínios do data center contra as principais blacklists públicas e comerciais (Spamhaus ZEN via DQS, Barracuda, SpamCop, PSBL, SORBS, SURBL, UCEPROTECT, etc.), com registro histórico de listagens, diagnóstico automático e notificações multi-canal.

### 1.2 Problema que resolve

- IPs listados em blacklist degradam a entregabilidade de e-mail dos clientes e a reputação do ASN.
- Detecção manual é lenta: hoje o problema geralmente é descoberto quando o cliente reclama.
- Não há histórico centralizado de quando/onde cada IP foi listado, nem workflow de delist.

### 1.3 Escopo do MVP

1. Cadastro de blocos de IP (CIDR) e IPs avulsos, com agrupamento por cliente/serviço/datacenter.
2. Motor de verificação agendado contra lista **editável** de DNSBLs.
3. Suporte a **Spamhaus DQS** (chave configurável por instalação).
4. Pré-verificação por **ping (ICMP)** configurável — pular IPs sem resposta (opcional, por grupo ou global).
5. Registro histórico de cada listagem (entrada, saída, duração, severidade).
6. Notificações por **E-mail (SMTP)** e **Pushover**.
7. Dashboard no padrão visual do mockup (tema dark, cards de KPI, gráfico donut de severidade, timeline, tabela de listagens recentes, painel de diagnóstico rápido, feed de atividades).

---

## 2. Arquitetura Proposta

### 2.1 Stack sugerida

| Camada | Tecnologia | Justificativa |
|---|---|---|
| Backend/API | **Python 3.12 + FastAPI** | Async nativo (ideal para milhares de consultas DNS concorrentes), tipagem, OpenAPI automático |
| Worker/Scheduler | **Celery + Redis** (ou APScheduler no MVP) | Fila de verificação distribuída, retry, rate limiting por blacklist |
| Banco de dados | **PostgreSQL 16** | Tipos nativos `inet`/`cidr` (perfeitos para blocos de IP), particionamento do histórico |
| Cache/Fila | **Redis** | Fila Celery, cache de resultados, deduplicação de alertas |
| Frontend | **React + Vite + Tailwind** (ou Next.js) | SPA responsiva seguindo o design do mockup |
| Gráficos | **Recharts** ou Chart.js | Donut de severidade e timeline de listagens |
| Resolução DNS | **aiodns / dnspython** + **resolver dedicado (Unbound local)** | Ver item 2.3 — obrigatório para Spamhaus |
| Deploy | **Docker Compose** (app, worker, beat, postgres, redis, unbound) | Portabilidade para o ambiente de produção |
| Proxy | Nginx + TLS (Let's Encrypt) | — |

> Alternativa se o time preferir um único runtime: **Node.js (NestJS) + BullMQ**. A lógica do documento permanece idêntica.

### 2.2 Componentes

```
┌─────────────┐   ┌──────────────┐   ┌───────────────┐
│  Frontend   │──▶│  API (FastAPI)│──▶│  PostgreSQL   │
│  React SPA  │   └──────┬───────┘   └───────────────┘
└─────────────┘          │ enfileira jobs
                  ┌──────▼───────┐   ┌───────────────┐
                  │ Redis (fila) │◀─▶│ Workers Celery │
                  └──────────────┘   │ - ping check   │
                                     │ - dnsbl check  │
                                     │ - diagnóstico  │
                                     │ - notificação  │
                                     └──────┬────────┘
                                     ┌──────▼────────┐
                                     │ Unbound local │──▶ DNSBLs / DQS
                                     └───────────────┘
```

### 2.3 Resolver DNS dedicado (ponto crítico)

- **Spamhaus, SORBS e outras bloqueiam consultas vindas de resolvers públicos** (8.8.8.8, 1.1.1.1) e de resolvers com alto volume — retornam respostas de erro ou falsos "não listado".
- Rodar um **Unbound local** no container/host, sem forwarding para resolvers públicos.
- Para Spamhaus, usar exclusivamente o endpoint **DQS**: `<ip-reverso>.<chave>.zen.dq.spamhaus.net` — a chave fica em configuração criptografada.
- Implementar **rate limiting por blacklist** (configurável, ex.: 20 QPS por zona) e **jitter** entre consultas para não ser bloqueado.

---

## 3. Funcionalidades Detalhadas

### 3.1 Cadastro e gerenciamento de IPs

- Cadastro por **bloco CIDR** (`45.77.32.0/24`), **range** (`45.77.32.1-45.77.32.100`) ou IP avulso; IPv4 e IPv6.
- Expansão automática do CIDR em IPs individuais monitoráveis (com limite de segurança configurável, ex.: máx. /22 por importação).
- **Importação em massa** via CSV/TXT (coluna: ip/cidr, cliente, serviço, grupo, tags).
- Campos por IP/bloco: cliente, serviço (ex.: Cloud VPS #1234), grupo (ex.: Cloud — São Paulo), datacenter, ASN, tags livres, data de adição.
- **Grupos de IP** com configurações herdáveis (intervalo de verificação, política de ping, blacklists ativas, canais de notificação).
- Ativar/desativar monitoramento por IP, bloco ou grupo (ex.: janela de manutenção).

### 3.2 Pré-verificação por ping (configurável)

Comportamento padrão sugerido, com três modos selecionáveis por grupo ou globalmente:

| Modo | Comportamento |
|---|---|
| `skip_unreachable` *(padrão)* | Faz ICMP echo (timeout 2s, 2 tentativas). Sem resposta ⇒ IP marcado como **"não utilizado"** e **pulado** na rodada. |
| `check_all` | Verifica todos os IPs nas blacklists, respondam ou não ao ping. |
| `tcp_fallback` | Se ICMP falhar, tenta TCP connect nas portas configuráveis (ex.: 80, 443, 25, 22). Só pula se tudo falhar. |

Observações de implementação:
- Muitos servidores bloqueiam ICMP mas estão em uso — por isso o modo `tcp_fallback` e o aviso na UI de que "sem ping ≠ sem uso".
- IPs pulados aparecem no dashboard com status próprio ("Não verificado — sem resposta") e contador dedicado.
- Cache do resultado do ping por N minutos (configurável) para não pingar a cada ciclo.
- Opção de **verificação forçada** manual por IP ignorando o ping.

### 3.3 Motor de verificação DNSBL

- Consulta assíncrona em lote: `A` record em `<octetos-invertidos>.<zona-dnsbl>` (IPv4) e nibbles invertidos para IPv6.
- Interpretação dos **códigos de retorno** por blacklist (ex.: Spamhaus ZEN — 127.0.0.2/3 = SBL, 127.0.0.4-7 = XBL/CSS, 127.0.0.10/11 = PBL), com mapeamento editável por blacklist.
- Consulta `TXT` opcional para capturar o motivo/URL de delist.
- Detecção de **falso positivo por bloqueio do resolver** (ex.: retorno 127.255.255.x da Spamhaus indica erro de acesso, não listagem) — registrar como erro, nunca como listagem.
- Agendamento: intervalo global padrão (ex.: a cada 1h), sobrescrevível por grupo; IPs atualmente listados podem ter intervalo reduzido (ex.: 15 min) para detectar delist rapidamente.
- Deduplicação: alerta disparado apenas na **transição de estado** (entrou/saiu da lista), nunca a cada ciclo.

### 3.4 Gerenciamento de blacklists (editável)

CRUD completo na UI, com seed inicial:

| Blacklist | Zona | Severidade padrão | Observação |
|---|---|---|---|
| Spamhaus ZEN (SBL/XBL/CSS/PBL) | `<key>.zen.dq.spamhaus.net` | Crítica (SBL/XBL/CSS) / Baixa (PBL) | **Requer chave DQS** |
| Barracuda BRBL | `b.barracudacentral.org` | Alta | Requer registro do IP do resolver |
| SpamCop | `bl.spamcop.net` | Alta | — |
| PSBL | `psbl.surriel.com` | Média | — |
| SORBS | `dnsbl.sorbs.net` | Média | — |
| UCEPROTECT L1 | `dnsbl-1.uceprotect.net` | Média | L2/L3 opcionais (listam por ASN — cuidado) |
| SURBL (domínios) | `multi.surbl.org` | Alta | Para monitoramento de domínios |
| Spamhaus DBL (domínios) | `<key>.dbl.dq.spamhaus.net` | Crítica | DQS |

Campos por blacklist: nome, zona DNS, tipo (IP v4/v6/domínio), severidade padrão, mapa de códigos de retorno → sub-lista/severidade, URL de delist, URL de lookup, rate limit (QPS), habilitada s/n, requer chave s/n, campo de chave (criptografado).

### 3.5 Registro histórico e ciclo de vida da listagem

Cada listagem gera um registro com estados:

`detectada → notificada → (delist solicitado) → em observação → removida`

- Armazenar: IP, blacklist, sub-lista/código de retorno, severidade, timestamp de entrada, timestamp de saída, duração, TXT/motivo, quem solicitou delist, ticket vinculado.
- Timeline por IP (histórico completo de reincidências) — IPs reincidentes recebem badge/score de risco.
- Retenção configurável (ex.: 24 meses) com particionamento mensal da tabela de histórico.

### 3.6 Diagnóstico automático (painel "Diagnóstico Rápido")

Executado ao detectar listagem crítica/alta (e sob demanda):

- rDNS/PTR existe e PTR corresponde ao IP (FCrDNS)
- Hostname do PTR resolve A/AAAA
- SPF, DKIM, DMARC do domínio associado (quando houver)
- Porta 25 aberta/fechada (indício de open relay ou VPS comprometida)
- Consulta reputacional adicional (ex.: Talos/Sender Score — fase 2, via link externo no MVP)

Resultado exibido no painel lateral com ícones OK/aviso/erro, como no mockup.

### 3.7 Notificações

**Canais do MVP:**
1. **E-mail (SMTP)** — servidor, porta, TLS, auth configuráveis; templates HTML editáveis (módulo *Templates*).
2. **Pushover** — app token + user key por destinatário/grupo; prioridade mapeada da severidade (Crítica → priority 1/2 com retry).

**Canais sugeridos (fase 2):**
3. **Telegram Bot** — gratuito, ótimo para NOC.
4. **Webhook genérico** (POST JSON assinado com HMAC) — integra com qualquer sistema interno, incluindo o painel de clientes WordPress.
5. **Slack / Discord / Microsoft Teams** — via webhook nativo.
6. **SMS (Twilio/Zenvia)** — apenas para severidade crítica, por custo.
7. **Integração com sistema de tickets** (criação automática, como o "Ticket #8421" do mockup) — via API do WHMCS/HubSpot/osTicket, conforme o que a ServerSP usa.

**Regras de Alerta (módulo dedicado, como no mockup):**
- Condições: severidade ≥ X, blacklist específica, grupo/cliente específico, reincidência, IP saiu da lista (notificação de resolução).
- Ações: canais, destinatários, criação de ticket, bloqueio automático de SMTP (fase 2, com dupla confirmação).
- **Escalonamento**: se listagem crítica não reconhecida em N minutos, notificar segundo nível.
- **Silenciamento/snooze** por IP, bloco ou blacklist (janela de manutenção), com expiração.
- **Digest diário/semanal** por e-mail (resumo executivo).

### 3.8 Delist Requests (workflow)

- Botão "Solicitar Delist" abre o formulário/URL de delist da blacklist (links pré-configurados no CRUD de blacklists).
- Registrar quem solicitou, quando, e ativar re-verificação acelerada (15 min) até confirmação da remoção.
- Fase 2: automação de delist onde houver API (ex.: formulários da Barracuda) e templates de e-mail de delist.

### 3.9 Monitoramento de domínios

- Cadastro de domínios (SURBL, Spamhaus DBL, URIBL).
- Mesmo ciclo de vida e notificações dos IPs.

### 3.10 Relatórios e exportação

- Exportar relatório do período (PDF/CSV/XLSX) — botão "Exportar Relatório" do mockup.
- Relatórios: reputação por cliente, por grupo/datacenter, top blacklists ofensoras, tempo médio de delist, IPs reincidentes.
- Filtro por período (date range picker, como no mockup).

### 3.11 API REST e autenticação

- API completa (mesma usada pelo frontend) com tokens de API por usuário — permite integração futura com provisionamento (cadastrar IP automaticamente ao ativar um VPS).
- **RBAC**: Administrador, Operador (NOC), Somente leitura, e (fase 2) acesso de Cliente restrito aos próprios IPs.
- Login com senha + **2FA TOTP**; sessões JWT; auditoria de ações (módulo *Atividades*).

---

## 4. UI — Estrutura de Telas (seguindo o mockup)

Tema **dark** (base `#0d1220`/`#111827`), cards com cantos arredondados, acento azul primário, badges de severidade coloridos (Crítica=vermelho, Alta=laranja, Média=amarelo, Baixa=verde), fonte sans (Inter/Roboto).

### Sidebar

**Principal:** Dashboard · IPs Monitorados · Domínios Monitorados · Alertas (badge) · Tickets (badge)
**Gerenciamento:** Clientes · Serviços · Grupos de IP · Importações · Integrações
**Ferramentas:** Diagnóstico · Delist Requests · Templates · Regras de Alerta
**Relatórios:** Histórico · Reputação · Blacklists · Atividades
**Config:** Configurações (SMTP, Pushover, DQS key, resolver, ping, agendador, usuários)

### Dashboard (tela principal)

1. **Cards KPI (5):** IPs Monitorados, IPs Limpos (%), IPs com Listagem (%), Listagens Críticas (%), Domínios Monitorados — cada um com variação mensal (↑/↓).
2. **Tabela "IPs com Listagens Recentes"** com abas por severidade (Todos/Críticos/Altos/Médios/Baixos + contadores), colunas: IP (com dot de severidade), Cliente/Serviço, Listas (badges das blacklists + "+N"), Severidade, Última Detecção, Ações (ver/menu).
3. **Donut "Listagens por Severidade"** com total central e legenda com contagens/percentuais.
4. **Gráfico de linhas "Listagens ao Longo do Tempo"** (4 séries por severidade).
5. **Painel "Detalhes do IP"** (drill-down ao clicar na tabela): dados do cliente/serviço/grupo/ASN/datacenter, resumo de listagens com datas, botões: Ver Diagnóstico · Abrir Ticket · Solicitar Delist · Bloquear SMTP.
6. **Painel "Diagnóstico Rápido"** com checklist rDNS/PTR/SPF/DKIM/DMARC/porta 25/reputação.
7. **Feed "Atividades Recentes"** (entrou em blacklist, saiu, ticket criado, delist solicitado).

---

## 5. Modelo de Dados (resumo)

```sql
clients        (id, name, external_id, contact_email, created_at)
services       (id, client_id, name, type, external_ref)          -- ex.: "Cloud VPS #1234"
ip_groups      (id, name, datacenter, ping_mode, check_interval, settings jsonb)
ip_blocks      (id, cidr CIDR, group_id, client_id, service_id, asn, note)
monitored_ips  (id, ip INET UNIQUE, block_id, group_id, client_id, service_id,
                enabled bool, ping_status enum, last_ping_at,
                current_status enum(clean,listed,unchecked,error), risk_score int)
blacklists     (id, name, zone, type enum(ipv4,ipv6,domain), default_severity,
                return_code_map jsonb, delist_url, lookup_url, rate_limit_qps,
                enabled bool, requires_key bool, api_key_encrypted)
listings       (id, ip_id, blacklist_id, sublist, severity, detected_at,
                removed_at, duration, txt_reason, status enum, ticket_ref)
                -- particionada por mês
check_runs     (id, started_at, finished_at, ips_checked, ips_skipped_ping, errors)
alert_rules    (id, name, conditions jsonb, channels jsonb, escalation jsonb, enabled)
notifications  (id, listing_id, rule_id, channel, recipient, sent_at, status)
domains        (id, domain, client_id, ... )                       -- espelho de monitored_ips
users          (id, email, role, totp_secret, api_token_hash)
activity_log   (id, user_id, action, entity, payload jsonb, created_at)
settings       (key, value_encrypted)                              -- SMTP, Pushover, DQS, resolver
```

---

## 6. Segurança e Boas Práticas

- Chaves (DQS, Pushover, SMTP) criptografadas em repouso (Fernet/libsodium) — nunca em texto plano no banco ou logs.
- Resolver Unbound isolado, sem recursão aberta.
- Rate limiting e backoff exponencial por blacklist; nunca ultrapassar limites do DQS contratado.
- Validação estrita de entrada de CIDR (evitar expansão acidental de /8).
- Auditoria completa de ações administrativas.
- Backups diários do PostgreSQL + retenção de 30 dias.
- Healthchecks (endpoint `/health`) e métricas Prometheus (fase 2) para monitorar o próprio monitor.

---

## 7. Roadmap por Fases

### Fase 1 — MVP (estimativa: 4–6 semanas)
- [ ] Setup do projeto (Docker Compose: api, worker, beat, postgres, redis, unbound, nginx)
- [ ] Modelo de dados + migrations
- [ ] CRUD de blacklists com seed inicial + suporte a Spamhaus DQS
- [ ] CRUD de clientes, serviços, grupos, blocos/IPs + importação CSV
- [ ] Worker de ping (3 modos) + worker DNSBL assíncrono + agendador
- [ ] Ciclo de vida de listagens + deduplicação de alertas
- [ ] Notificações: E-mail (SMTP) + Pushover, com templates
- [ ] Dashboard completo no padrão do mockup + tabela de listagens + detalhes do IP
- [ ] Autenticação (senha + 2FA) e RBAC básico
- [ ] Exportação CSV do período

### Fase 2 — Operação (4 semanas)
- [ ] Diagnóstico automático completo (FCrDNS, SPF/DKIM/DMARC, porta 25)
- [ ] Regras de alerta avançadas + escalonamento + snooze/manutenção
- [ ] Telegram, Slack/Discord, Webhook HMAC
- [ ] Workflow de Delist Requests com re-verificação acelerada
- [ ] Monitoramento de domínios (SURBL/DBL)
- [ ] Relatórios PDF/XLSX + digest diário
- [ ] Integração com sistema de tickets (criação automática)

### Fase 3 — Escala e automação
- [ ] API pública documentada + provisionamento automático (novo VPS ⇒ IP monitorado)
- [ ] Portal do cliente (visão restrita aos próprios IPs)
- [ ] Score de risco/reincidência por IP e por cliente
- [ ] Bloqueio automático de SMTP via integração com firewall/hypervisor (com aprovação dupla)
- [ ] Métricas Prometheus + alertas de saúde do próprio sistema
- [ ] Multi-idioma (PT-BR/EN)

---

## 8. Requisitos de Produção

| Item | Especificação mínima |
|---|---|
| Servidor | 4 vCPU, 8 GB RAM, 100 GB SSD (para ~5.000 IPs monitorados) |
| SO | Ubuntu 24.04 LTS ou Debian 12 |
| Rede | IP com rDNS válido; ICMP de saída liberado; porta 53/UDP+TCP de saída liberada para o Unbound |
| Docker | Engine 27+ e Compose v2 |
| DNS | **Não** usar resolver do provedor/público para as consultas DNSBL |
| Chaves | Conta Spamhaus DQS ativa; registro do IP do resolver na Barracuda |
| E-mail | Conta SMTP dedicada para alertas (com SPF/DKIM configurados) |
| Pushover | Application token criado em pushover.net |

---

## 9. Decisões em Aberto (para alinhar antes do desenvolvimento)

1. Stack final: Python/FastAPI (recomendado) ou Node.js?
2. Sistema de tickets a integrar (WHMCS? osTicket? interno?)
3. Volume estimado de IPs no primeiro ano (dimensiona workers e plano DQS)?
4. Portal do cliente entra no escopo inicial ou fase 3?
5. "Bloquear SMTP" será integração real (firewall/hypervisor) ou apenas registro de ação manual no MVP?
6. Retenção do histórico: 12 ou 24 meses?
