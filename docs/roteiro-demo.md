# Roteiro da demo

Um caminho de ~15 minutos que mostra a tese, prova que ela funciona em dados reais, e
deixa espaço para mexer no código junto. A ordem importa: a ideia central vem primeiro,
o código depois, e a UI por último.

---

## Antes de começar (5 min, sozinho)

```bash
cd /home/inteli/Documentos/case-bill
docker compose up -d
cd apps/api && uv run billpoc doctor          # tudo verde?
```

Deixe três terminais e duas abas prontos:

| | |
|---|---|
| Terminal 1 | `apps/api`, livre para os comandos |
| Terminal 2 | `uv run uvicorn billpoc.api:app --port 8000` |
| Terminal 3 | `cd apps/web && npm run dev` |

> Não rode `npm run build` com o `npm run dev` de pé — os dois compartilham `.next` e o
> dev server quebra com `Cannot find module './vendor-chunks/next.js'`. Se acontecer:
> `rm -rf .next` e reinicie o dev.
| Aba 1 | `localhost:3000` |
| Aba 2 | o repositório aberto no editor |

Se o banco estiver sujo de testes anteriores, uma rodada limpa:

```bash
docker exec -i billpoc-pg psql -U postgres -d billpoc -c \
  "truncate email_messages, vendors cascade;"
uv run billpoc run --fonte eml
```

---

## 1. A tese, antes de qualquer código (2 min)

> "Antes de mostrar rodando, a ideia central em uma frase: **num boleto brasileiro,
> valor e vencimento não precisam ser confiados ao LLM — eles estão aritmeticamente
> codificados na linha digitável.** Então dá para *conferir* em vez de *confiar*."

Mostre no terminal:

```bash
uv run python -c "
from billpoc.validate.boleto import decodificar
b = decodificar('34191790010104351004791020150008115700000123456')
print('valor     ', b.valor)
print('vencimento', b.vencimento)
print('válido    ', b.valido)
"
```

> "Isso é aritmética pura, sem modelo nenhum. O LLM continua fazendo o trabalho difícil
> — ler PDF de layout desconhecido, decidir se é cobrança ou ruído, categorizar. Mas nos
> dois campos onde errar custa dinheiro, existe um piso."

**Se perguntarem "e quando não tem código de barras?"** — a resposta está no item 4.

---

## 2. Rodando sobre a caixa real (3 min)

```bash
uv run billpoc run --fonte eml
```

Aponte para o resumo: **48 e-mails, 42 ruído, 6 cobranças, 0 erros, US$ 0,36**.

> "87% da caixa é ruído. Por isso a triagem roda em Haiku sobre cabeçalho e corpo, sem
> abrir PDF — e só o que passa vai para o Opus com o documento inteiro. É o que faz o
> custo por e-mail ficar de pé em escala."

Depois, a acurácia:

```bash
uv run billpoc golden
```

> "16 casos rotulados à mão. Os pisos são assimétricos de propósito: recall exige 100%,
> precisão aceita 90%. Um falso positivo o revisor descarta em dois minutos; um falso
> negativo some, a conta não é paga, e o cliente descobre pela multa."

---

## 3. O que a caixa real ensinou (2 min)

Este é o trecho que diferencia de uma POC com dados fabricados.

> "Três coisas que só apareceram porque rodei nos e-mails de verdade:"

1. **Todas as cobranças chegam encaminhadas** de uma mesma pessoa. O `From` é do
   encaminhador. Sem tratar isso, os seis boletos casariam com um "fornecedor"
   `gmail.com`.
2. **Dois dos seis PDFs são protegidos por senha.** Num deles a linha digitável estava no
   corpo, e a varredura determinística resolveu sem abrir o PDF.
3. **O mesmo provedor aparece com dois nomes** (Starfiber e Lord Fibra) — é por isso que
   o casamento de fornecedor é por CNPJ, não por nome.

---

## 4. A tela — e o momento que importa (4 min)

Abra `localhost:3000`.

**Caixa de entrada.** Três faixas. Mostre a **Ruído** e a justificativa de cada descarte.

> "O ruído fica visível de propósito, com o motivo e um botão para contestar. Descartar
> em silêncio é criar um falso negativo que ninguém descobre."

Abra uma conta em **Revisar** — de preferência a **Lord Fibra**.

Aponte os selos de origem ao lado de cada campo:

> "Esta é a informação mais importante da tela. 🔒 quer dizer que o número foi conferido
> por aritmética; 🤖 que foi lido pelo modelo. Sem essa distinção o revisor confere tudo
> com o mesmo cuidado, que é o mesmo que não conferir nada."

