"""Testes da política de decisão.

Este arquivo é a especificação executável de como o sistema lida com incerteza. Cada
teste é um cenário que custa dinheiro se for tratado errado.
"""

from datetime import date
from decimal import Decimal

import pytest

from billpoc.extract.schemas import (
    CampoCategoria,
    CampoData,
    CampoRecorrencia,
    CampoTexto,
    CampoValor,
    DocumentoExtraido,
    Triagem,
)
from billpoc.validate.rules import conciliar

from .test_boleto import montar_boleto_bancario

HOJE = date(2026, 8, 31)
VENCIMENTO = date(2026, 9, 15)
VALOR = Decimal("1234.56")
CNPJ_VALIDO = "33000167000101"


def triagem(confianca: float = 0.97, e_conta: bool = True) -> Triagem:
    return Triagem(
        e_conta_a_pagar=e_conta,
        confianca=confianca,
        tipo_documento="boleto",
        justificativa="Boleto de fornecedor anexado ao e-mail.",
        anexos_relevantes=["boleto.pdf"],
    )


def extraido(
    *,
    tipo: str = "boleto",
    valor: str | None = "1234.56",
    valor_conf: float = 0.93,
    vencimento: str | None = "2026-09-15",
    venc_conf: float = 0.95,
    linha: str | None = None,
    cnpj: str | None = CNPJ_VALIDO,
    numero_nf: str | None = None,
    chave: str | None = None,
    pix: str | None = None,
    observacoes: str | None = None,
) -> DocumentoExtraido:
    return DocumentoExtraido(
        tipo_documento=tipo,
        beneficiario=CampoTexto(valor="ACME Serviços Ltda", confianca=0.96, evidencia="ACME"),
        cnpj=CampoTexto(valor=cnpj, confianca=0.94, evidencia="CNPJ 33.000.167/0001-01"),
        valor=CampoValor(valor_reais=valor, confianca=valor_conf, evidencia="R$ 1.234,56"),
        vencimento=CampoData(data=vencimento, confianca=venc_conf, evidencia="Venc. 15/09/2026"),
        data_emissao=CampoData(data="2026-08-20", confianca=0.9, evidencia="Emissão 20/08/2026"),
        linha_digitavel=CampoTexto(valor=linha, confianca=0.99, evidencia=linha),
        pix_copia_e_cola=CampoTexto(valor=pix, confianca=0.9, evidencia=pix),
        numero_nf=CampoTexto(valor=numero_nf, confianca=0.9, evidencia=numero_nf),
        chave_nfe=CampoTexto(valor=chave, confianca=0.9, evidencia=chave),
        categoria=CampoCategoria(
            categoria="SERVICOS_PJ", confianca=0.85, justificativa="Prestação de serviço"
        ),
        recorrencia=CampoRecorrencia(
            recorrencia="unico", confianca=0.8, justificativa="Sem menção a mensalidade"
        ),
        descricao="Serviço prestado em agosto/2026",
        observacoes=observacoes,
    )


# ------------------------------------------------------------------------------------
# Caminho feliz
# ------------------------------------------------------------------------------------


def test_boleto_com_leitura_concordante_vai_para_a_faixa_rapida():
    linha = montar_boleto_bancario(vencimento=VENCIMENTO, valor=VALOR)
    r = conciliar(extraido(linha=linha), triagem(), referencia=HOJE)

    assert r.faixa == "auto_ok", r.motivos()
    assert r.campos["valor"].valor == VALOR
    assert r.campos["data_vencimento"].valor == VENCIMENTO
    # Aritmética assume os campos: o valor gravado veio do código de barras, não do modelo.
    assert r.campos["valor"].origem == "codigo_barras"
    assert r.campos["valor"].confianca == 1.0
    assert r.conflitos == []


def test_faixa_rapida_nao_significa_pagamento_automatico():
    """auto_ok é posição na fila, não autorização. O status inicial é sempre em revisão."""
    linha = montar_boleto_bancario(vencimento=VENCIMENTO, valor=VALOR)
    r = conciliar(extraido(linha=linha), triagem(), referencia=HOJE)
    assert r.faixa == "auto_ok"
    assert r.bloqueios == []
    # Nada aqui aprova nada: quem aprova é o Finance Partner na UI.


