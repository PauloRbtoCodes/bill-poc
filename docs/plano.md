# POC — Contas a Pagar por E-mail (desafio Bill)

## Contexto

O desafio pede a primeira fatia do fluxo de contas a pagar do Bill: capturar cobranças
que chegam por e-mail, extrair os dados e registrá-los de forma estruturada. Os cinco
entregáveis são: (1) três abordagens com trade-offs e uma escolha justificada, (2) POC
funcionando, (3) modelo de dados para ERP + auditoria, (4) proposta de interação do
Finance Partner até o agendamento bancário manual, (5) notas de limitação e escala.

A entrega principal é uma **demo ao vivo com mexida no código junto**. Isso enviesa as
decisões: o repo precisa ser navegável, as decisões precisam estar escritas, e a parte
que mais importa na avaliação — *"mexe com dinheiro, errar valor ou vencimento tem
custo; como você lida com a incerteza conta bastante"* — precisa ser visível na tela,
não só no README.

`/home/inteli/Documentos/case-bill` está vazio. Projeto do zero.

### Decisões já tomadas

| Item | Escolha |
|---|---|
| Captura | Gmail API via OAuth (desktop flow) |
| Stack | Python 3.12 + FastAPI (pipeline) / Next.js (UI de revisão) |
| Datastore | Supabase Postgres |
| LLM | Anthropic Messages API, `client.messages.parse()` com Pydantic |
| Escopo | Completo — pipeline + UI + documentação dos 5 itens |

---

## A tese técnica: incerteza com piso determinístico

O ponto central da POC, e o que eu quero mostrar primeiro na call:

**Num boleto brasileiro, valor e vencimento não precisam ser confiados ao LLM — eles
estão aritmeticamente codificados na linha digitável.**

- Posições 34–37 da linha digitável de 47 dígitos = *fator de vencimento* (dias desde
  07/10/1997, com o ciclo reiniciado em 22/02/2025 após estourar 9999).
- Posições 38–47 = valor em centavos.
- Os 5 dígitos verificadores (mod 10 nos campos 1–3, mod 11 no DV geral) provam que a
  própria linha digitável não foi lida errado.

Então o pipeline extrai com LLM (cobertura ampla, evolui rápido com novos fornecedores)
e **valida com aritmética** (garantia dura exatamente onde está o dinheiro). Quando os
dois discordam, o registro **nunca** entra no caminho automático — vai para a fila de
revisão com os dois valores lado a lado.

O mesmo vale para os outros campos:

| Campo | Fonte determinística disponível |
|---|---|
| valor, vencimento | linha digitável (fator + centavos) |
| CNPJ | DV mod 11 |
| nº da NF, CNPJ emitente | chave de acesso NFe de 44 dígitos (DV mod 11) — decodifica UF, AAMM, CNPJ, modelo, série, número |
| todos os campos da NFe | XML anexo, quando presente → zero LLM |
| valor Pix | BR Code EMV, campo 54, com CRC16-CCITT |
| boleto de concessionária | 48 dígitos iniciados em `8`, mod 10 ou mod 11 conforme o 3º dígito |

Sobra para o LLM só o que é genuinamente ambíguo: **é uma cobrança ou é ruído**,
**categoria da despesa**, **recorrente x único**, e campos de documentos sem código de
barras. Que é exatamente onde erro é barato e reversível.

---

## Entregável 1 — Três abordagens (vai no README)

**A. Determinística / templates por fornecedor.** Regex para linha digitável e CNPJ,
`pdfplumber` para texto, parser de XML da NFe, um template por remetente conhecido.
*Prós:* barata, rápida, auditável, zero alucinação. *Contras:* cada fornecedor novo é
trabalho de engenharia; quebra em mudança de layout; cobertura ruim no dia 1.

**B. LLM/VLM ponta a ponta.** Corpo do e-mail + PDF direto para um modelo multimodal
com structured output. *Prós:* cobertura imediata de layouts nunca vistos; custo
marginal ~zero por fornecedor novo; muda-se o comportamento editando prompt e schema.
*Contras:* não determinística; pode alucinar um valor plausível; sem piso de garantia
justo no campo mais caro de errar.

**C. Híbrida — LLM para cobertura, validadores determinísticos como porteiro.**
✅ **Escolhida.** LLM classifica e extrai; validadores aritméticos conferem; divergência
ou checksum inválido derruba o registro para revisão humana com evidência apontada.

**Por quê C**, amarrado ao briefing deles:
- *"fase inicial, necessidades podem evoluir rápido com novos clientes"* → A não
  escala: cada cliente traz fornecedores novos e vira fila de engenharia. C absorve
  fornecedor novo sem deploy.
