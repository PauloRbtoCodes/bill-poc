"""Testes de CNPJ, chave de acesso da NF-e e Pix Copia e Cola.

Ao contrário do boleto — cujos vetores públicos são quase todos fabricados — aqui dá
para ancorar em coisas verificáveis de fato: CNPJ de empresas públicas conhecidas, o
exemplo oficial de CNPJ alfanumérico da Receita Federal, e o valor canônico do
CRC16-CCITT-FALSE para a string ``123456789`` (0x29B1).
"""

from decimal import Decimal

import pytest

from billpoc.validate import cnpj, nfe, pix

# ------------------------------------------------------------------------------------
# CNPJ
# ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "valor",
    [
        "00.000.000/0001-91",  # Banco do Brasil
        "33.000.167/0001-01",  # Petrobras
        "60.746.948/0001-12",  # Bradesco
        "00000000000191",  # sem formatação
    ],
)
def test_cnpj_real_valida(valor):
    assert cnpj.valido(valor)


@pytest.mark.parametrize(
    "valor",
    [
        "00.000.000/0001-92",  # DV trocado
        "00000000000000",  # repetido
        "11111111111111",
        "123",  # curto
        "",
    ],
)
def test_cnpj_invalido_reprova(valor):
    assert not cnpj.valido(valor)


def test_cnpj_alfanumerico_exemplo_oficial_da_receita():
    """A partir de julho/2026 o CNPJ pode ter letras. O DV usa ASCII menos 48."""
    assert cnpj.valido("12.ABC.345/01DE-35")
    assert cnpj.alfanumerico("12.ABC.345/01DE-35")
    assert not cnpj.valido("12.ABC.345/01DE-99")


def test_cnpj_numerico_nao_e_marcado_como_alfanumerico():
    assert not cnpj.alfanumerico("00.000.000/0001-91")


def test_formatar_cnpj():
    assert cnpj.formatar("00000000000191") == "00.000.000/0001-91"
    assert cnpj.formatar("abc") == "abc"  # devolve a entrada quando não dá para formatar


def test_encontra_cnpj_no_corpo_do_email():
    corpo = """
    Fornecedor: ACME Serviços Ltda
    CNPJ: 33.000.167/0001-01
    Inscrição estadual: 123.456.789.000
    Contato: 11 98888-7777
    """
    assert cnpj.encontrar(corpo) == ["33000167000101"]


def test_cnpj_com_dv_errado_nao_e_capturado_do_texto():
    """OCR trocando dígito é o caso real: o DV é o que impede o erro de passar."""
    assert cnpj.encontrar("CNPJ: 33.000.167/0001-99") == []


# ------------------------------------------------------------------------------------
# Chave de acesso NF-e
# ------------------------------------------------------------------------------------


def montar_chave(
    uf: str = "35",
    ano: int = 26,
    mes: int = 8,
    cnpj_emitente: str = "33000167000101",
    modelo: str = "55",
    serie: int = 1,
    numero: int = 123456,
    tipo_emissao: str = "1",
    codigo: str = "12345678",
) -> str:
    base = (
        f"{uf}{ano:02d}{mes:02d}{cnpj_emitente}{modelo}{serie:03d}{numero:09d}"
        f"{tipo_emissao}{codigo}"
    )
    assert len(base) == 43, len(base)
    return base + str(nfe.dv_chave(base))


def test_chave_decodifica_cnpj_numero_e_serie():
    """Três campos que o desafio pede saem da chave sem passar por LLM nenhum."""
    chave = montar_chave(numero=987654, serie=3)
    c = nfe.decodificar(chave)
    assert c.valida
    assert c.cnpj_emitente == "33000167000101"
    assert c.numero == 987654
    assert c.serie == 3
    assert c.modelo == "55"
    assert c.descricao_modelo == "NF-e"
    assert (c.ano, c.mes) == (2026, 8)


def test_chave_com_digito_trocado_reprova():
    chave = list(montar_chave())
    chave[20] = str((int(chave[20]) + 1) % 10)
    assert not nfe.decodificar("".join(chave)).valida


def test_chave_aceita_grupos_separados_por_espaco():
    chave = montar_chave()
    agrupada = " ".join(chave[i : i + 4] for i in range(0, 44, 4))
    assert nfe.decodificar(agrupada).chave == chave


def test_chave_com_uf_inexistente_reprova_mesmo_com_dv_ok():
    """O DV fecha, mas 99 não é UF. Sanidade extra pega erro que o DV deixa passar."""
    chave = montar_chave(uf="99")
    c = nfe.decodificar(chave)
    assert c.dv_valido
    assert not c.uf_valida
    assert not c.valida


def test_chave_com_cnpj_invalido_reprova():
    chave = montar_chave(cnpj_emitente="33000167000199")
    c = nfe.decodificar(chave)
    assert c.dv_valido
    assert not c.cnpj_valido
    assert not c.valida


def test_tamanho_errado_levanta_erro_tratavel():
    with pytest.raises(nfe.ChaveError):
        nfe.decodificar("123")


def test_encontra_chave_no_texto_do_danfe():
    chave = montar_chave()
    texto = f"DANFE — consulta em www.nfe.fazenda.gov.br\nChave de acesso {chave}\nEmitido em 08/2026"
    achadas = nfe.encontrar(texto)
    assert [c.chave for c in achadas] == [chave]


# ------------------------------------------------------------------------------------
# Pix
# ------------------------------------------------------------------------------------


def test_crc16_vetor_canonico():
    """CRC16-CCITT-FALSE tem valor de referência conhecido para '123456789'."""
    assert pix.crc16("123456789") == 0x29B1


def test_pix_roundtrip_com_valor():
    payload = pix.montar(
        chave="financeiro@fornecedor.com.br",
        beneficiario="FORNECEDOR LTDA",
        cidade="SAO PAULO",
        valor=Decimal("1234.56"),
    )
    p = pix.decodificar(payload)
    assert p.valido
    assert p.valor == Decimal("1234.56")
    assert p.chave == "financeiro@fornecedor.com.br"
    assert p.beneficiario == "FORNECEDOR LTDA"
    assert p.cidade == "SAO PAULO"


def test_pix_sem_valor_e_cobranca_aberta():
    """Sem o campo 54 não há valor para conferir — o documento manda, e sem corroboração."""
    p = pix.decodificar(pix.montar("chave@x.com", "X LTDA", "RECIFE"))
    assert p.valido
    assert p.valor is None


def test_pix_adulterado_quebra_o_crc():
    """Trocar um centavo no payload invalida o CRC. É o equivalente ao DV do boleto."""
    payload = pix.montar("chave@x.com", "X LTDA", "RECIFE", Decimal("100.00"))
    adulterado = payload.replace("100.00", "900.00")
    assert not pix.decodificar(adulterado).valido


def test_pix_truncado_levanta_erro():
    payload = pix.montar("chave@x.com", "X LTDA", "RECIFE", Decimal("10.00"))
    with pytest.raises(pix.PixError):
        pix.decodificar(payload[:60])


def test_pix_sem_campo_crc_levanta_erro():
    with pytest.raises(pix.PixError):
        pix.decodificar("00020126360014BR.GOV.BCB.PIX")
