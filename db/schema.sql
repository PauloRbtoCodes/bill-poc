-- =====================================================================================
-- POC Contas a Pagar — schema
--
-- Dois domínios com propósitos diferentes e regras diferentes:
--
--   ERP        tabelas mutáveis que respondem "o que eu tenho a pagar?".
--              Equivalente ao que um Conta Azul/Omie guarda.
--
--   AUDITORIA  tabelas append-only que respondem "por que o sistema acha isso?".
--              Nunca se faz UPDATE aqui. Toda mudança em um payable gera uma linha
--              nova em review_actions, então o histórico completo é reconstruível.
--
-- A separação existe porque as duas perguntas têm ciclos de vida distintos: o payable
-- vira "pago" e some da tela, mas a trilha de como aquele valor foi parar ali precisa
-- sobreviver — é ela que responde a uma auditoria ou a um pagamento errado.
--
-- org_id em tudo desde o dia 1: multi-tenant é caro de retrofitar.
-- =====================================================================================

create extension if not exists "pgcrypto";

-- =====================================================================================
-- Tenancy
-- =====================================================================================

create table orgs (
    id          uuid primary key default gen_random_uuid(),
    nome        text not null,
    criado_em   timestamptz not null default now()
);

create table usuarios (
    id          uuid primary key default gen_random_uuid(),
    org_id      uuid not null references orgs(id) on delete cascade,
    email       text not null,
    nome        text not null,
    papel       text not null default 'finance_partner'
                check (papel in ('finance_partner', 'admin', 'sistema')),
    criado_em   timestamptz not null default now(),
    unique (org_id, email)
);


-- =====================================================================================
-- AUDITORIA — o que chegou e o que o sistema fez com isso
-- =====================================================================================

-- Um e-mail capturado. gmail_message_id é a chave de idempotência da ingestão:
-- reprocessar a caixa inteira não duplica nada.
create table email_messages (
    id                  uuid primary key default gen_random_uuid(),
    org_id              uuid not null references orgs(id) on delete cascade,
    mailbox             text not null,
    gmail_message_id    text not null,
    thread_id           text,
    remetente           text not null,
    remetente_nome      text,
    destinatarios       text[] not null default '{}',
    assunto             text,
    recebido_em         timestamptz not null,
    headers             jsonb not null default '{}',
    corpo_texto         text,
    corpo_html          text,
    -- hash do RFC822 inteiro: detecta reenvio idêntico mesmo com message_id diferente
    content_hash        text not null,
    storage_uri         text,
    ingerido_em         timestamptz not null default now(),
    unique (org_id, gmail_message_id)
);

create index on email_messages (org_id, recebido_em desc);
create index on email_messages (org_id, content_hash);

-- Anexos. sha256 é a chave de dedup: o mesmo boleto anexado em três e-mails
-- (original, lembrete, segunda via) é um documento só.
create table documents (
    id                  uuid primary key default gen_random_uuid(),
    org_id              uuid not null references orgs(id) on delete cascade,
    email_message_id    uuid references email_messages(id) on delete cascade,
    nome_arquivo        text not null,
    mime_type           text not null,
    tamanho_bytes       bigint not null,
    sha256              text not null,
    -- classificação do anexo, decidida na triagem
    tipo                text not null default 'desconhecido'
                        check (tipo in ('boleto_pdf', 'nfe_xml', 'danfe_pdf',
                                        'fatura_pdf', 'imagem', 'recibo', 'desconhecido')),
    paginas             int,
    -- O conteúdo do anexo vive no banco, não em disco. Num deploy serverless ou em
    -- container o disco é efêmero, e o revisor precisa ver o PDF ao lado dos campos —
    -- perder o arquivo no primeiro restart tornaria a tela de revisão inútil.
    -- São poucos KB por boleto; em produção isso vira bucket privado com URL assinada,
    -- e a coluna `storage_uri` passa a apontar para lá.
    conteudo            bytea,
    storage_uri         text,
    criado_em           timestamptz not null default now(),
    unique (org_id, sha256)
);

create index on documents (email_message_id);

-- Uma execução do pipeline sobre um e-mail. Reprocessar gera um run novo — os runs
-- antigos ficam, então dá para comparar o resultado de duas versões do prompt.
create table processing_runs (
    id                  uuid primary key default gen_random_uuid(),
    org_id              uuid not null references orgs(id) on delete cascade,
    email_message_id    uuid not null references email_messages(id) on delete cascade,
    pipeline_version    text not null,
    status              text not null default 'em_andamento'
                        check (status in ('em_andamento', 'concluido', 'erro')),
    erro                text,
    iniciado_em         timestamptz not null default now(),
    finalizado_em       timestamptz
);

create index on processing_runs (org_id, email_message_id, iniciado_em desc);

