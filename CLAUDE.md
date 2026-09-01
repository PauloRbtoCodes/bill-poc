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
- Interromper o usuário só quando algo bloqueia de verdade — na prática, só criação de
  conta e digitação de senha, que agentes não fazem.
- Tudo roda offline com `billpoc run --fonte demo --somente-cache`; a caixa real precisa
  das credenciais em [Setup](#setup).

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
| Datastore | Postgres (local via Docker; Supabase opcional) | Relacional para ERP + auditoria; schema idêntico nos dois |
| Modelo | `claude-opus-5` na extração, `claude-haiku-4-5` na triagem | Modelo caro só no que passa da triagem |

**A tese central:** valor e vencimento de um boleto estão aritmeticamente codificados na
linha digitável (fator de vencimento + centavos, com DVs mod 10/mod 11). Então não é
preciso *confiar* no LLM nesses campos — dá para *conferir*. Divergência entre o que o
LLM leu e o que o código de barras diz derruba o registro para revisão humana.

---

## Setup

| Item | Status | Onde |
|---|---|---|
| Gmail OAuth | ✅ autorizado | `credentials.json` + `token.json` na raiz (fora do git) |
| Anthropic API key | ✅ configurada | `ANTHROPIC_API_KEY` no `.env` |
| Banco | ✅ Postgres local via `docker compose` | `DATABASE_URL` no `.env` |
| Supabase | ⬜ opcional | mesmo schema; só trocar `DATABASE_URL`. Ver [docs/setup.md](docs/setup.md) |

`uv run billpoc doctor` confere tudo. O passo a passo para reproduzir num ambiente novo
está em [docs/setup.md](docs/setup.md).

---

## Diário de bordo

Registro do que foi feito, em ordem. Atualizar a cada etapa concluída.

### 2026-08-31

- **Descoberta:** a senha fornecida para `financeiro.test@gmail.com` **não autentica via
  IMAP** — `[AUTHENTICATIONFAILED] Invalid credentials`. O Google desativou login com
  senha de conta em apps externos em 2022. Caminhos possíveis: App Password (exige 2FA
  na conta) ou OAuth/Gmail API. Escolhido OAuth, que também é a resposta de produção.
- `git init`, `.gitignore`, `CLAUDE.md`, plano versionado em `docs/plano.md`.
- **`validate/`** — boleto, CNPJ, chave NF-e, Pix. Aritmética pura, sem I/O.
  Verificado contra vetores publicamente conferíveis: as três âncoras FEBRABAN do fator
  de vencimento, o exemplo oficial de CNPJ alfanumérico da Receita, o valor canônico do
  CRC16-CCITT. Descoberta lateral: as linhas digitáveis que circulam em blogs falham nos
  próprios DVs — por isso os testes usam boletos construídos.
- **`db/schema.sql`** — 16 tabelas, 2 views. Aplicado e verificado em Postgres 16 local.
- **`extract/` + `rules.py`** — schema com evidência por campo; política de decisão em
  código, fora do prompt.
- **`ingest/`** — parser RFC822 compartilhado entre `.eml` e Gmail API.
- **`pipeline.py` + `store/` + `cli.py`** — as seis etapas, persistência transacional,
  CLI com `doctor`, `auth`, `ingest`, `semear`, `run`, `report`, `inspecionar`.
- **`demo/`** — 10 cenários com PDFs reais e cache de LLM pré-populado. O projeto roda
  sem nenhuma credencial. Rodar isso ponta a ponta revelou três bugs (extração via XML
  perdia a marca de determinística; DANFE + XML geravam duas contas; identificador do
  boleto de arrecadação fora da faixa), todos corrigidos.
- **`api.py` + `apps/web/`** — API HTTP e as três telas do Finance Partner. Ver a tela
  revelou mais dois bugs: fornecedor sem CNPJ sumia da lista, e confiança geral ia a zero
  por campo ausente. Corrigidos na raiz (coluna `beneficiario_nome` no payable; campos
  sem valor não entram no cálculo da confiança).
- **`README.md`** — os entregáveis 1, 3, 4 e 5.

**Estado:** 107 testes passando (12 ponta a ponta contra Postgres real), ruff e tsc
limpos.

### 2026-08-31 (cont.) — credenciais reais

- **Gmail OAuth concluído.** O servidor de callback local não sobrevive neste ambiente
  (processos spawnados de um comando são mortos), então o fluxo virou dois passos manuais
  em `scripts/gmail_auth.py`: gerar URL → colar a URL de redirecionamento. Precisou de
  `OAUTHLIB_INSECURE_TRANSPORT=1` porque o redirect é `http://localhost`.
- **Bug corrigido:** `GMAIL_CREDENTIALS=credentials.json` no `.env` resolvia a partir do
  cwd. Agora caminho relativo conta a partir da raiz do repo (`config._caminho`).
- **`token.json` gerado** — `billpoc doctor` todo verde, leitura da caixa real testada
  (8 e-mails: 2 boletos encaminhados de `gestao.btk@gmail.com`, resto ruído).
- **Chave da Anthropic é identity-linked** → exige cabeçalho `anthropic-workspace-id`.
  Suporte adicionado em `Extrator.client` via env `ANTHROPIC_WORKSPACE_ID`.

**Pendente do usuário:** preencher `ANTHROPIC_WORKSPACE_ID` no `.env` (ou trocar por uma
chave de conta comum). Depois: `billpoc ingest && billpoc run` processa a caixa real.

### 2026-08-31 (cont.) — pipeline rodou sobre a caixa real

- Chave trocada por uma que funciona. `billpoc ingest --limite 60` baixou 48 e-mails.
- **Bug:** `adaptive thinking` não existe em `claude-haiku-4-5` (400). Agora só é enviado
  para Opus/Sonnet 5 e família 4.6+.
- **Bug:** dois boletos vinham em PDF cifrado (senha = CPF/CNPJ do pagador). `pdfplumber`
  abre, mas a API da Anthropic recusa. Detecção por `/Encrypt` nos bytes; o registro cai
  em revisão com o motivo, sem quebrar o lote.
- **Resultado real:** 48 e-mails → 42 ruído (87%), 6 cobranças, 6 payables (2 auto, 4
  revisar), **0 erros**, US$ 0,36. Fornecedores extraídos: LELLO CONDOMÍNIOS (R$ 415,11),
  STARFIBER/LORD INTERNET (R$ 89,90 — mesmo ISP com dois nomes), MAC IBIRAPUERA.
- A caixa também tem e-mails de teste de outro candidato ("Conciliação Maio/2026",
  "Demo Conciliacao v21") — todos classificados como ruído corretamente.

### 2026-09-01 — rodada final antes da entrega

Fechados os itens que o README prometia e o código não fazia:

- **Encaminhamento.** Todas as cobranças da caixa real chegam como `Fwd:` da mesma
  pessoa. `detectar_encaminhamento()` lê o cabeçalho original de dentro do corpo (Gmail
  em inglês e português, Outlook), pegando o bloco mais profundo em encaminhamento
  aninhado. Sem isso, os seis boletos casariam com um fornecedor `gmail.com`.
- **Golden set.** 16 casos da caixa real rotulados à mão, rodando em modo somente-cache.
  Pisos assimétricos: recall 100%, precisão 90%. `billpoc golden` imprime as métricas.
- **Exportação.** CNAB 240, CSV e layout de ERP. Os cinco registros do CNAB são
  declarados como listas de campos nomeados — foi assim que apareceu que meu header de
  lote tinha 235 caracteres em vez de 240.
- **Enriquecimento pelo histórico.** O README dizia que existia; agora existe. Categoria
  confirmada por humano vence o LLM, três cobranças em cadência viram `recorrente` com
  origem `historico`, e valor fora do padrão alerta. Detecção de cadência exige
  consistência, não só mediana plausível.
- **Casamento por domínio corporativo** quando não há CNPJ, com lista de provedores
  pessoais excluídos.
- **PDF protegido por senha** (2 dos 6 boletos reais) detectado antes de gastar a chamada.
- **CI** com Postgres de serviço, e `docs/roteiro-demo.md` para a call.

**Estado final:** 151 testes, ruff e tsc limpos, build de produção do front OK.
Caixa real: 48 e-mails, 42 ruído, 6 cobranças, 0 erros, US$ 0,36, acurácia 100%.
Duas caixas separadas: `--fonte eml` (real) e `--fonte demo` (cenários curados).
