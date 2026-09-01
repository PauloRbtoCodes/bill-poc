"""Teste ponta a ponta do pipeline contra um Postgres real.

Usa um extrator falso no lugar do Claude. Não é para economizar chamada de API: é porque
o que está sendo testado aqui é a **orquestração** — idempotência, transação, trilha de
auditoria, detecção de duplicata — e essas coisas precisam de um resultado de extração
previsível para serem verificáveis. A qualidade da extração em si é outra medida, que sai
do `billpoc report` sobre a caixa real.

Pula automaticamente se não houver banco:

    docker compose up -d && uv run billpoc initdb
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from billpoc.config import ORG_DEMO, Config
from billpoc.extract.claude import Uso
from billpoc.extract.schemas import DocumentoExtraido, Triagem
from billpoc.ingest.base import parse_rfc822
from billpoc.pipeline import Pipeline
from billpoc.store.db import BancoIndisponivel, conectar, schema_aplicado
from billpoc.store.repositories import Repositorio

from .test_boleto import montar_boleto_bancario
from .test_ingest import montar_email
from .test_rules import extraido as montar_extraido
from .test_rules import triagem as montar_triagem

URL = "postgresql://postgres:billpoc@localhost:55432/billpoc"
HOJE = date(2026, 8, 31)
VENCIMENTO = date(2026, 9, 15)
VALOR = Decimal("1234.56")


# ------------------------------------------------------------------------------------
# Infra do teste
# ------------------------------------------------------------------------------------


@pytest.fixture
def conexao():
    try:
        with conectar(URL) as conn:
            if not schema_aplicado(conn):
                pytest.skip("schema não aplicado — rode `uv run billpoc initdb`")
            yield conn
            conn.rollback()  # cada teste sai sem deixar rastro
    except BancoIndisponivel:
        pytest.skip("Postgres indisponível — rode `docker compose up -d`")


@pytest.fixture
def org(conexao):
    """Uma org nova por teste.

    Isolamento de verdade em vez de "espero que o banco esteja vazio": os testes rodam
    no mesmo Postgres que a caixa de demonstração, e uma suíte que só passa com o banco
    limpo é uma suíte que vai falhar na hora errada. Como `org_id` já está em todas as
    tabelas por causa do multi-tenant, sai de graça.
    """
    with conexao.cursor() as cur:
        cur.execute("insert into orgs (nome) values ('teste') returning id")
        org_id = str(cur.fetchone()["id"])
        # O Finance Partner e as categorias que o pipeline espera encontrar.
        cur.execute(
            "insert into usuarios (id, org_id, email, nome) values "
            "('00000000-0000-0000-0000-0000000000f1', %s, 'fp@teste', 'FP') "
            "on conflict do nothing",
            (org_id,),
        )
        cur.execute(
            """
            insert into expense_categories (org_id, codigo, nome)
            select %s, codigo, nome from expense_categories where org_id = %s
            """,
            (org_id, ORG_DEMO),
        )
    return org_id


@pytest.fixture
def repo(conexao, org):
    return Repositorio(conexao, org)


@pytest.fixture
def conta(conexao, org):
    """Conta linhas de uma tabela dentro da org do teste."""

    def _contar(tabela: str, coluna: str = "org_id") -> int:
        with conexao.cursor() as cur:
            cur.execute(f"select count(*) as n from {tabela} where {coluna} = %s", (org,))
            return cur.fetchone()["n"]

    return _contar


class ExtratorFalso:
    """Devolve resultados combinados de antemão, e conta quantas vezes foi chamado."""

    def __init__(self, triagem: Triagem, documento: DocumentoExtraido | None = None):
        self._triagem = triagem
        self._documento = documento
        self.chamadas_triagem = 0
        self.chamadas_extracao = 0

    def _uso(self, modelo: str) -> Uso:
        return Uso.calcular(modelo, 1000, 200, 500)

    def triar(self, email):
        self.chamadas_triagem += 1
        return self._triagem, self._uso("claude-haiku-4-5")

    def extrair(self, email, anexo=None):
        self.chamadas_extracao += 1
        assert self._documento is not None, "extração não deveria ter sido chamada"
        return self._documento, self._uso("claude-opus-5")


def montar_pipeline(repo, extrator) -> Pipeline:
    cfg = Config(
        database_url=URL,
        anthropic_api_key=None,
        modelo_triagem="claude-haiku-4-5",
        modelo_extracao="claude-opus-5",
        gmail_credentials=__import__("pathlib").Path("credentials.json"),
        gmail_token=__import__("pathlib").Path("token.json"),
        gmail_query="",
        mailbox="financeiro.test@gmail.com",
        fixtures_dir=__import__("pathlib").Path("fixtures"),
        demo_dir=__import__("pathlib").Path("fixtures/demo"),
        cache_dir=__import__("pathlib").Path(".cache"),
        storage_dir=__import__("pathlib").Path("/tmp/billpoc-test-storage"),
        org_id=repo.org_id,
        sync_janela=60,
    )
    return Pipeline(cfg, repo, extrator)


def email_com_boleto(assunto: str = "Boleto agosto", linha: str | None = None):
    linha = linha or montar_boleto_bancario(vencimento=VENCIMENTO, valor=VALOR)
    return parse_rfc822(
        montar_email(
            assunto=assunto,
            texto=f"Segue a cobrança.\nLinha digitável: {linha}",
            anexos=[("boleto.pdf", "application/pdf", b"%PDF-1.7\n" + b"x" * 6000)],
        )
    )


# ------------------------------------------------------------------------------------
# Caminho feliz
# ------------------------------------------------------------------------------------


def test_email_com_boleto_vira_payable_com_auditoria(repo):
    linha = montar_boleto_bancario(vencimento=VENCIMENTO, valor=VALOR)
    extrator = ExtratorFalso(montar_triagem(), montar_extraido(linha=linha))
    resultado = montar_pipeline(repo, extrator).processar(email_com_boleto(linha=linha), HOJE)

    assert resultado.erro is None
    assert len(resultado.payables) == 1
    assert resultado.faixa == "auto_ok"

    detalhe = repo.detalhe(resultado.payables[0])
    assert detalhe["valor_centavos"] == 123456
    assert detalhe["data_vencimento"] == VENCIMENTO
    assert detalhe["status"] == "em_revisao"  # nada entra aprovado

    # A trilha de auditoria nasce junto com o payable, não depois.
    campos = {c["campo"]: c for c in detalhe["campos"]}
    assert campos["valor"]["origem"] == "codigo_barras"
    assert campos["valor"]["confianca"] == 1
    assert campos["beneficiario"]["origem"] == "llm"
    assert campos["beneficiario"]["evidencia"]

    assert detalhe["verificacoes"], "nenhuma verificação foi gravada"
    assert detalhe["instrumentos"][0]["linha_digitavel"] == linha
    # O que a aritmética extraiu fica guardado para o revisor inspecionar.
    assert detalhe["instrumentos"][0]["decodificado"]["banco"] == "341"


def test_custo_e_latencia_ficam_registrados(repo, conexao):
    linha = montar_boleto_bancario(vencimento=VENCIMENTO, valor=VALOR)
    extrator = ExtratorFalso(montar_triagem(), montar_extraido(linha=linha))
    montar_pipeline(repo, extrator).processar(email_com_boleto(linha=linha), HOJE)

    with conexao.cursor() as cur:
        cur.execute(
            "select ps.etapa, ps.modelo, ps.custo_centavos from processing_steps ps "
            "join processing_runs r on r.id = ps.run_id "
            "where ps.modelo is not null and r.org_id = %s order by ps.etapa",
            (repo.org_id,),
        )
        passos = cur.fetchall()

    etapas = {p["etapa"] for p in passos}
    assert etapas == {"triage", "extract"}
    assert all(p["custo_centavos"] > 0 for p in passos)


# ------------------------------------------------------------------------------------
# Ruído
# ------------------------------------------------------------------------------------


def test_ruido_nao_gera_payable_mas_fica_registrado(repo, conexao):
    """Ruído descartado em silêncio é ruído impossível de auditar depois."""
    triagem = Triagem(
        e_conta_a_pagar=False,
        confianca=0.96,
        tipo_documento="outro",
        justificativa="Newsletter de marketing, sem documento de cobrança.",
    )
    extrator = ExtratorFalso(triagem)  # sem documento: extração não pode ser chamada
    email = parse_rfc822(montar_email(assunto="Novidades de agosto", texto="Confira nosso blog!"))

    resultado = montar_pipeline(repo, extrator).processar(email, HOJE)

    assert resultado.e_ruido
    assert resultado.payables == []
    assert extrator.chamadas_extracao == 0, "gastou o modelo caro em ruído"

    with conexao.cursor() as cur:
        cur.execute(
            "select c.e_conta_a_pagar, c.justificativa from classifications c "
            "join processing_runs r on r.id = c.run_id where r.org_id = %s",
            (repo.org_id,),
        )
        linha = cur.fetchone()
    assert linha["e_conta_a_pagar"] is False
    assert "Newsletter" in linha["justificativa"]


# ------------------------------------------------------------------------------------
# Idempotência e duplicata
# ------------------------------------------------------------------------------------


def test_reprocessar_o_mesmo_email_nao_duplica(repo, conta):
    linha = montar_boleto_bancario(vencimento=VENCIMENTO, valor=VALOR)
    extrator = ExtratorFalso(montar_triagem(), montar_extraido(linha=linha))
    pipeline = montar_pipeline(repo, extrator)
    email = email_com_boleto(linha=linha)

    primeira = pipeline.processar(email, HOJE)
    segunda = pipeline.processar(email, HOJE)

    assert not primeira.ja_processado
    assert segunda.ja_processado

    assert conta("email_messages") == 1
    # Mas os dois runs ficam: dá para comparar o resultado de duas execuções.
    assert conta("processing_runs") == 2


def test_boleto_reenviado_e_marcado_como_duplicata(repo):
    """O caso real: original, lembrete e segunda via do mesmo boleto na mesma caixa."""
    linha = montar_boleto_bancario(vencimento=VENCIMENTO, valor=VALOR)
    extrator = ExtratorFalso(montar_triagem(), montar_extraido(linha=linha))
    pipeline = montar_pipeline(repo, extrator)

    original = pipeline.processar(email_com_boleto("Boleto agosto", linha), HOJE)
    lembrete = pipeline.processar(
        email_com_boleto("Lembrete: boleto vence amanhã", linha), HOJE
    )

    assert not original.duplicado
    assert lembrete.duplicado
    assert repo.detalhe(lembrete.payables[0])["status"] == "duplicado"
    assert repo.detalhe(original.payables[0])["status"] == "em_revisao"


# ------------------------------------------------------------------------------------
# Divergência ponta a ponta
# ------------------------------------------------------------------------------------


def test_divergencia_de_valor_grava_o_valor_correto_e_o_bloqueio(repo):
    """Do e-mail ao banco: o modelo lê errado e o sistema grava o valor do código de barras."""
    linha = montar_boleto_bancario(vencimento=VENCIMENTO, valor=Decimal("9999.99"))
    extrator = ExtratorFalso(montar_triagem(), montar_extraido(linha=linha, valor="1234.56"))
    resultado = montar_pipeline(repo, extrator).processar(email_com_boleto(linha=linha), HOJE)

    detalhe = repo.detalhe(resultado.payables[0])
    assert detalhe["valor_centavos"] == 999999
    assert detalhe["faixa"] == "revisar"

    falhas = {v["check_nome"] for v in detalhe["verificacoes"] if not v["passou"]}
    assert "valor_confere" in falhas


# ------------------------------------------------------------------------------------
# Varredura determinística
# ------------------------------------------------------------------------------------


def test_linha_digitavel_encontrada_no_corpo_quando_o_modelo_nao_leu(repo):
    """O melhor caso: a linha vem do texto por regex validado, sem transcrição de ninguém."""
    linha = montar_boleto_bancario(vencimento=VENCIMENTO, valor=VALOR)
    extrator = ExtratorFalso(
        montar_triagem(),
        montar_extraido(linha=None, valor=None, vencimento=None),
    )
    email = parse_rfc822(
        montar_email(texto=f"Cobrança de agosto.\nPague com o código: {linha}")
    )
    resultado = montar_pipeline(repo, extrator).processar(email, HOJE)

    detalhe = repo.detalhe(resultado.payables[0])
    campos = {c["campo"]: c for c in detalhe["campos"]}
    assert campos["valor"]["origem"] == "codigo_barras"
    assert detalhe["valor_centavos"] == 123456
    assert detalhe["data_vencimento"] == VENCIMENTO


# ------------------------------------------------------------------------------------
# Ações do Finance Partner
# ------------------------------------------------------------------------------------


def test_correcao_humana_preserva_o_valor_original(repo, conexao):
    """Append-only: a correção entra como linha nova, a leitura do modelo continua lá."""
    extrator = ExtratorFalso(
        montar_triagem(), montar_extraido(tipo="nota_fiscal", linha=None, valor="100.00")
    )
    resultado = montar_pipeline(repo, extrator).processar(
        parse_rfc822(montar_email(texto="NF em anexo")), HOJE
    )
    payable_id = resultado.payables[0]

    repo.editar_campo(payable_id, "valor", "250.00", ator_id="00000000-0000-0000-0000-0000000000f1")

    detalhe = repo.detalhe(payable_id)
    assert detalhe["valor_centavos"] == 25000
    campos = {c["campo"]: c for c in detalhe["campos"]}
    assert campos["valor"]["origem"] == "humano"
    assert campos["valor"]["confianca"] == 1

    # O que o modelo tinha lido continua no banco, fora de vigência.
    with conexao.cursor() as cur:
        cur.execute(
            "select valor_normalizado, origem from field_extractions "
            "where payable_id=%s and campo='valor' and not vigente",
            (payable_id,),
        )
        antigo = cur.fetchone()
    assert antigo["valor_normalizado"] == "100.00"
    assert antigo["origem"] == "llm"

    # E a intervenção fica na trilha.
    assert detalhe["historico"][0]["acao"] == "editar_campo"
    assert detalhe["historico"][0]["valor_anterior"] == "100.00"


def test_aprovar_e_agendar_registra_o_pagamento_manual(repo):
    linha = montar_boleto_bancario(vencimento=VENCIMENTO, valor=VALOR)
    extrator = ExtratorFalso(montar_triagem(), montar_extraido(linha=linha))
    resultado = montar_pipeline(repo, extrator).processar(email_com_boleto(linha=linha), HOJE)
    payable_id = resultado.payables[0]
    fp = "00000000-0000-0000-0000-0000000000f1"

    repo.mudar_status(payable_id, "aprovado", "aprovar", fp)
    assert any(a["forma_pagamento"] == "boleto_bancario" for a in repo.agenda())

    repo.agendar(payable_id, VENCIMENTO, "Itaú", "PROTO-99887", fp)

    detalhe = repo.detalhe(payable_id)
    assert detalhe["status"] == "agendado"
    acoes = [h["acao"] for h in detalhe["historico"]]
    assert "agendar" in acoes and "aprovar" in acoes
    # Sai da agenda depois de agendado — não se agenda duas vezes o mesmo boleto.
    assert payable_id not in [str(a["id"]) for a in repo.agenda()]


# ------------------------------------------------------------------------------------
# Enriquecimento pelo histórico
# ------------------------------------------------------------------------------------


def _processar_mensalidades(repo, quantidade: int, valor=VALOR, cnpj="33000167000101"):
    """Processa N cobranças mensais do mesmo fornecedor. Devolve os payables."""
    ids = []
    for i in range(quantidade):
        venc = date(2026, 3 + i, 10)
        linha = montar_boleto_bancario(vencimento=venc, valor=valor)
        extrator = ExtratorFalso(
            montar_triagem(),
            montar_extraido(linha=linha, vencimento=venc.isoformat(), cnpj=cnpj),
        )
        r = montar_pipeline(repo, extrator).processar(
            email_com_boleto(f"Mensalidade {i}", linha), HOJE
        )
        ids.extend(r.payables)
    return ids


def test_fornecedor_vira_recorrente_depois_de_tres_cobrancas(repo):
    """O segundo boleto de um fornecedor deve ser mais fácil que o primeiro.

    O modelo lê um documento isolado e chuta 'unico'. O histórico sabe que este
    fornecedor cobra todo mês — e sabe de forma determinística.
    """
    ids = _processar_mensalidades(repo, 4)

    primeiro = repo.detalhe(ids[0])
    ultimo = repo.detalhe(ids[-1])

    # O extrator falso sempre devolve 'unico'; o histórico corrige a partir da quarta.
    assert primeiro["recorrencia"] == "unico"
    assert ultimo["recorrencia"] == "recorrente"

    campos = {c["campo"]: c for c in ultimo["campos"]}
    assert campos["recorrencia"]["origem"] == "historico"
    assert campos["recorrencia"]["confianca"] == 1
    assert ultimo["recurrence_group_id"] is not None


def test_categoria_confirmada_pelo_humano_vale_para_o_proximo_boleto(repo, conexao):
    """Corrigir a categoria uma vez faz o fornecedor inteiro entrar certo.

    É o mecanismo de aprendizado mais simples que existe: sem treino, sem prompt novo.
    """
    ids = _processar_mensalidades(repo, 1)
    detalhe = repo.detalhe(ids[0])
    assert detalhe["categoria_codigo"] == "SERVICOS_PJ"  # o que o modelo sugeriu

    repo.definir_categoria_padrao(str(detalhe["vendor_id"]), "SOFTWARE")

    linha = montar_boleto_bancario(vencimento=date(2026, 10, 10), valor=VALOR)
    extrator = ExtratorFalso(
        montar_triagem(), montar_extraido(linha=linha, vencimento="2026-10-10")
    )
    novo = montar_pipeline(repo, extrator).processar(
        email_com_boleto("Outubro", linha), HOJE
    )

    seguinte = repo.detalhe(novo.payables[0])
    assert seguinte["categoria_codigo"] == "SOFTWARE"
    campos = {c["campo"]: c for c in seguinte["campos"]}
    assert campos["categoria"]["origem"] == "historico"


def test_valor_fora_do_padrao_alerta_sem_bloquear(repo):
    """'Esse aluguel veio R$ 400 mais caro' — a pergunta que um analista faria."""
    _processar_mensalidades(repo, 3, valor=Decimal("1000.00"))

    caro = montar_boleto_bancario(vencimento=date(2026, 7, 10), valor=Decimal("3000.00"))
    extrator = ExtratorFalso(
        montar_triagem(),
        montar_extraido(linha=caro, valor="3000.00", vencimento="2026-07-10"),
    )
    r = montar_pipeline(repo, extrator).processar(email_com_boleto("Julho", caro), HOJE)

    conciliacao = r.conciliacoes[0]
    alertas = {v.nome for v in conciliacao.alertas}
    assert "valor_fora_do_padrao" in alertas
    # Alerta, não bloqueio: quem decide se o valor está certo é o humano.
    assert "valor_fora_do_padrao" not in {v.nome for v in conciliacao.bloqueios}


def test_variacao_normal_nao_gera_alerta(repo):
    _processar_mensalidades(repo, 3, valor=Decimal("1000.00"))

    linha = montar_boleto_bancario(vencimento=date(2026, 7, 10), valor=Decimal("1050.00"))
    extrator = ExtratorFalso(
        montar_triagem(),
        montar_extraido(linha=linha, valor="1050.00", vencimento="2026-07-10"),
    )
    r = montar_pipeline(repo, extrator).processar(email_com_boleto("Julho", linha), HOJE)
    assert "valor_fora_do_padrao" not in {v.nome for v in r.conciliacoes[0].alertas}


def test_historico_de_um_fornecedor_nao_contamina_outro(repo):
    """Isolamento por vendor: cada CNPJ tem o seu próprio histórico."""
    _processar_mensalidades(repo, 4, valor=Decimal("1000.00"))

    outro = montar_boleto_bancario(vencimento=date(2026, 8, 10), valor=Decimal("5000.00"))
    extrator = ExtratorFalso(
        montar_triagem(),
        montar_extraido(
            linha=outro, valor="5000.00", vencimento="2026-08-10", cnpj="00000000000191"
        ),
    )
    r = montar_pipeline(repo, extrator).processar(email_com_boleto("Outro", outro), HOJE)

    detalhe = repo.detalhe(r.payables[0])
    assert detalhe["recorrencia"] == "unico"  # fornecedor novo, sem histórico
    assert "valor_fora_do_padrao" not in {v.nome for v in r.conciliacoes[0].alertas}


# ------------------------------------------------------------------------------------
# Fila e resiliência
# ------------------------------------------------------------------------------------


def test_fila_prioriza_urgente_e_com_mais_bloqueios(repo):
    extrator_ok = ExtratorFalso(
        montar_triagem(),
        montar_extraido(linha=montar_boleto_bancario(vencimento=date(2026, 12, 1), valor=VALOR)),
    )
    montar_pipeline(repo, extrator_ok).processar(
        email_com_boleto("Tranquilo", montar_boleto_bancario(vencimento=date(2026, 12, 1), valor=VALOR)),
        HOJE,
    )

    urgente_linha = montar_boleto_bancario(vencimento=date(2026, 9, 1), valor=VALOR)
    extrator_urgente = ExtratorFalso(
        montar_triagem(), montar_extraido(linha=urgente_linha, cnpj="33000167000199")
    )
    montar_pipeline(repo, extrator_urgente).processar(
        email_com_boleto("Vence amanhã", urgente_linha), HOJE
    )

    fila = repo.fila_revisao()
    assert fila[0]["urgente"] is True
    assert fila[0]["falhas_bloqueantes"] > 0


def test_erro_em_um_email_nao_derruba_o_lote(repo):
    """Um e-mail com anexo corrompido não pode impedir os outros de serem processados."""

    class ExtratorQueFalha(ExtratorFalso):
        def extrair(self, email, anexo=None):
            raise RuntimeError("PDF ilegível")

    extrator = ExtratorQueFalha(montar_triagem(), montar_extraido())
    resultado = montar_pipeline(repo, extrator).processar(email_com_boleto(), HOJE)

    assert resultado.erro is not None
    assert "PDF ilegível" in resultado.erro
    assert resultado.payables == []


def test_relatorio_conta_origens_e_custos(repo):
    linha = montar_boleto_bancario(vencimento=VENCIMENTO, valor=VALOR)
    extrator = ExtratorFalso(montar_triagem(), montar_extraido(linha=linha))
    montar_pipeline(repo, extrator).processar(email_com_boleto(linha=linha), HOJE)

    dados = repo.relatorio()
    assert dados["payables"] >= 1
    origens = {o["origem"] for o in dados["origens"]}
    assert "codigo_barras" in origens and "llm" in origens
    assert any(c["etapa"] == "extract" for c in dados["custos"])
