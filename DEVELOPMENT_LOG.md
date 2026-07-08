# Blacklist Monitor — Log de Desenvolvimento e Pendências

**Última atualização:** 2026-07-07 (pacote de idiomas concluído)
**Objetivo deste arquivo:** dar contexto completo para retomar o desenvolvimento em outra
sessão, sem precisar reler todo o histórico de conversa. Ver também `PLANEJAMENTO-blacklist-monitor.md`
(escopo original) e `README.md` (como rodar).

---

## 1. Estado atual de produção

- Rodando via **systemd** (`/etc/systemd/system/blacklistmonitor.service`), habilitado no boot,
  restart automático em falha. **Docker não está instalado** neste servidor — a stack real é
  Python nativo + SQLite, não a stack do `docker-compose.yml` (que existe no repo mas não foi
  usada aqui).
- Logs: `/var/log/blacklistmonitor.log`.
- Config real (secrets gerados de verdade, fora do git): `/root/blacklistmonitor/.env`.
- Banco: SQLite em `/root/blacklistmonitor/blacklist_monitor.db` — **zerado de dados de
  demonstração**, só contém as 8 blacklists padrão (config real do motor) e o usuário admin.
- Acesso: `http://<ip-do-servidor>:8000` — **HTTP puro, sem TLS/domínio configurado**.
- **Todo o backend (`/api/*`, exceto `/api/auth/login` e `/health`) exige JWT válido.** Isso foi
  uma correção feita nesta sessão — inicialmente as rotas de leitura (`GET`) não exigiam token,
  só criar/editar/excluir. Agora está uniforme: sem login, nada funciona (nem visualizar).
- Login do admin criado nesta sessão foi entregue ao usuário no chat (senha gerada
  aleatoriamente, exibida uma única vez no log). **Se você não tem essa senha, gere uma nova:**
  apague a linha do usuário na tabela `users` e reinicie o serviço (o seed recria o admin com
  nova senha aleatória e loga em `/var/log/blacklistmonitor.log`), ou troque manualmente via
  Python (`app.security.hash_password`).
- **Git**: repositório local (`git init` já feito), mas **nada foi commitado ainda** — todo o
  código está como untracked. Perguntar ao usuário antes do primeiro commit.

---

## 2. O que foi implementado (testado end-to-end nesta sessão)

Cobertura da Fase 1 (MVP) do `PLANEJAMENTO-blacklist-monitor.md`:

- **Modelo de dados completo** (`app/models.py`): clients, services, ip_groups, ip_blocks,
  monitored_ips, domains, blacklists, listings, check_runs, alert_rules, notifications,
  activity_log, users, settings — igual ao desenho da seção 5 do planejamento.
- **Cadastro de IPs**: CIDR, range (`a.b.c.d-e`) e IP avulso, com expansão automática e limite
  de segurança configurável (`MAX_CIDR_EXPANSION`, padrão /22). Importação CSV. Testado com
  CIDRs reais, incluindo rejeição de `/8` por estourar o limite.
- **Motor DNSBL** (`app/services/dnsbl.py`): reversão de octetos (IPv4) e nibbles (IPv6),
  suporte a chave Spamhaus DQS (`{key}` no template da zona), rate limiting por zona
  (token bucket), detecção de erro de resolver Spamhaus (127.255.255.x) vs. listagem real,
  interpretação de código de retorno → sublista/severidade via `return_code_map` editável.
  Testado com consultas DNS reais contra Barracuda/SpamCop/PSBL/SORBS/UCEPROTECT.
- **Pré-check de ping** (`app/services/ping.py`): 3 modos (skip_unreachable, check_all,
  tcp_fallback), cache configurável, usa o binário `ping` do sistema (não precisa de root).
  Testado com ICMP real.
- **Diagnóstico rápido** (`app/services/diagnostics.py`): rDNS/PTR, FCrDNS, SPF, DKIM, DMARC,
  porta 25. Testado com DNS real contra um IP público.
- **Ciclo de vida de listagem + deduplicação**: alerta só na transição de estado (entrou/saiu),
  nunca a cada ciclo (`app/services/checker.py`).
- **Notificações**: e-mail (SMTP) e Pushover, com regras de alerta (condições: severidade
  mínima, blacklist, grupo, cliente, entrada/saída) — `app/services/notifications.py`.
  Testado o caminho de falha (SMTP não configurado → grava notificação com status "failed",
  não derruba a aplicação).
- **Configurações em runtime**: SMTP/Pushover/DQS/resolver DNS editáveis pela UI e aplicados
  imediatamente (sem restart) via `app/runtime_settings.py` — isso era um bug real encontrado
  e corrigido nesta sessão (as configs salvas não tinham efeito nenhum antes da correção).
