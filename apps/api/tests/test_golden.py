"""Golden set: regressão de acurácia sobre a caixa real.

O problema que isto resolve: prompt e modelo mudam, e a única forma honesta de saber se
uma mudança melhorou ou piorou é medir contra um conjunto de casos com resposta conhecida.
Sem isso, "mudei o prompt e ficou melhor" é opinião.

Como funciona:

- `golden/casos.json` guarda a resposta esperada por e-mail — classificação, e para as
  cobranças o fornecedor, valor e vencimento corretos. Os rótulos foram conferidos à mão
  contra os documentos.
- O teste roda o pipeline **em modo somente-cache**, então é determinístico, offline e de
  graça. O cache é populado por `billpoc run` sobre a caixa real.
- Falha se a acurácia cair abaixo do piso. Em CI isso bloqueia o deploy.

Os e-mails reais não vão para o git (dados de terceiros), então o teste pula sozinho
quando `fixtures/` não tem os `.eml` da caixa. Rodar localmente:

    uv run billpoc ingest --limite 60 && uv run billpoc run && uv run pytest tests/test_golden.py
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from billpoc.config import ORG_DEMO, carregar
from billpoc.extract.claude import Extrator, SemCredencial
from billpoc.ingest.eml import EmlSource
from billpoc.pipeline import Pipeline
from billpoc.store.db import BancoIndisponivel, conectar, schema_aplicado
from billpoc.store.repositories import Repositorio

GOLDEN = Path(__file__).parent / "golden" / "casos.json"

# Pisos de aceitação. Deliberadamente assimétricos: deixar passar ruído custa dois
# minutos de um humano; **perder uma cobrança** custa multa e ninguém descobre sozinho.
PISO_PRECISAO_TRIAGEM = 0.90  # do que foi marcado como cobrança, quanto era mesmo
PISO_RECALL_TRIAGEM = 1.00  # das cobranças que existem, quantas foram encontradas
PISO_ACURACIA_VALOR = 0.90
PISO_ACURACIA_VENCIMENTO = 0.90


@pytest.fixture(scope="module")
def resultados():
    """Roda o pipeline inteiro uma vez, em modo somente-cache."""
    if not GOLDEN.exists():
        pytest.skip("golden set ausente — veja o docstring deste arquivo")

    casos = {c["arquivo"]: c for c in json.loads(GOLDEN.read_text())["casos"]}
    cfg = carregar()

    disponiveis = {p.stem for p in cfg.fixtures_dir.glob("*.eml")} if cfg.fixtures_dir.is_dir() else set()
    if not disponiveis & set(casos):
        pytest.skip(
            "e-mails do golden set não estão em fixtures/ — rode "
            "`billpoc ingest --limite 60 && billpoc run`"
        )

    extrator = Extrator(
        modelo_triagem=cfg.modelo_triagem,
        modelo_extracao=cfg.modelo_extracao,
        cache_dir=cfg.cache_dir,
        somente_cache=True,  # determinístico e sem custo
    )

    try:
        with conectar(cfg.database_url) as conexao:
            if not schema_aplicado(conexao):
                pytest.skip("schema não aplicado")
            with conexao.cursor() as cur:
                cur.execute("insert into orgs (nome) values ('golden') returning id")
                org = str(cur.fetchone()["id"])
                cur.execute(
                    "insert into expense_categories (org_id, codigo, nome) "
                    "select %s, codigo, nome from expense_categories where org_id = %s",
                    (org, ORG_DEMO),
                )

            repo = Repositorio(conexao, org)
            pipeline = Pipeline(cfg, repo, extrator)

            saida = {}
            faltando = []
            for email in EmlSource(cfg.fixtures_dir).listar():
                if email.message_id not in casos:
                    continue
                try:
                    saida[email.message_id] = pipeline.processar(email)
                except SemCredencial:
                    faltando.append(email.message_id)

            if faltando:
                pytest.skip(
                    f"{len(faltando)} caso(s) sem resposta no cache — rode `billpoc run` "
                    "com a API key para popular"
                )

            yield casos, saida, repo
            conexao.rollback()
    except BancoIndisponivel:
        pytest.skip("Postgres indisponível")


# ------------------------------------------------------------------------------------
# Triagem
# ------------------------------------------------------------------------------------


def test_recall_da_triagem(resultados):
    """Nenhuma cobrança real pode ser descartada como ruído.

    Este é o piso mais rígido da suíte (100%) porque é o erro assimétrico: um falso
    positivo aparece na fila e o humano descarta; um falso negativo some, a conta não é
    paga, e o cliente descobre pela multa.
    """
    casos, saida, _ = resultados
    esperadas = {a for a, c in casos.items() if c["e_cobranca"]}
    perdidas = {
        a
        for a in esperadas
        if a in saida and (saida[a].e_ruido or saida[a].triagem is None)
    }
    recall = 1 - len(perdidas) / len(esperadas) if esperadas else 1.0
    assert recall >= PISO_RECALL_TRIAGEM, (
        f"cobranças classificadas como ruído: {sorted(perdidas)}"
    )


def test_precisao_da_triagem(resultados):
    """Ruído classificado como cobrança polui a fila do Finance Partner."""
    casos, saida, _ = resultados
    marcados = {a for a, r in saida.items() if not r.e_ruido and r.triagem}
    if not marcados:
        pytest.skip("nada classificado como cobrança")
    falsos = {a for a in marcados if not casos[a]["e_cobranca"]}
    precisao = 1 - len(falsos) / len(marcados)
    assert precisao >= PISO_PRECISAO_TRIAGEM, f"falsos positivos: {sorted(falsos)}"


# ------------------------------------------------------------------------------------
# Extração
# ------------------------------------------------------------------------------------


def _campos_esperados(casos, saida, chave):
    """Pares (esperado, obtido) para um campo, só nos casos que têm rótulo."""
    pares = []
    for arquivo, caso in casos.items():
        if not caso["e_cobranca"] or caso.get(chave) is None or arquivo not in saida:
            continue
        conciliacoes = saida[arquivo].conciliacoes
        if not conciliacoes:
            pares.append((arquivo, caso[chave], None))
            continue
        campo = conciliacoes[0].campos.get(
            {"valor": "valor", "vencimento": "data_vencimento"}[chave]
        )
        obtido = campo.valor if campo else None
        pares.append((arquivo, caso[chave], obtido))
    return pares


def test_acuracia_do_valor(resultados):
    casos, saida, _ = resultados
    pares = _campos_esperados(casos, saida, "valor")
    if not pares:
        pytest.skip("nenhum caso com valor rotulado")
    erros = [
        (a, esp, str(obt))
        for a, esp, obt in pares
        if obt is None or Decimal(str(obt)) != Decimal(esp)
    ]
    acuracia = 1 - len(erros) / len(pares)
    assert acuracia >= PISO_ACURACIA_VALOR, f"valores errados: {erros}"


def test_acuracia_do_vencimento(resultados):
    casos, saida, _ = resultados
    pares = _campos_esperados(casos, saida, "vencimento")
    if not pares:
        pytest.skip("nenhum caso com vencimento rotulado")
    erros = [
        (a, esp, str(obt)) for a, esp, obt in pares if obt is None or obt.isoformat() != esp
    ]
    acuracia = 1 - len(erros) / len(pares)
    assert acuracia >= PISO_ACURACIA_VENCIMENTO, f"vencimentos errados: {erros}"


# ------------------------------------------------------------------------------------
# A propriedade que não pode quebrar nunca
# ------------------------------------------------------------------------------------


def test_nada_com_bloqueio_entra_na_faixa_rapida(resultados):
    """Invariante da política, verificada sobre dados reais.

    Se algum dia um registro com verificação bloqueante aparecer como `auto_ok`, a tese
    inteira da POC caiu — e é o tipo de regressão que passa despercebida num refactor.
    """
    _, saida, _ = resultados
    for arquivo, resultado in saida.items():
        for c in resultado.conciliacoes:
            if c.bloqueios:
                assert c.faixa == "revisar", (
                    f"{arquivo}: faixa rápida com {len(c.bloqueios)} bloqueio(s)"
                )


def test_campo_deterministico_tem_confianca_maxima(resultados):
    """Valor vindo de aritmética nunca deve carregar confiança parcial."""
    _, saida, _ = resultados
    for arquivo, resultado in saida.items():
        for c in resultado.conciliacoes:
            for campo in c.campos.values():
                if campo.determinístico:
                    assert campo.confianca == 1.0, f"{arquivo}: {campo.nome}"