-- Cada etapa do pipeline, com custo e latência. É daqui que sai a resposta para
-- "quanto custa processar um e-mail" e "qual versão de prompt gerou este resultado".
create table processing_steps (
    id                  uuid primary key default gen_random_uuid(),
    run_id              uuid not null references processing_runs(id) on delete cascade,
    etapa               text not null
                        check (etapa in ('ingest', 'triage', 'extract', 'validate',
                                         'enrich', 'persist')),
    document_id         uuid references documents(id) on delete set null,
    modelo              text,
    prompt_version      text,
    input_tokens        int,
    output_tokens       int,
    custo_centavos      numeric(12, 4),
    latencia_ms         int,
    request_id          text,
    status              text not null default 'ok' check (status in ('ok', 'erro')),
    erro                text,
    raw_response        jsonb,
    criado_em           timestamptz not null default now()
);

create index on processing_steps (run_id, criado_em);

-- Resultado da triagem: é conta a pagar ou é ruído? O ruído também é gravado, com o
-- motivo — sem isso não dá para medir falso negativo, que é o erro caro aqui
-- (uma conta perdida vira multa).
create table classifications (
    id                  uuid primary key default gen_random_uuid(),
    run_id              uuid not null references processing_runs(id) on delete cascade,
    email_message_id    uuid not null references email_messages(id) on delete cascade,
    e_conta_a_pagar     boolean not null,
    confianca           numeric(4, 3) not null check (confianca between 0 and 1),
    tipo_documento      text,
    justificativa       text not null,
    -- preenchido quando um humano discorda da máquina; é o rótulo de verdade
    corrigido_por       uuid references usuarios(id),
    corrigido_para      boolean,
    corrigido_em        timestamptz,
    criado_em           timestamptz not null default now()
);

create index on classifications (run_id);


-- =====================================================================================
-- ERP — o que se tem a pagar
-- =====================================================================================

create table expense_categories (
    id          uuid primary key default gen_random_uuid(),
    org_id      uuid not null references orgs(id) on delete cascade,
    codigo      text not null,
    nome        text not null,
    parent_id   uuid references expense_categories(id) on delete set null,
    unique (org_id, codigo)
);

create table vendors (
    id                      uuid primary key default gen_random_uuid(),
    org_id                  uuid not null references orgs(id) on delete cascade,
    -- alfanumérico a partir de jul/2026, por isso text e não numérico
    cnpj                    text,
    razao_social            text not null,
    nome_fantasia           text,
    categoria_padrao_id     uuid references expense_categories(id) on delete set null,
    -- domínios de e-mail conhecidos do fornecedor: sinal forte na triagem
    dominios_email          text[] not null default '{}',
    criado_em               timestamptz not null default now(),
    atualizado_em           timestamptz not null default now(),
    unique (org_id, cnpj)
);

-- Agrupa cobranças recorrentes do mesmo fornecedor (aluguel, SaaS, energia).
-- Serve para dois fins: marcar recurrence='recorrente' e alertar quando o valor
-- do mês foge do esperado.
create table recurrence_groups (
    id                      uuid primary key default gen_random_uuid(),
    org_id                  uuid not null references orgs(id) on delete cascade,
    vendor_id               uuid not null references vendors(id) on delete cascade,
    descricao               text not null,
    cadencia                text not null default 'mensal'
                            check (cadencia in ('mensal', 'bimestral', 'trimestral',
                                                'semestral', 'anual')),
    valor_esperado_centavos bigint,
    -- variação aceita antes de levantar alerta de valor fora do padrão
    tolerancia_percentual   numeric(5, 2) not null default 10.0,
    dia_vencimento          int check (dia_vencimento between 1 and 31),
    ativo                   boolean not null default true,
    criado_em               timestamptz not null default now()
);

create index on recurrence_groups (org_id, vendor_id);