- **Autenticação**: JWT + bcrypt, RBAC (admin/operator/readonly), 2FA TOTP **no login** (ver
  pendência abaixo — falta o *enrollment*). Troca de senha própria implementada
  (`POST /api/auth/change-password`) com UI em Configurações → Minha Conta.
- **Todo o `/api/*` exige autenticação** (correção desta sessão — ver seção 1).
- **Scheduler** (`app/services/scheduler.py`, APScheduler in-process): verificação geral
  (intervalo configurável) + reverificação acelerada de IPs atualmente listados.
- **UI server-rendered** (Jinja2 + JS puro + Chart.js/Tailwind via CDN, tema escuro igual ao
  mockup): Dashboard, IPs Monitorados (+ import CIDR/CSV), Domínios, Clientes, Grupos de IP,
  Blacklists (CRUD), Regras de Alerta (CRUD básico), Configurações, Atividades, Login.
- **Exportação CSV** de listagens por período (`/api/reports/export.csv`, baixado via JS com
  token, não link direto).
- **Pacote de idiomas** (`app/static/js/i18n.js`): interface traduzida para PT-BR (padrão),
  inglês, espanhol, francês e alemão, selecionável em Configurações → Idioma (troca é global,
  salva no banco via `app/runtime_settings.py`, recarrega a página). Motor client-side
  (`t()`/`applyI18n()`/`data-i18n*`) cobre navegação, todas as páginas de CRUD (IPs, domínios,
  clientes, grupos, blacklists, regras de alerta, usuários, logs, atividades) e o dashboard,
  incluindo textos gerados dinamicamente em JS (toasts, confirms, títulos de modal). Esta sessão
  retomou um trabalho que tinha parado pela metade: o motor de i18n e os textos de navegação/
  configurações já existiam, mas praticamente nenhuma chave de conteúdo de página (`dashboard.*`,
  `ips.*`, `clients.*`, `groups.*`, `blacklists.*`, `domains.*`) tinha sido preenchida no arquivo
  de traduções — os templates referenciavam chaves inexistentes, então essas páginas exibiam a
  chave crua em vez de texto. Também corrigidos bugs reais achados no meio do trabalho: `ips.js`
  referenciava `STATUS_LABEL`/`PING_LABEL` que não existiam mais em lugar nenhum (usa agora
  `statusLabel()`/`pingLabel()` de `app.js`), e `alert-rules.js` referenciava um `SEVERITY_LABEL`
  que nunca existiu (usa agora `severityLabel()`).

---

## 3. O que falta (gaps conhecidos, não implementados ainda)

### 3.1 Gaps dentro do próprio escopo de Fase 1 (deveriam existir num MVP "completo")

- **Gestão de usuários**: não existe `/api/users` nem tela de usuários. Só dá para logar com
  o admin criado no seed. RBAC (admin/operator/readonly) existe no modelo e é checado nas
  rotas, mas não há como criar operadores/readonly pela UI/API ainda.
- **Enrollment de 2FA**: o login já valida TOTP se `totp_enabled=True`, mas não existe endpoint
  para gerar o secret, mostrar QR code e o usuário ativar o 2FA. `generate_totp_secret()` existe
  em `app/security.py` mas não é chamado em lugar nenhum.
- **Tokens de API por usuário**: campo `api_token_hash` existe no modelo `User` mas não é usado
  — não há como gerar/usar um token de API (só JWT de sessão via login).
- **Página "Tickets"**: item da sidebar existe mas não é clicável (só um badge). Não há listagem
  de tickets, só o campo `ticket_ref` (string tipo `#8421`) preenchido ao clicar "Abrir Ticket"
  num listing — não é uma integração real com sistema de tickets.
- **Página "Reputação" / "Relatórios" dedicados**: o mockup original tem itens de sidebar para
  isso; hoje só existe `/api/reports/top-offenders` (endpoint pronto, sem UI consumindo) e
  export CSV. Faltam: relatório por cliente, por grupo/datacenter, tempo médio de delist, IPs
  reincidentes (o campo `risk_score` existe e incrementa a cada nova listagem, mas não tem
  nenhuma tela/relatório que o exponha).
- **Página "Templates"**: notificações usam um template HTML fixo no código
  (`render_listing_email` em `notifications.py`). Não há editor de templates pela UI.
- **Página "Delist Requests" dedicada**: existe a ação "Solicitar Delist" por listagem, mas não
  uma tela central listando todos os delists solicitados/pendentes.
- **Botão "Bloquear SMTP"**: aparece no mockup original, não foi implementado (nem como stub) —
  ok como está, é item de Fase 3 no planejamento (bloqueio real via firewall/hypervisor).
- **Diagnóstico como ferramenta standalone**: hoje só existe diagnóstico *por IP já cadastrado*
  (drilldown do dashboard). O mockup sugere uma tela "Diagnóstico" separada onde daria pra
  digitar qualquer IP/domínio avulso e rodar o diagnóstico sem precisar cadastrar antes.