- *"errar valor ou vencimento tem custo"* → B sozinha não tem piso. C tem, e o piso
  cobre exatamente valor, vencimento e linha digitável.
- C também degrada bem: onde não há código de barras, ela simplesmente vira B com
  confiança menor e revisão obrigatória — não quebra, escala de confiança.

---

## Entregável 3 — Modelo de dados (Supabase Postgres)

Dois domínios separados de propósito. `org_id` em tudo (multi-tenant desde o início) +
RLS no Supabase.

### Lado ERP (o registro de contas a pagar)

- **`vendors`** — `cnpj` único, razão social, nome fantasia, categoria padrão, método
  de pagamento padrão.
- **`expense_categories`** — plano de contas simples, hierárquico (`parent_id`).
- **`payables`** — o registro central: `vendor_id`, `document_type`, `document_number`
  (nº NF), `amount_cents`, `issue_date`, `due_date`, `competence_date`, `category_id`,
  `recurrence` (`one_off` | `recurring`), `recurrence_group_id`, `status`
  (`needs_review` | `approved` | `scheduled` | `paid` | `rejected` | `duplicate`),
  `confidence_overall`, `source_document_id`.
- **`payment_instruments`** — 1:N com payable: `kind` (`boleto_bancario` |
  `boleto_arrecadacao` | `pix` | `ted`), `linha_digitavel`, `barcode`, `pix_emv`,
  `decoded` jsonb (fator e valor decodificados, para o reviewer inspecionar).
- **`payment_schedules`** — `scheduled_date`, `bank`, `scheduled_by`,
  `bank_confirmation_code`, `paid_at`, `receipt_document_id`. É aqui que o agendamento
  manual do Finance Partner é registrado.
- **`recurrence_groups`** — fornecedor + cadência esperada + valor esperado. Alimenta
  tanto a flag `recurring` quanto o alerta "esse aluguel veio R$ 400 mais caro".

### Lado auditoria (log de processamento de cada e-mail)

Tabelas **append-only**. Nunca se faz `UPDATE` numa linha de auditoria — `payables` é a
projeção mutável, e toda mutação gera uma linha em `review_actions`.

- **`email_messages`** — `gmail_message_id` único (idempotência), thread, remetente,
  assunto, `received_at`, headers jsonb, corpo, `content_hash`, `storage_uri` do RFC822.
- **`documents`** — anexos: `sha256` (dedup), mime, `kind` (`pdf_boleto` | `nfe_xml` |
  `danfe_pdf` | `image`), `storage_uri`.
- **`processing_runs`** — uma execução do pipeline sobre um e-mail, com
  `pipeline_version`, status e erro.
- **`processing_steps`** — por etapa (`triage` | `extract` | `validate` | `enrich` |
  `persist`): `model`, `prompt_version`, `input_tokens`, `output_tokens`, `cost_cents`,
  `latency_ms`, `request_id`, `raw_response` jsonb.
- **`classifications`** — `is_payable`, `confidence`, `doc_type`, `rationale`. O ruído
  também é gravado, com o motivo.
- **`field_extractions`** — *a espinha dorsal da auditoria.* Uma linha por campo:
  `field_name`, `value_normalized`, `source` (`llm` | `barcode` | `nfe_xml` | `regex` |
  `human`), `confidence`, `evidence_snippet`, `evidence_page`. Responde
  "por que esse payable diz R$ 1.234,56?" com a fonte e o trecho do documento.
- **`validation_results`** — `check_name`, `severity` (`info` | `warn` | `block`),
  `passed`, `expected`, `actual`.
- **`review_actions`** — `actor`, `action`, `field_name`, `old_value`, `new_value`,
  `note`. Trilha de quem mudou o quê. Também é o **sinal de treino** para o roadmap.

Replay completo de qualquer valor: `field_extractions` + `validation_results` +
`review_actions`.

---

## Entregável 2 — A POC

### Estrutura do repo

```
case-bill/
  README.md                       # os entregáveis 1, 3, 4, 5 — o documento da call
  docs/{abordagens,modelo-de-dados,finance-partner,limitacoes}.md
  db/schema.sql  db/seed.sql      # aplicado no Supabase
  fixtures/*.eml                  # e-mails salvos — demo offline determinística
  apps/api/                       # Python 3.12, uv
    src/billpoc/
      ingest/{base,gmail,eml}.py
      extract/{schemas,claude}.py  extract/prompts/
      validate/{boleto,cnpj,nfe,pix,rules}.py
      enrich/{vendors,recurrence,category}.py
      store/{db,repositories}.py
      pipeline.py  api.py  cli.py
    tests/
  apps/web/                       # Next.js App Router + Tailwind, 3 telas
```

### Pipeline (`pipeline.py`, 6 etapas)

