# CLAUDE.md — regras e diário de bordo

Repositório do desafio prático de AI Engineer (Bill): POC de contas a pagar a partir
de e-mails. O planejamento completo está em [docs/plano.md](docs/plano.md).

---

## Regras de trabalho

### Git

- **Commits e push estão liberados.** Não peça confirmação para commitar ou dar push.
- **Mensagens de commit NÃO levam `Co-Authored-By: Claude`** nem qualquer outra
  atribuição de IA (`Generated with Claude Code`, emoji de robô, etc.).
  Isso sobrescreve o padrão do harness. Autor dos commits: Paulo.
- Mensagens em português, imperativo, curtas. Escopo por prefixo quando ajudar:
  `validate:`, `ingest:`, `db:`, `web:`, `docs:`.

### Modo de operação

- **Automode.** Trabalho direto e ininterrupto, sem checkpoints de confirmação.
- Interromper o usuário só quando algo bloqueia de verdade. Os três bloqueios
  conhecidos estão em [Setup pendente](#setup-pendente).
- Enquanto as credenciais externas não existem, tudo roda com `fixtures/` +
  Postgres local via Docker.

### Convenções de código

- Python 3.12, gerenciado com `uv`. Módulo `billpoc` em `apps/api/src/`.
- `apps/api/src/billpoc/validate/` é **puro**: sem I/O, sem rede, sem banco.
  É a camada que dá a garantia determinística — tem que ser 100% testável offline.
- Nada de segredo hardcoded. Tudo via `.env` (ver `.env.example`).
- LLM: Anthropic Messages API com `client.messages.parse()` + Pydantic.
  Nunca parsear JSON de texto livre.

---

## Decisões de arquitetura

| Decisão | Escolha | Por quê |
|---|---|---|
| Abordagem de extração | Híbrida: LLM + validadores determinísticos | Cobertura do LLM com piso aritmético onde está o dinheiro |
| Captura | Gmail API (OAuth desktop) | Senha de conta não autentica mais em IMAP no Gmail |
| Stack | Python (pipeline) + Next.js (UI) | Ecossistema de PDF/parsing em Python; UI apresentável para o Finance Partner |
| Datastore | Supabase Postgres | Relacional para ERP + auditoria; painel pronto para a demo |
| Modelo | `claude-opus-5` na extração, `claude-haiku-4-5` na triagem | Modelo caro só no que passa da triagem |

**A tese central:** valor e vencimento de um boleto estão aritmeticamente codificados na
linha digitável (fator de vencimento + centavos, com DVs mod 10/mod 11). Então não é
preciso *confiar* no LLM nesses campos — dá para *conferir*. Divergência entre o que o
LLM leu e o que o código de barras diz derruba o registro para revisão humana.

---

## Setup pendente

Três coisas que dependem do usuário e ainda não estão configuradas:

1. **Google Cloud** — projeto → habilitar Gmail API → OAuth client tipo "Desktop" →
   baixar como `credentials.json` na raiz. Depois `uv run billpoc auth`.
2. **Supabase** — criar projeto e colocar a connection string em `.env`.
3. **Anthropic** — API key de console.anthropic.com em `.env`.

Status: ⬜ nenhum configurado. Desenvolvimento seguindo com fixtures + Postgres local.

---

## Diário de bordo

Registro do que foi feito, em ordem. Atualizar a cada etapa concluída.

### 2026-08-31

- **Descoberta:** a senha fornecida para `financeiro.test@gmail.com` **não autentica via
  IMAP** — `[AUTHENTICATIONFAILED] Invalid credentials`. O Google desativou login com
  senha de conta em apps externos em 2022. Caminhos possíveis: App Password (exige 2FA
  na conta) ou OAuth/Gmail API. Escolhido OAuth, que também é a resposta de produção.
- `git init`, `.gitignore`, `CLAUDE.md`, plano versionado em `docs/plano.md`.