### 3.2 Fase 2 do planejamento (não iniciada)

- Escalonamento de alertas: campo `escalation` (jsonb) existe no modelo `AlertRule` e na UI/API
  de criação, mas **nada processa esse campo** — não há worker/lógica que verifique "listagem
  crítica não reconhecida em N minutos → notifica segundo nível".
- Silenciamento/snooze por IP, bloco ou blacklist (janela de manutenção) — não implementado,
  nenhum campo no modelo para isso ainda.
- Digest diário/semanal por e-mail — não implementado.
- Canais adicionais: Telegram, Slack/Discord, Webhook genérico HMAC, SMS — não implementados
  (só e-mail e Pushover existem, ver `app/services/notifications.py`).
- Integração real com sistema de tickets (WHMCS/osTicket/HubSpot/interno) — não implementada
  (ver 3.1).
- Automação de delist onde há API (ex.: formulário da Barracuda) — não implementada, hoje é
  só um link de delist configurado por blacklist (`delist_url`) que o operador abre manualmente.
- Relatórios PDF/XLSX — só CSV existe hoje.

### 3.3 Fase 3 do planejamento (não iniciada, esperado)

- API pública documentada + provisionamento automático (novo VPS → IP monitorado
  automaticamente via API de provisionamento externa).
- Portal do cliente (acesso restrito aos próprios IPs).
- Score de risco/reincidência agregado por cliente (hoje só existe por IP individual).
- Bloqueio automático de SMTP via firewall/hypervisor com aprovação dupla.
- Métricas Prometheus + alertas de saúde do próprio sistema (hoje só `/health` simples existe).
- ~~Multi-idioma (PT-BR/EN) — hoje é só PT-BR.~~ Feito nesta sessão (ver seção 2), com 5 idiomas
  em vez de 2.

### 3.4 Infraestrutura / produção (pendências técnicas)

- **Stack real vs. planejada**: rodando nativo (systemd + SQLite + resolver DNS do sistema),
  não a stack completa do `docker-compose.yml` (Postgres 16 + Unbound dedicado + Celery/Redis).
  Se o volume de IPs crescer, ou se Spamhaus começar a bloquear/degradar as consultas por vir
  de um resolver compartilhado, será necessário:
  1. Instalar Docker (não estava disponível no ambiente de build desta sessão).
  2. Subir `docker-compose up -d --build` (já teste-ável, mas não testado nesta sessão por
     falta de Docker).
  3. Migrar dados do SQLite pro Postgres (não há script de migração pronto para isso ainda).
- **Sem TLS/domínio**: acesso é HTTP puro em `IP:8000`. Precisa de domínio apontando pro IP +
  Nginx como proxy reverso + Let's Encrypt.
- **Sem chave Spamhaus DQS configurada**: `Spamhaus ZEN`/`Spamhaus DBL` estão cadastrados mas
  vão sempre dar erro de resolução até alguém configurar a chave em Configurações (ou por
  blacklist individual). Confirmado via teste real nesta sessão (erro "A DNS label is empty"
  sem chave, comportamento correto/seguro — não gera falso positivo, só fica sem checar).
- **Sem testes automatizados**: toda a verificação desta sessão foi manual (curl + scripts
  Python ad-hoc). Não existe suite pytest no repo.
- **Sem CI/CD.**
- **Sem backup automatizado** do SQLite (nem do Postgres, quando/se migrar).
- **Sem rate-limit/backoff exponencial em falhas de DNS** — existe rate limiting por QPS
  configurado por blacklist, mas não um backoff progressivo quando uma zona começa a falhar
  repetidamente (ex.: bloqueio temporário do resolver).

---

## 4. Sugestão de prioridade para a próxima sessão

Ordem sugerida (dos gaps que mais importam pro uso real como provedor IaaS):

1. **Gestão de usuários + enrollment de 2FA** — hoje só existe 1 admin; times de NOC precisam
   de contas próprias com RBAC de verdade.
2. **Configurar chave Spamhaus DQS** (dado real do cliente, não é código) + validar que o
   resolver DNS em uso não está sendo bloqueado por volume (considerar Unbound dedicado se for
   monitorar centenas/milhares de IPs).
3. **Página de Reputação/Relatórios** consumindo `top-offenders` + adicionando relatório por
   cliente e IPs reincidentes (o dado já existe, falta só a tela).
4. **Escalonamento de alertas** (processar o campo `escalation` já existente no schema).
5. **TLS + domínio**, quando o usuário tiver um domínio disponível.
6. Canais adicionais de notificação (Telegram é o mais barato/rápido de agregar valor).
7. Testes automatizados básicos (pelo menos o motor DNSBL, CIDR e ciclo de vida de listagem,
   que são a lógica mais crítica).