# ------------------------------------------------------------------------------------
# Divergência — o cenário que a POC existe para pegar
# ------------------------------------------------------------------------------------


def test_valor_lido_errado_gera_conflito_e_a_aritmetica_vence():
    """O caso caro: o modelo lê R$ 1.234,56 num boleto de R$ 9.999,99."""
    linha = montar_boleto_bancario(vencimento=VENCIMENTO, valor=Decimal("9999.99"))
    r = conciliar(extraido(linha=linha, valor="1234.56"), triagem(), referencia=HOJE)

    assert r.faixa == "revisar"
    # O valor gravado é o do código de barras, não o que o modelo leu.
    assert r.campos["valor"].valor == Decimal("9999.99")
    conflito = r.campos["valor"].conflito
    assert conflito is not None
    assert conflito.valor_llm == "R$ 1.234,56"
    assert conflito.valor_deterministico == "R$ 9.999,99"
    assert conflito.fonte == "codigo_barras"
    # E o conflito é visível como falha bloqueante, não escondido.
    assert any(v.nome == "valor_confere" for v in r.bloqueios)


def test_vencimento_lido_errado_gera_conflito():
    """Errar o vencimento custa multa e juros — mesmo tratamento que errar o valor."""
    linha = montar_boleto_bancario(vencimento=date(2026, 9, 5), valor=VALOR)
    r = conciliar(extraido(linha=linha, vencimento="2026-09-15"), triagem(), referencia=HOJE)

    assert r.faixa == "revisar"
    assert r.campos["data_vencimento"].valor == date(2026, 9, 5)
    assert r.campos["data_vencimento"].conflito is not None
    assert any(v.nome == "data_vencimento_confere" for v in r.bloqueios)


def test_modelo_que_nao_leu_o_campo_nao_conta_como_divergencia():
    """Ausência não é discordância. O código de barras preenche e ninguém é penalizado."""
    linha = montar_boleto_bancario(vencimento=VENCIMENTO, valor=VALOR)
    r = conciliar(extraido(linha=linha, valor=None, vencimento=None), triagem(), referencia=HOJE)

    assert r.faixa == "auto_ok", r.motivos()
    assert r.campos["valor"].valor == VALOR
    assert r.campos["valor"].conflito is None


# ------------------------------------------------------------------------------------
# Leitura ruim da linha digitável
# ------------------------------------------------------------------------------------


def test_linha_digitavel_corrompida_descarta_a_fonte_e_bloqueia():
    """DV que não fecha significa transcrição errada: a fonte inteira é descartada."""
    linha = list(montar_boleto_bancario(vencimento=VENCIMENTO, valor=VALOR))
    linha[12] = str((int(linha[12]) + 1) % 10)
    r = conciliar(extraido(linha="".join(linha)), triagem(), referencia=HOJE)

    assert r.faixa == "revisar"
    assert r.boleto is None  # não se usa dado de um boleto cujo DV falhou
    assert any(v.nome.startswith("boleto_dv") for v in r.bloqueios)
    # E o valor cai para a leitura do modelo, agora explicitamente não corroborada.
    assert r.campos["valor"].origem == "llm"
    assert any(v.nome == "valor_sem_corroboracao" for v in r.bloqueios)


def test_linha_digitavel_com_digito_faltando_bloqueia():
    linha = montar_boleto_bancario()[:-1]
    r = conciliar(extraido(linha=linha), triagem(), referencia=HOJE)
    assert r.faixa == "revisar"
    assert any(v.nome == "linha_digitavel_formato" for v in r.bloqueios)


# ------------------------------------------------------------------------------------
# Documentos sem código de barras
# ------------------------------------------------------------------------------------


