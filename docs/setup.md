# Setup

Três credenciais. As duas primeiras exigem login em conta, então precisam ser feitas por
uma pessoa — nenhum agente digita senha em formulário.

O projeto roda **sem nenhuma delas** em modo demo (`--somente-cache` + fixtures), então
nada aqui bloqueia o desenvolvimento. Elas são necessárias para capturar a caixa real e
para popular o cache na primeira vez.

```bash
cp .env.example .env
```

---

## 1. Anthropic API key — 2 minutos

Necessária para a primeira execução do pipeline (depois o cache cobre as reexecuções).

1. Acesse **console.anthropic.com**
2. **Settings → API keys → Create Key**
3. Copie a chave (`sk-ant-...`) — ela só aparece uma vez
4. Cole em `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
```

**Custo estimado desta POC:** alguns centavos de dólar. A triagem roda em Haiku 4.5
(US$ 1 / US$ 5 por milhão de tokens) sobre cabeçalho e corpo; a extração roda em Opus 5
(US$ 5 / US$ 25) só nos e-mails aprovados na triagem, e um boleto em PDF gasta na ordem
de 2–4 mil tokens de entrada. Para uma caixa de ~30 e-mails, o total fica bem abaixo de
US$ 1. O comando `billpoc report` mostra o custo real acumulado por etapa.

> Verificação: `uv run billpoc doctor` diz se a chave foi lida.

---

## 2. Gmail via OAuth — 8 minutos

A senha da caixa **não funciona** via IMAP: o Google desativou login com senha de conta
em aplicativos externos em 2022 (testado, retorna `[AUTHENTICATIONFAILED] Invalid
credentials`). O caminho é OAuth, que também é o que se usaria em produção.

### 2.1 Criar o projeto e habilitar a API

1. **console.cloud.google.com** — logado em qualquer conta Google (não precisa ser a da
   caixa de teste)
2. Topo da tela → seletor de projeto → **Novo projeto** → nome `bill-poc` → **Criar**
3. Menu → **APIs e serviços → Biblioteca** → buscar **Gmail API** → **Ativar**

### 2.2 Configurar a tela de consentimento

4. **APIs e serviços → Tela de permissão OAuth**
5. Tipo de usuário: **Externo** → **Criar**
6. Preencher só o obrigatório: nome do app (`bill-poc`), e-mail de suporte, e-mail do
   desenvolvedor → **Salvar e continuar**
7. Escopos: pode pular → **Salvar e continuar**
8. **Usuários de teste → Adicionar usuários** → `financeiro.test@gmail.com`
   → **Salvar e continuar**

> Este passo é o que costuma travar. Sem a caixa listada como usuário de teste, o
> consentimento é recusado com "app não verificado".

### 2.3 Criar as credenciais

9. **APIs e serviços → Credenciais → Criar credenciais → ID do cliente OAuth**
10. Tipo de aplicativo: **App para computador** → nome qualquer → **Criar**
11. **Fazer download do JSON** → salvar na raiz do repositório como `credentials.json`

### 2.4 Autorizar

```bash
cd apps/api && uv run billpoc auth
```

Abre o navegador. Logar em `financeiro.test@gmail.com` (senha `Teste2026!`), aceitar o
aviso de app não verificado em **Avançado → Acessar bill-poc**, e conceder o acesso de
**leitura** ao Gmail.

Gera `token.json` na raiz. `credentials.json` e `token.json` estão no `.gitignore`.

> O escopo pedido é `gmail.readonly` — o pipeline nunca apaga, marca ou responde nada.

---

## 3. Banco — 1 minuto

### Opção A: Postgres local (padrão, não precisa de conta)

```bash
docker compose up -d
psql "postgresql://postgres:billpoc@localhost:55432/billpoc" -f db/schema.sql -f db/seed.sql
```

### Opção B: Supabase

1. **supabase.com** → novo projeto
2. **SQL Editor** → colar o conteúdo de `db/schema.sql` → **Run** → repetir com
   `db/seed.sql`
3. **Project Settings → Database → Connection string → URI**, e colar em `.env`:

```
DATABASE_URL=postgresql://postgres.[ref]:[senha]@aws-0-....pooler.supabase.com:6543/postgres
```

O mesmo schema aplica nos dois. A vantagem do Supabase na demo é o painel de tabelas
pronto para mostrar os dados gravados.

---

## Verificação

```bash
cd apps/api && uv run billpoc doctor
```

Mostra o que está configurado e o que falta, sem revelar valor de credencial nenhuma.

---

## Rodando sem nenhuma credencial

O modo demo usa os `.eml` já capturados em `fixtures/` e as respostas de LLM já gravadas
em `.cache/llm/`:

```bash
uv run billpoc run --fonte eml --somente-cache
```

É como a demo da call roda: sem depender de rede, de token válido ou de saldo na API.
