# Deploy — Vercel + Supabase

Arquitetura publicada:

```
  Vercel (um projeto, dois runtimes)
  ├── apps/web        Next.js — as três telas
  └── api/index.py    FastAPI como função serverless Python
                          │
                          ▼
                    Supabase Postgres
```

O `vercel.json` roteia `/api/*` para a função Python e o resto para o Next.js. Front e
API ficam no mesmo domínio, então não há CORS nem URL de backend espalhada pelo código.

---

## Por que estas escolhas

**Vercel em vez de container.** O plano gratuito de hosts de container dorme após alguns
minutos de inatividade e leva ~50s para acordar. Para um link que alguém vai abrir sem
avisar, isso é a diferença entre uma demo e uma tela em branco. Serverless tem cold start
de ~1s.

**Postgres em vez de disco para os anexos.** Função serverless não tem disco persistente.
Se o PDF vivesse em disco, a tela de revisão perderia o documento no primeiro restart — e
a tela inteira existe para o revisor poder olhar o documento. São ~1,2 MB no total.

**Sincronização incremental.** A função tem 60 segundos; processar a caixa leva minutos.
`POST /api/sync` processa um lote pequeno e devolve quantos faltam; a UI chama em laço.
Como cada e-mail é uma transação e a ingestão é idempotente por `gmail_message_id`,
interromper no meio não corrompe nada.

---

## 1. Supabase

1. **supabase.com** → *New project* → nome `bill-poc` → senha forte (anote) → região
   `South America (São Paulo)`
2. Espere provisionar (~2 min)
3. **SQL Editor** → cole `db/schema.sql` → **Run** → repita com `db/seed.sql`
4. **Project Settings → Database → Connection string → URI** e guarde

> Use a string do **Connection pooling** (porta `6543`) e não a direta (`5432`). Cada
> invocação da função abre uma conexão própria; sem pooler, uma sincronização em laço
> esgota o limite de conexões do Postgres em poucos minutos.

---

## 2. GitHub

```bash
cd /home/inteli/Documentos/case-bill
git remote add origin git@github.com:SEU-USUARIO/case-bill.git
git push -u origin main
```

`.env`, `credentials.json`, `token.json` e os `.eml` estão no `.gitignore` — nenhum
segredo nem e-mail de terceiros vai para o repositório.

---

## 3. Vercel

1. **vercel.com** → login com GitHub → **Add New → Project** → importe `case-bill`
2. **Root Directory: deixe a raiz** (não aponte para `apps/web` — o `vercel.json` na raiz
   é que declara os dois runtimes)
3. Em **Environment Variables**, adicione:

| Variável | Valor |
|---|---|
| `DATABASE_URL` | a URI do pooler do Supabase (porta 6543) |
| `ANTHROPIC_API_KEY` | `sk-ant-...` |
| `GMAIL_TOKEN_JSON` | o conteúdo **inteiro** de `token.json`, numa linha |
| `SYNC_JANELA` | `60` |

4. **Deploy**

Para o `GMAIL_TOKEN_JSON`:

```bash
cat token.json | tr -d '\n'
```

---

## 4. Carregar os dados

Duas opções, e as duas funcionam:

**Pelo site** — abra o deploy e clique em **Buscar novos e-mails**. Processa um e-mail por
chamada mostrando progresso. É o caminho que demonstra o produto.

**Pela sua máquina** — apontando para o Supabase:

```bash
cd apps/api
DATABASE_URL="<a URI do Supabase>" uv run billpoc run --fonte eml
```

Mais rápido para carregar os 48 de uma vez antes da apresentação.

---

## Verificação

```bash
curl https://SEU-PROJETO.vercel.app/api/health
```

Deve responder `{"ok":true,...}` com `llm` e `gmail` em `true`.

---

## Se o deploy falhar

| Sintoma | Causa provável |
|---|---|
| `ModuleNotFoundError: billpoc` | `includeFiles` no `vercel.json` não pegou `apps/api/src`. Confira o caminho. |
| `A Serverless Function has exceeded the unzipped maximum size` | Alguma dependência voltou ao `api/requirements.txt`. O pacote está em ~59MB; o limite é 250MB. |
| `FUNCTION_INVOCATION_TIMEOUT` no sync | Um e-mail específico está demorando >60s. Reduza `SYNC_JANELA` ou pule aquele e-mail. |
| `too many connections` | Está usando a string direta (5432) em vez do pooler (6543). |
| Build do Next.js falha | Rode `cd apps/web && npm run build` local para ver o erro real. |

O log completo fica em **Vercel → o deploy → Building / Functions**.