def test_nota_fiscal_sem_boleto_passa_com_alerta_e_nao_com_bloqueio():
    """Uma NF sem instrumento de pagamento nunca terá corroboração. Isso é do formato,
    não um defeito da extração — vira alerta, não bloqueio."""
    r = conciliar(
        extraido(tipo="nota_fiscal", linha=None, numero_nf="12345"),
        triagem(),
        referencia=HOJE,
    )
    assert r.faixa == "auto_ok", r.motivos()
    assert any(v.nome == "valor_sem_corroboracao" for v in r.alertas)


def test_boleto_sem_linha_digitavel_bloqueia():
    """Se o documento é boleto, a linha digitável deveria estar legível. Ausência é falha."""
    r = conciliar(extraido(tipo="boleto", linha=None), triagem(), referencia=HOJE)
    assert r.faixa == "revisar"
    assert any(v.nome == "valor_sem_corroboracao" and v.severidade == "bloqueante" for v in r.bloqueios)


def test_confianca_baixa_do_modelo_bloqueia_quando_nao_ha_corroboracao():
    """Sem aritmética para conferir, a confiança declarada pelo modelo é tudo o que há."""
    r = conciliar(
        extraido(tipo="nota_fiscal", linha=None, valor_conf=0.42),
        triagem(),
        referencia=HOJE,
    )
    assert r.faixa == "revisar"
    assert any(v.nome == "valor_confianca_minima" for v in r.bloqueios)


def test_confianca_baixa_nao_importa_quando_ha_corroboracao():
    """Modelo inseguro num campo que a aritmética confirma não é problema nenhum."""
    linha = montar_boleto_bancario(vencimento=VENCIMENTO, valor=VALOR)
    r = conciliar(extraido(linha=linha, valor_conf=0.30), triagem(), referencia=HOJE)
    assert r.faixa == "auto_ok", r.motivos()
    assert r.campos["valor"].confianca == 1.0


# ------------------------------------------------------------------------------------
# Pix
# ------------------------------------------------------------------------------------


def test_pix_corrobora_o_valor_quando_nao_ha_boleto():
    from billpoc.validate import pix as pix_mod

    payload = pix_mod.montar("acme@x.com", "ACME LTDA", "SAO PAULO", Decimal("1234.56"))
    r = conciliar(
        extraido(tipo="fatura", linha=None, pix=payload),
        triagem(),
        referencia=HOJE,
    )
    assert r.campos["valor"].origem == "pix"
    assert r.campos["valor"].valor == Decimal("1234.56")


def test_pix_adulterado_nao_corrobora_nada():
    from billpoc.validate import pix as pix_mod

    payload = pix_mod.montar("acme@x.com", "ACME LTDA", "SAO PAULO", Decimal("100.00"))
    r = conciliar(
        extraido(tipo="fatura", linha=None, pix=payload.replace("100.00", "900.00")),
        triagem(),
        referencia=HOJE,
    )
    assert r.pix is None
    assert any(v.nome == "pix_crc" for v in r.bloqueios)


# ------------------------------------------------------------------------------------
# Chave da NF-e
# ------------------------------------------------------------------------------------


def test_chave_nfe_corrobora_cnpj_e_numero_da_nota():
    from .test_documentos import montar_chave

    chave = montar_chave(cnpj_emitente=CNPJ_VALIDO, numero=54321)
    r = conciliar(
        extraido(tipo="nota_fiscal", linha=None, chave=chave, numero_nf="54321"),
        triagem(),
        referencia=HOJE,
    )
    assert r.campos["cnpj"].origem == "chave_nfe"
    assert r.campos["cnpj"].valor == CNPJ_VALIDO
    assert r.campos["numero_documento"].origem == "chave_nfe"
    assert r.campos["numero_documento"].valor == "54321"


def test_cnpj_divergente_da_chave_gera_conflito():
    """Pagar o fornecedor errado é tão caro quanto pagar o valor errado."""
    from .test_documentos import montar_chave

    chave = montar_chave(cnpj_emitente="00000000000191", numero=1)
    r = conciliar(
        extraido(tipo="nota_fiscal", linha=None, chave=chave, cnpj=CNPJ_VALIDO),
        triagem(),
        referencia=HOJE,
    )
    assert r.faixa == "revisar"
    assert r.campos["cnpj"].conflito is not None
    assert any(v.nome == "cnpj_confere" for v in r.bloqueios)