1. **`ingest`** — Gmail API `users.messages.list` + `get(format='raw')`. Idempotência
   por `gmail_message_id`; anexos por `sha256`. Atrás de uma interface `MailSource`, com
   `EmlSource` lendo `fixtures/` para a demo não depender da rede.
2. **`triage`** — classificador barato (`claude-haiku-4-5`) sobre remetente + assunto +
   corpo + nomes dos anexos → `is_payable`, `confidence`, `doc_type`, `rationale`. Corta
   custo no ruído antes de chamar o modelo caro.
3. **`extract`** — por documento. `client.messages.parse()` com `output_format` Pydantic
   (`ExtractedBill`), PDF entrando como `document` block base64 nativo (sem OCR próprio),
   modelo `claude-opus-5`. **O schema exige, por campo monetário, um
   `evidence` verbatim e uma `confidence`** — grounding reduz alucinação e dá ao
   reviewer algo clicável. NFe com XML anexo pula esta etapa: parser direto.
4. **`validate`** — módulo puro, sem I/O, 100% testável:
   - linha digitável: DVs mod 10/mod 11, decodifica fator de vencimento (tratando o
     rollover de 22/02/2025 — calcula os dois candidatos e escolhe o plausível) e valor;
   - CNPJ mod 11; chave NFe mod 11 com cross-check de CNPJ e nº NF; CRC16 do Pix;
   - sanidade: vencimento em janela plausível, valor > 0;
   - **duplicata**: mesma linha digitável, ou mesmo CNPJ+valor+vencimento, já no banco →
     `possible_duplicate`. Boleto reenviado como lembrete é o caso real mais comum.
5. **`enrich`** — upsert de `vendors` por CNPJ; categoria = histórico do fornecedor
   sobrepondo a sugestão do LLM; recorrência = cadência mensal detectada no histórico.
6. **`persist`** — uma transação: `payables` + `payment_instruments` + todas as linhas
   de auditoria.

### Política de decisão (em código, não no prompt)

```
auto_ok      → triage.confidence ≥ limiar
             ∧ checksum da linha digitável válido
             ∧ valor(LLM) == valor(código de barras)
             ∧ vencimento(LLM) == vencimento(código de barras)
             ∧ DV do CNPJ válido
             ∧ não é duplicata
needs_review → é cobrança, mas falhou qualquer um dos acima
noise        → is_payable = false (gravado com o motivo, reversível em 1 clique)
```

`auto_ok` significa apenas *"vai para a faixa rápida"*. **Nada paga sozinho** — todo
payable passa por aprovação humana antes de virar agendamento.

---

## Entregável 4 — Fluxo do Finance Partner (Next.js, 3 telas)

