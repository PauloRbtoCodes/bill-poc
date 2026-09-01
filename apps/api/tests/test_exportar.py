"""Testes da exportação da agenda de pagamento."""

from datetime import date
from decimal import Decimal

from billpoc.exportar import (
    Pagamento,
    para_cnab240,
    para_csv,
    para_erp,
    sem_linha_digitavel,
)

from .test_boleto import montar_boleto_bancario

LD = montar_boleto_bancario(vencimento=date(2026, 9, 15), valor=Decimal("1234.56"))

BOLETO = Pagamento(
    fornecedor="ACME SERVICOS LTDA",
    cnpj="33000167000101",
    valor_centavos=123456,
    vencimento=date(2026, 9, 15),
    documento="NF-4471",
    linha_digitavel=LD,
    pix=None,
)
PIX = Pagamento(
    fornecedor="NUVEMSOFT LTDA",
    cnpj=None,
    valor_centavos=89000,
    vencimento=date(2026, 9, 10),
    documento=None,
    linha_digitavel=None,
    pix="00020126...6304ABCD",
)


# ------------------------------------------------------------------------------------
# CSV
# ------------------------------------------------------------------------------------


def test_csv_usa_o_dialeto_que_o_excel_brasileiro_abre():
    """Ponto e vírgula e vírgula decimal: sem isso o Excel transforma valor em data."""
    saida = para_csv([BOLETO])
    linha = saida.splitlines()[1]
    assert linha.count(";") == 6
    assert "1234,56" in linha
    assert "15/09/2026" in linha


def test_csv_inclui_pagamento_sem_boleto():
    """O CSV é o formato abrangente — nada pode ficar de fora dele."""
    saida = para_csv([BOLETO, PIX])
    assert len(saida.strip().splitlines()) == 3
    assert "NUVEMSOFT LTDA" in saida


def test_erp_tem_as_colunas_que_conta_azul_e_omie_esperam():
    cabecalho = para_erp([BOLETO]).splitlines()[0]
    for coluna in ("Descrição", "Valor", "Data de vencimento", "CPF/CNPJ"):
        assert coluna in cabecalho


# ------------------------------------------------------------------------------------
# CNAB 240
# ------------------------------------------------------------------------------------


def _linhas(texto: str) -> list[str]:
    return [linha for linha in texto.split("\r\n") if linha]


def test_toda_linha_do_cnab_tem_exatamente_240_caracteres():
    """Um único registro com tamanho errado faz o banco rejeitar o arquivo inteiro."""
    arquivo = para_cnab240([BOLETO], empresa="CLIENTE DEMO", cnpj_empresa="11222333000181")
    for i, linha in enumerate(_linhas(arquivo), 1):
        assert len(linha) == 240, f"linha {i} tem {len(linha)}"


def test_estrutura_de_registros_do_cnab():
    """Header de arquivo, header de lote, um segmento J por boleto, dois trailers."""
    arquivo = para_cnab240(
        [BOLETO, BOLETO], empresa="CLIENTE DEMO", cnpj_empresa="11222333000181"
    )
    linhas = _linhas(arquivo)
    assert len(linhas) == 6
    assert linhas[0][7] == "0"  # header de arquivo
    assert linhas[1][7] == "1"  # header de lote
    assert linhas[2][7] == "3" and linhas[2][13] == "J"  # detalhe, segmento J
    assert linhas[3][7] == "3" and linhas[3][13] == "J"
    assert linhas[4][7] == "5"  # trailer de lote
    assert linhas[5][7] == "9"  # trailer de arquivo


def test_cnab_carrega_o_codigo_de_barras_e_o_valor():
    from billpoc.validate.boleto import linha_para_barras_bancario

    arquivo = para_cnab240([BOLETO], empresa="X", cnpj_empresa="11222333000181")
    detalhe = _linhas(arquivo)[2]
    assert linha_para_barras_bancario(LD) in detalhe
    assert "000000000123456" in detalhe  # valor em centavos, 15 posições
    assert "ACME SERVICOS LTDA" in detalhe


def test_trailer_soma_o_lote():
    arquivo = para_cnab240(
        [BOLETO, BOLETO], empresa="X", cnpj_empresa="11222333000181"
    )
    trailer = _linhas(arquivo)[4]
    assert str(123456 * 2).rjust(18, "0") in trailer


def test_pagamento_sem_boleto_fica_de_fora_do_cnab_mas_e_devolvido():
    """Sumir em silêncio seria pior que não exportar: a conta some da vista do FP."""
    arquivo = para_cnab240([BOLETO, PIX], empresa="X", cnpj_empresa="11222333000181")
    assert "NUVEMSOFT" not in arquivo
    assert len(_linhas(arquivo)) == 5  # só um segmento J
    assert sem_linha_digitavel([BOLETO, PIX]) == [PIX]


def test_cnab_vazio_ainda_e_um_arquivo_valido():
    arquivo = para_cnab240([], empresa="X", cnpj_empresa="11222333000181")
    linhas = _linhas(arquivo)
    assert len(linhas) == 4  # os dois headers e os dois trailers
    assert all(len(linha) == 240 for linha in linhas)


def test_da_agenda_converte_a_linha_da_view():
    p = Pagamento.da_agenda({
        "fornecedor": "ACME",
        "cnpj": "33000167000101",
        "valor_centavos": 5000,
        "data_vencimento": date(2026, 9, 1),
        "numero_documento": "123",
        "linha_digitavel": LD,
        "pix_copia_e_cola": None,
    })
    assert p.valor_centavos == 5000
    assert p.linha_digitavel == LD


def test_da_agenda_tolera_campos_ausentes():
    p = Pagamento.da_agenda({})
    assert p.fornecedor == "(sem fornecedor)"
    assert p.valor_centavos == 0