# ------------------------------------------------------------------------------------
# Sanidade e política
# ------------------------------------------------------------------------------------


def test_cnpj_com_dv_invalido_bloqueia():
    linha = montar_boleto_bancario(vencimento=VENCIMENTO, valor=VALOR)
    r = conciliar(extraido(linha=linha, cnpj="33000167000199"), triagem(), referencia=HOJE)
    assert r.faixa == "revisar"
    assert any(v.nome == "cnpj_dv" for v in r.bloqueios)


def test_duplicata_bloqueia():
    """Boleto reenviado como lembrete é o caso mais comum de pagamento em dobro."""
    linha = montar_boleto_bancario(vencimento=VENCIMENTO, valor=VALOR)
    r = conciliar(
        extraido(linha=linha), triagem(), referencia=HOJE, duplicado_de="payable-abc"
    )
    assert r.faixa == "revisar"
    assert any(v.nome == "nao_duplicado" for v in r.bloqueios)


def test_triagem_insegura_bloqueia():
    linha = montar_boleto_bancario(vencimento=VENCIMENTO, valor=VALOR)
    r = conciliar(extraido(linha=linha), triagem(confianca=0.55), referencia=HOJE)
    assert r.faixa == "revisar"
    assert any(v.nome == "triagem_confiante" for v in r.bloqueios)


def test_cobranca_ja_vencida_alerta_sem_bloquear():
    """Já vencida ainda se paga — mas o Finance Partner precisa saber que há juros."""
    linha = montar_boleto_bancario(vencimento=date(2026, 8, 10), valor=VALOR)
    r = conciliar(extraido(linha=linha, vencimento="2026-08-10"), triagem(), referencia=HOJE)
    assert r.faixa == "auto_ok", r.motivos()
    assert any(v.nome == "vencimento_futuro" for v in r.alertas)


def test_observacao_do_modelo_vira_alerta():
    """Quando o modelo diz 'tem algo estranho aqui', isso não se perde."""
    linha = montar_boleto_bancario(vencimento=VENCIMENTO, valor=VALOR)
    r = conciliar(
        extraido(linha=linha, observacoes="O PDF traz duas datas de vencimento diferentes."),
        triagem(),
        referencia=HOJE,
    )
    assert any(v.nome == "observacoes_do_modelo" for v in r.alertas)


def test_valor_zerado_bloqueia():
    r = conciliar(extraido(tipo="fatura", linha=None, valor=None), triagem(), referencia=HOJE)
    assert r.faixa == "revisar"
    assert any(v.nome == "valor_presente" for v in r.bloqueios)


def test_sem_vencimento_bloqueia():
    r = conciliar(
        extraido(tipo="fatura", linha=None, vencimento=None), triagem(), referencia=HOJE
    )
    assert r.faixa == "revisar"
    assert any(v.nome == "vencimento_presente" for v in r.bloqueios)


# ------------------------------------------------------------------------------------
# Confiança agregada
# ------------------------------------------------------------------------------------


def test_confianca_geral_e_o_elo_mais_fraco_e_nao_a_media():
    """Média esconde o campo ruim. Um CNPJ a 0.20 entre nove campos ótimos tem que doer."""
    r = conciliar(
        extraido(tipo="nota_fiscal", linha=None, valor_conf=0.20),
        triagem(),
        referencia=HOJE,
    )
    assert r.confianca_geral == pytest.approx(0.20)


def test_corroboracao_aritmetica_eleva_a_confianca_do_campo():
    linha = montar_boleto_bancario(vencimento=VENCIMENTO, valor=VALOR)
    sem = conciliar(extraido(tipo="nota_fiscal", linha=None), triagem(), referencia=HOJE)
    com = conciliar(extraido(linha=linha), triagem(), referencia=HOJE)
    assert com.confianca_geral > sem.confianca_geral
