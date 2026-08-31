-- Dados mínimos para a POC rodar: uma org, o Finance Partner e um plano de contas.
-- Idempotente: pode rodar quantas vezes quiser.

insert into orgs (id, nome)
values ('00000000-0000-0000-0000-000000000001', 'Cliente Demo Ltda')
on conflict (id) do nothing;

insert into usuarios (id, org_id, email, nome, papel)
values
    ('00000000-0000-0000-0000-0000000000f1',
     '00000000-0000-0000-0000-000000000001',
     'finance.partner@bill.com.br', 'Finance Partner', 'finance_partner'),
    ('00000000-0000-0000-0000-0000000000f0',
     '00000000-0000-0000-0000-000000000001',
     'pipeline@bill.com.br', 'Pipeline automático', 'sistema')
on conflict (org_id, email) do nothing;

-- Plano de contas enxuto, no vocabulário de quem opera financeiro de PME.
-- A categorização do LLM é restrita a estes códigos — modelo não inventa categoria.
insert into expense_categories (org_id, codigo, nome) values
    ('00000000-0000-0000-0000-000000000001', 'ALUGUEL',       'Aluguel e condomínio'),
    ('00000000-0000-0000-0000-000000000001', 'UTILIDADES',    'Energia, água, gás e telefonia'),
    ('00000000-0000-0000-0000-000000000001', 'SOFTWARE',      'Software e assinaturas'),
    ('00000000-0000-0000-0000-000000000001', 'SERVICOS_PJ',   'Serviços prestados por PJ'),
    ('00000000-0000-0000-0000-000000000001', 'FORNECEDORES',  'Fornecedores e insumos'),
    ('00000000-0000-0000-0000-000000000001', 'IMPOSTOS',      'Impostos e tributos'),
    ('00000000-0000-0000-0000-000000000001', 'FOLHA',         'Folha, pró-labore e benefícios'),
    ('00000000-0000-0000-0000-000000000001', 'MARKETING',     'Marketing e publicidade'),
    ('00000000-0000-0000-0000-000000000001', 'VIAGENS',       'Viagens e deslocamento'),
    ('00000000-0000-0000-0000-000000000001', 'FINANCEIRO',    'Tarifas bancárias e juros'),
    ('00000000-0000-0000-0000-000000000001', 'OUTROS',        'Outros')
on conflict (org_id, codigo) do nothing;