-- O registro central de contas a pagar.
create table payables (
    id                      uuid primary key default gen_random_uuid(),
    org_id                  uuid not null references orgs(id) on delete cascade,
    vendor_id               uuid references vendors(id) on delete set null,

    tipo_documento          text not null default 'boleto'
                            check (tipo_documento in ('boleto', 'nota_fiscal', 'fatura',
                                                      'recibo', 'outro')),
    numero_documento        text,          -- nº da NF
    chave_nfe               text,
    descricao               text,
    -- O nome do beneficiário como apareceu no documento. Fica no payable, e não só no
    -- vendor, porque nem toda cobrança traz CNPJ — e sem CNPJ não se cria fornecedor
    -- (casar por nome erraria). O payable registra o que o documento disse; o vendor é
    -- a entidade conciliada. São coisas diferentes e ambas precisam existir.
    beneficiario_nome       text,

    valor_centavos          bigint not null check (valor_centavos >= 0),
    moeda                   char(3) not null default 'BRL',
    data_emissao            date,
    data_vencimento         date,
    data_competencia        date,

    categoria_id            uuid references expense_categories(id) on delete set null,
    recorrencia             text not null default 'unico'
                            check (recorrencia in ('unico', 'recorrente')),
    recurrence_group_id     uuid references recurrence_groups(id) on delete set null,

    -- Fluxo do Finance Partner. Nada pula direto para 'aprovado': todo payable passa
    -- por um humano, mesmo quando todos os checks fecham.
    status                  text not null default 'em_revisao'
                            check (status in ('em_revisao', 'aprovado', 'agendado',
                                              'pago', 'rejeitado', 'duplicado')),
    -- Resultado da política de decisão: 'auto_ok' significa "faixa rápida", não "pago".
    faixa                   text not null default 'revisar'
                            check (faixa in ('auto_ok', 'revisar')),
    confianca_geral         numeric(4, 3) check (confianca_geral between 0 and 1),

    email_message_id        uuid references email_messages(id) on delete set null,
    document_id             uuid references documents(id) on delete set null,
    run_id                  uuid references processing_runs(id) on delete set null,

    -- Apontamento para o payable original quando este é detectado como reenvio.
    duplicado_de_id         uuid references payables(id) on delete set null,

    criado_em               timestamptz not null default now(),
    atualizado_em           timestamptz not null default now()
);

create index on payables (org_id, status, data_vencimento);
create index on payables (org_id, vendor_id, data_vencimento);
create index on payables (org_id, faixa) where status = 'em_revisao';

-- Como pagar. Um payable pode oferecer mais de uma forma (boleto e Pix no mesmo PDF).
create table payment_instruments (
    id                  uuid primary key default gen_random_uuid(),
    org_id              uuid not null references orgs(id) on delete cascade,
    payable_id          uuid not null references payables(id) on delete cascade,
    tipo                text not null
                        check (tipo in ('boleto_bancario', 'boleto_arrecadacao',
                                        'pix', 'ted', 'debito_automatico')),
    linha_digitavel     text,
    codigo_barras       text,
    pix_copia_e_cola    text,
    dados_bancarios     jsonb,
    -- O que a aritmética extraiu do próprio instrumento: fator de vencimento, valor,
    -- banco, resultado de cada DV. É o que a UI mostra ao lado do que o LLM leu.
    decodificado        jsonb not null default '{}',
    preferencial        boolean not null default false,
    criado_em           timestamptz not null default now()
);

-- Dedup de boleto reenviado: a mesma linha digitável nunca vira duas contas.
create unique index on payment_instruments (org_id, linha_digitavel)
    where linha_digitavel is not null;
create index on payment_instruments (payable_id);

-- Agendamento bancário. A POC não paga nada: o Finance Partner agenda no banco e
-- registra aqui que agendou. Esta tabela é a ponte entre o sistema e o mundo real.
create table payment_schedules (
    id                      uuid primary key default gen_random_uuid(),
    org_id                  uuid not null references orgs(id) on delete cascade,
    payable_id              uuid not null references payables(id) on delete cascade,
    payment_instrument_id   uuid references payment_instruments(id) on delete set null,
    data_agendada           date not null,
    banco                   text,
    agendado_por            uuid references usuarios(id),
    codigo_confirmacao      text,          -- o protocolo que o banco devolve
    pago_em                 timestamptz,
    comprovante_document_id uuid references documents(id) on delete set null,
    status                  text not null default 'agendado'
                            check (status in ('agendado', 'pago', 'falhou', 'cancelado')),
    observacao              text,
    criado_em               timestamptz not null default now()
);

create index on payment_schedules (org_id, data_agendada, status);


-- =====================================================================================
-- AUDITORIA — a espinha dorsal: proveniência campo a campo
-- =====================================================================================

-- Uma linha por campo extraído. Responde, para qualquer valor na tela:
-- de onde veio, com que confiança, e qual trecho do documento sustenta isso.
--
-- Append-only. Correção humana não faz UPDATE: insere uma linha nova com
-- origem='humano', e a mais recente vence.
create table field_extractions (
    id                  uuid primary key default gen_random_uuid(),
    org_id              uuid not null references orgs(id) on delete cascade,
    run_id              uuid not null references processing_runs(id) on delete cascade,
    payable_id          uuid references payables(id) on delete cascade,
    document_id         uuid references documents(id) on delete set null,

    campo               text not null,     -- 'valor', 'data_vencimento', 'cnpj', ...
    valor_texto         text,              -- como apareceu no documento
    valor_normalizado   text,              -- já convertido para o tipo do banco

    -- A distinção que sustenta a tese da POC. 'codigo_barras', 'nfe_xml' e 'chave_nfe'
    -- são aritmética: confiança 1.0 por construção. 'llm' é leitura: precisa de
    -- corroboração antes de ser tratada como certa.
    origem              text not null
                        check (origem in ('codigo_barras', 'nfe_xml', 'chave_nfe',
                                          'pix', 'regex', 'llm', 'humano', 'historico')),
    confianca           numeric(4, 3) not null check (confianca between 0 and 1),

    -- Grounding: o trecho verbatim que o modelo alega ter lido. Sem isso, "confiança
    -- 0.9" é um número sem lastro; com isso, o revisor confere em dois segundos.
    evidencia           text,
    evidencia_pagina    int,

    -- true na linha que está valendo agora para este (payable, campo)
    vigente             boolean not null default true,
    criado_em           timestamptz not null default now()
);