Repare que **valor** está 🔒 e **vencimento** está 🤖 nessa conta:

> "É um boleto de arrecadação. O formato codifica o valor mas não o vencimento — e o
> sistema *sabe* que não pode conferir a data. Por isso caiu em revisão mesmo com o valor
> confirmado. Essa é a resposta para 'e quando não tem como conferir': não quebra, escala
> de confiança."

**O caso do conflito.** Se quiser mostrar o cenário de divergência, use a caixa de
demonstração — ela tem um boleto onde o modelo lê R$ 987,00 e o código de barras diz
R$ 9.870,00:

```bash
uv run billpoc semear && uv run billpoc run --fonte demo --somente-cache
```

Abra a Norte Logística: os dois valores lado a lado, com o determinístico já gravado.

**O aprendizado.** Na caixa de demonstração há quatro mensalidades do mesmo fornecedor
(Limpeza Total). Abra a de setembro e mostre o campo **Recorrência**:

> "As três primeiras saíram como 'único' com selo 🤖 — o modelo lê um documento isolado e
> não tem como saber. A quarta virou 'recorrente' com selo 🔒 e a evidência 'três
> cobranças anteriores em cadência mensal'. O sistema fica melhor com o uso, e não por
> treinar nada: o histórico é determinístico."

**Agenda.** Mostre o agrupamento por vencimento e o botão **Exportar → CNAB 240**.

> "Copiar-e-colar resolve três contas. Trinta é o volume de um cliente pequeno de
> verdade, e aí o caminho é subir um arquivo de remessa no banco."

---

## 5. Mexer no código junto (o resto do tempo)

O entrevistador disse que quer mexer no código junto. Três lugares bons, do mais simples
ao mais interessante:

**a) Um limiar da política** — `apps/api/src/billpoc/validate/rules.py`, topo do arquivo:

```python
LIMIAR_TRIAGEM = 0.85
LIMIAR_CAMPO = 0.70
```

Baixar `LIMIAR_CAMPO` para 0.4 e rodar de novo mostra contas saindo da revisão. É uma
conversa boa sobre onde calibrar.

**b) O prompt** — `apps/api/src/billpoc/extract/prompts.py`. Mexer nele muda o
`PROMPT_VERSION`, o cache é invalidado, e `billpoc golden` mede se melhorou ou piorou.
É a demonstração do ciclo de iteração.

**c) A tolerância do alerta de valor** — `apps/api/src/billpoc/enrich.py`:

```python
MINIMO_PARA_RECORRENCIA = 3
TOLERANCIA_PADRAO = Decimal("15.0")
```

Baixar a tolerância para 2% faz aparecer alerta em variação normal de conta de consumo —
boa conversa sobre onde fica o limite entre sinal e ruído. Ou uma **regra nova** em
`rules.py`, função `_politica`: o padrão de `Verificacao` já está montado, é só
acrescentar.

---

## Perguntas prováveis, e onde está a resposta

| Pergunta | Resposta curta |
|---|---|
| "Por que não usou IMAP?" | Testei; o Google recusa senha de conta desde 2022. OAuth é também o caminho de produção. |
| "Isso escala para 100 clientes?" | OAuth por caixa não escala. Endereço de encaminhamento por cliente elimina o consentimento e funciona em qualquer provedor. `MailSource` já é a interface. |
| "Quanto custa?" | US$ 0,36 para 48 e-mails. `billpoc report` quebra por etapa e modelo. |
| "E se o modelo alucinar?" | Nos campos com código de barras, é detectado. Nos outros, cai em revisão por falta de corroboração. Nada paga sozinho. |
| "Por que não um agente?" | Extrair campos é uma chamada com schema estrito, não um loop. Agente aqui adiciona não-determinismo sem adicionar capacidade. |
| "Como você sabe que uma mudança melhorou?" | `billpoc golden`. Sem isso é opinião. |
| "E prompt injection?" | O prompt trata documento como dado, e a política de decisão está em código, não no prompt. Um PDF não consegue se auto-aprovar. |

---

## Se algo der errado ao vivo

- **API não responde** → `uv run billpoc doctor` mostra o que caiu.
- **Sem chave da Anthropic / sem rede** → `uv run billpoc run --fonte demo
  --somente-cache` usa as respostas já gravadas. A demo inteira funciona offline.
- **Banco sujo** → o `truncate` do começo deste arquivo.
- **Quer resetar tudo** → `docker compose down -v && docker compose up -d && uv run
  billpoc initdb && uv run billpoc semear`.