**1. Caixa de entrada / triagem.** Três faixas: `Pronto` (todos os checks verdes),
`Revisar` (N conflitos), `Ruído` (com o motivo do classificador e um botão "na verdade
é conta"). Colunas: fornecedor, valor, vencimento, confiança, badges dos checks.
Ordenação padrão por vencimento — o que vence antes aparece primeiro.

**2. Detalhe de revisão.** Split view: PDF renderizado à esquerda, campos à direita.
Cada campo com badge de origem (🔒 código de barras / 🤖 IA / ✏️ humano) e o trecho de
evidência no hover. **Conflito mostra os dois valores lado a lado, com o determinístico
pré-selecionado.** Editar um campo grava `review_action` e vira `source = human`,
confiança 1.0. "Aprovar" → `status = approved`.

**3. Agenda de pagamento.** Aprovados agrupados por data de vencimento, filtro padrão
"vence nos próximos 7 dias". Por linha: botão de copiar linha digitável / Pix
copia-e-cola, e "Marcar como agendado" capturando banco, código de confirmação e data —
grava em `payment_schedules`. Em lote: export CSV/OFX para o banco e um export no
formato Conta Azul/Omie (stub, mostrando o shape).

O agendamento bancário continua **manual e fora do sistema** — o FP paga no banco e o
sistema registra que aconteceu. Escalonamento: item ainda em `Revisar` com vencimento
em ≤ 2 dias úteis sobe para o topo marcado como urgente.

---

## Entregável 5 — Limitações e escala (README)

**Limitações da POC:** uma caixa só; sem OCR dedicado para boleto fotografado (a visão
do Claude cobre a maioria e degrada em foto ruim); sem write-back em ERP real;
categorização por heurística simples sem plano de contas do cliente; sem tratamento de
boleto parcelado/carnê.

**O que quebra em escala:**
- *Polling do Gmail* → migrar para Gmail API watch + Pub/Sub push (renovação a cada 7d).
- *Onboarding de cliente* → OAuth por caixa não escala. O que eu de fato mandaria para
  produção é um **endereço de encaminhamento** (`cliente@bills.…`), que funciona em
  qualquer provedor e elimina o consentimento por cliente.
- *Custo e latência* → escalonar modelos (Haiku na triagem, Opus só no que passa) e
  Batch API para backfill (50% do custo).
- *Deduplicação* → dedup por linha digitável, não por `message_id`: o mesmo boleto chega
  como original, lembrete e segunda via.
- *Multi-tenant* → `org_id` + RLS; documentos em bucket privado com signed URL;
  retenção LGPD.
- *Drift de prompt/modelo* → `prompt_version` já gravado em `processing_steps`, mais uma
  **golden set de regressão em CI**: queda de acurácia por campo bloqueia o deploy.

**Próximos passos:** aprender template por fornecedor a partir das correções humanas —
`review_actions` é o sinal de treino; após N extrações confirmadas do mesmo remetente e
layout, promover para parser determinístico e pular o LLM (custo cai e confiança sobe
com o uso). Depois: write-back Omie/Conta Azul, iniciação de pagamento Pix/CNAB, e
WhatsApp/portal do fornecedor como canais adicionais de entrada.

---

## Modo de trabalho (definido por você)

- **Passo 0:** `git init` em `/home/inteli/Documentos/case-bill`, `.gitignore`
  (`.env`, `credentials.json`, `token.json`, `fixtures/*.eml`, `__pycache__`,
  `node_modules`, `.next`).
- **`CLAUDE.md` na raiz do repo**, mantido vivo durante a construção: registro dos
  passos executados, decisões de arquitetura e o estado atual de cada etapa do pipeline.
- **Este plano vai versionado no repo** como `docs/plano.md`, no primeiro commit — serve
  de material de apoio para a call e mostra o raciocínio antes do código.
- **Regra de commit gravada no `CLAUDE.md`:** commits e push estão liberados sem pedir
  confirmação; **as mensagens de commit não levam `Co-Authored-By: Claude`** nem
  qualquer atribuição de IA (isso sobrescreve o padrão do harness).
- **Automode:** trabalho direto e ininterrupto, sem checkpoints de confirmação. Eu só
  te interrompo se algo bloquear de verdade — a criação do OAuth client no Google Cloud,
  a connection string do Supabase e a API key da Anthropic são os três pontos que
  dependem de você. Até lá o desenvolvimento roda em `fixtures/` + Postgres local.

## Arquivos críticos (ordem de construção)

1. `db/schema.sql` — o modelo de dados fecha as interfaces de todo o resto.
2. `apps/api/src/billpoc/validate/boleto.py` — o núcleo da tese. Construir **primeiro**,
   com testes, antes de qualquer LLM.
3. `apps/api/src/billpoc/extract/schemas.py` — Pydantic com `evidence` + `confidence`
   por campo monetário.
4. `apps/api/src/billpoc/ingest/{base,eml,gmail}.py` — `EmlSource` primeiro (destrava o
   desenvolvimento sem OAuth), `GmailSource` depois.
5. `pipeline.py` + `store/repositories.py`.
6. `apps/web/` — as 3 telas.
7. `README.md` + `docs/` — escritos por último, mas são metade da nota.

## Setup que depende de você (eu não insiro senhas em formulários)

1. **Google Cloud**: criar projeto → habilitar Gmail API → OAuth client "Desktop" →
   baixar `credentials.json`. Depois rodar `uv run billpoc auth`, que abre o navegador
   para você logar em `financeiro.test@gmail.com` e consentir. Eu te guio nos cliques.
2. **Supabase**: criar projeto, me passar a connection string.
3. **Anthropic**: criar API key em console.anthropic.com → `.env`.

Enquanto isso não existe, o desenvolvimento roda inteiro em `fixtures/` + Postgres local
via Docker (já instalado).

## Verificação

```bash
cd apps/api && uv run pytest -v          # validadores contra vetores de teste conhecidos
uv run billpoc auth                       # OAuth Gmail, uma vez
uv run billpoc ingest --limit 30          # baixa e salva os e-mails reais
uv run billpoc run --all                  # pipeline completo
uv run billpoc report                     # acurácia por campo + custo total em tokens
```

Depois: abrir o Supabase e conferir `payables` × `field_extractions` ×
`validation_results` para um boleto; subir `apps/web` e percorrer as três telas —
aprovar um item limpo, resolver um conflito na fila de revisão, e marcar um agendamento.

**Ensaio da demo:** o roteiro da call é (1) mostrar um boleto sendo processado ponta a
ponta, (2) abrir um item que caiu em revisão e mostrar o conflito com evidência, (3)
mexer no código de um validador junto com o entrevistador e rodar de novo.