create index on field_extractions (payable_id, campo, criado_em desc);
create index on field_extractions (run_id);
create unique index on field_extractions (payable_id, campo)
    where vigente and payable_id is not null;

-- Cada verificação executada, com o que se esperava e o que se achou.
-- severidade='bloqueante' é o que impede a faixa rápida.
create table validation_results (
    id                  uuid primary key default gen_random_uuid(),
    org_id              uuid not null references orgs(id) on delete cascade,
    run_id              uuid not null references processing_runs(id) on delete cascade,
    payable_id          uuid references payables(id) on delete cascade,
    check_nome          text not null,     -- 'dv_geral', 'valor_confere', ...
    passou              boolean not null,
    severidade          text not null default 'bloqueante'
                        check (severidade in ('bloqueante', 'alerta', 'info')),
    esperado            text,
    encontrado          text,
    mensagem            text,
    criado_em           timestamptz not null default now()
);

create index on validation_results (payable_id, criado_em desc);
create index on validation_results (run_id) where not passou;

-- Trilha de intervenção humana. Além da auditoria, é o sinal de treino do roadmap:
-- N correções do mesmo remetente no mesmo campo indicam que aquele layout merece um
-- parser determinístico e pode sair do caminho do LLM.
create table review_actions (
    id                  uuid primary key default gen_random_uuid(),
    org_id              uuid not null references orgs(id) on delete cascade,
    payable_id          uuid references payables(id) on delete cascade,
    email_message_id    uuid references email_messages(id) on delete set null,
    ator_id             uuid references usuarios(id),
    acao                text not null
                        check (acao in ('aprovar', 'editar_campo', 'rejeitar',
                                        'marcar_duplicado', 'reabrir',
                                        'reclassificar', 'agendar', 'marcar_pago')),
    campo               text,
    valor_anterior      text,
    valor_novo          text,
    observacao          text,
    criado_em           timestamptz not null default now()
);

create index on review_actions (payable_id, criado_em desc);
create index on review_actions (org_id, criado_em desc);


-- =====================================================================================
-- Views de apoio à UI
-- =====================================================================================

-- A fila do Finance Partner: tudo que espera decisão, com o que falhou e quão urgente é.
create view fila_revisao as
select
    p.id,
    p.org_id,
    p.status,
    p.faixa,
    p.confianca_geral,
    coalesce(v.razao_social, p.beneficiario_nome)   as fornecedor,
    v.cnpj,
    p.valor_centavos,
    p.data_vencimento,
    p.numero_documento,
    p.recorrencia,
    em.assunto                                      as email_assunto,
    em.remetente                                    as email_remetente,
    em.recebido_em,
    (select count(*) from validation_results vr
      where vr.payable_id = p.id and not vr.passou
        and vr.severidade = 'bloqueante')           as falhas_bloqueantes,
    (select count(*) from validation_results vr
      where vr.payable_id = p.id and not vr.passou
        and vr.severidade = 'alerta')               as alertas,
    -- Vencimento apertado com item ainda em revisão é o caso que gera multa.
    (p.data_vencimento is not null
     and p.data_vencimento <= current_date + 2)     as urgente
from payables p
left join vendors v         on v.id = p.vendor_id
left join email_messages em on em.id = p.email_message_id
where p.status = 'em_revisao';

-- A agenda de pagamento: aprovado e ainda não agendado, com como pagar já junto.
create view agenda_pagamento as
select
    p.id,
    p.org_id,
    coalesce(v.razao_social, p.beneficiario_nome) as fornecedor,
    v.cnpj,
    p.valor_centavos,
    p.data_vencimento,
    p.numero_documento,
    pi.tipo                         as forma_pagamento,
    pi.linha_digitavel,
    pi.pix_copia_e_cola,
    p.data_vencimento - current_date as dias_para_vencer
from payables p
left join vendors v on v.id = p.vendor_id
left join lateral (
    select * from payment_instruments x
    where x.payable_id = p.id
    order by x.preferencial desc, x.criado_em
    limit 1
) pi on true
where p.status = 'aprovado';
