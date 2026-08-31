"""Testes do decodificador de boletos.

Nota sobre vetores de teste: as linhas digitáveis que circulam em blogs e tutoriais são
quase todas fabricadas ou corrompidas — várias falham nos próprios dígitos verificadores.
Por isso os testes aqui usam boletos **construídos** por `montar_boleto_bancario`, que é
o inverso exato do decodificador, mais três âncoras da especificação FEBRABAN cujos
valores são publicamente verificáveis (fator 1000 = 03/07/2000, fator 9999 = 21/02/2025,
reinício do ciclo em 22/02/2025).

A validação contra boletos reais acontece no teste de integração sobre `fixtures/`.
"""

from datetime import date
from decimal import Decimal

import pytest

from billpoc.validate.boleto import (
    Boleto,
    BoletoError,
    barras_para_linha_bancario,
    codificar_fator,
    decodificar,
    decodificar_fator,
    dv_mod10,
    dv_mod11_arrecadacao,
    dv_mod11_barras,
    encontrar_linhas_digitaveis,
    linha_para_barras_bancario,
)


def montar_boleto_bancario(
    banco: str = "341",
    vencimento: date = date(2026, 9, 15),
    valor: Decimal = Decimal("1234.56"),
    campo_livre: str = "1790001043510049102015000",
) -> str:
    """Constrói uma linha digitável válida de 47 dígitos. Inverso do decodificador."""
    assert len(campo_livre) == 25
    fator = codificar_fator(vencimento)
    centavos = int(valor * 100)
    sem_dv = f"{banco}9{fator:04d}{centavos:010d}{campo_livre}"
    dv = dv_mod11_barras(sem_dv)
    barcode = f"{banco}9{dv}{fator:04d}{centavos:010d}{campo_livre}"
    assert len(barcode) == 44
    return barras_para_linha_bancario(barcode)


# ------------------------------------------------------------------------------------
# Dígitos verificadores
# ------------------------------------------------------------------------------------


def test_dv_mod10_dobra_alternado_e_soma_algarismos():
    # 21 -> pesos 2,1 da direita: 1*2=2, 2*1=2 -> soma 4 -> DV 6
    assert dv_mod10("21") == 6
    # produto maior que 9 tem os algarismos somados: 9*2=18 -> 1+8=9
    assert dv_mod10("9") == 1


def test_dv_mod11_barras_trata_caso_especial_como_1():
    """Resultado 0, 10 ou 11 vira DV 1 — é a regra mais implementada errado."""
    # Busca um bloco cujo resto force o caso especial, e confirma que nunca sai 0 ou 10.
    for n in range(10_000):
        bloco = f"{n:043d}"
        dv = dv_mod11_barras(bloco)
        assert 1 <= dv <= 9, f"DV fora da faixa válida em {bloco}: {dv}"


def test_dv_mod11_arrecadacao_usa_zero_no_caso_especial():
    """Ao contrário do DV geral bancário, arrecadação usa 0 quando o resto é 0 ou 1."""
    assert dv_mod11_arrecadacao("0" * 11) == 0


# ------------------------------------------------------------------------------------
# Fator de vencimento — âncoras da especificação
# ------------------------------------------------------------------------------------


def test_ancoras_febraban_do_fator_de_vencimento():
    ref_antiga = date(2000, 1, 1)
    assert decodificar_fator(1000, referencia=ref_antiga) == date(2000, 7, 3)
    assert decodificar_fator(9999, referencia=date(2025, 1, 1)) == date(2025, 2, 21)
    # O contador estourou em 9999 e reiniciou em 1000 no dia seguinte.
    assert decodificar_fator(1000, referencia=date(2026, 1, 1)) == date(2025, 2, 22)


def test_rollover_escolhe_o_ciclo_plausivel():
    """O mesmo fator aponta para duas datas separadas por 9000 dias.

    Este é o bug silencioso que mais custa dinheiro: um decodificador escrito antes de
    2025 devolve 2001 para um boleto que vence em 2026, e o pagamento entra como atrasado.
    """
    fator = 1500
    assert decodificar_fator(fator, referencia=date(2002, 1, 1)) == date(2001, 11, 15)
    assert decodificar_fator(fator, referencia=date(2026, 8, 31)) == date(2026, 7, 7)
    # As duas leituras do mesmo fator estão a 9000 dias uma da outra.
    assert (date(2026, 7, 7) - date(2001, 11, 15)).days == 9000


def test_fator_zero_significa_sem_vencimento():
    assert decodificar_fator(0) is None


def test_fator_fora_da_faixa_nao_inventa_data():
    """Preferimos None (cai em revisão) a uma data errada."""
    assert decodificar_fator(999) is None
    assert decodificar_fator(10_000) is None


# ------------------------------------------------------------------------------------
# Boleto bancário
# ------------------------------------------------------------------------------------


def test_decodifica_valor_e_vencimento_do_codigo_de_barras():
    ld = montar_boleto_bancario(vencimento=date(2026, 9, 15), valor=Decimal("1234.56"))
    b = decodificar(ld, referencia=date(2026, 8, 31))
    assert b.valido
    assert b.valor == Decimal("1234.56")
    assert b.vencimento == date(2026, 9, 15)
    assert b.banco == "341"
    assert b.tipo == "bancario"


def test_linha_digitavel_e_codigo_de_barras_sao_inversos():
    ld = montar_boleto_bancario()
    barcode = linha_para_barras_bancario(ld)
    assert len(barcode) == 44
    assert barras_para_linha_bancario(barcode) == ld


def test_aceita_linha_formatada_como_aparece_no_pdf():
    ld = montar_boleto_bancario()
    formatada = f"{ld[:5]}.{ld[5:10]} {ld[10:15]}.{ld[15:21]} {ld[21:26]}.{ld[26:32]} {ld[32]} {ld[33:]}"
    assert decodificar(formatada, referencia=date(2026, 8, 31)).valido


def test_digito_trocado_derruba_a_validacao():
    """O ponto inteiro dos DVs: um dígito errado na leitura tem que ser detectado."""
    ld = list(montar_boleto_bancario())
    ld[15] = str((int(ld[15]) + 1) % 10)
    b = decodificar("".join(ld), referencia=date(2026, 8, 31))
    assert not b.valido
    assert any(c.nome.startswith("dv_campo") for c in b.falhas)


def test_valor_adulterado_derruba_o_dv_geral():
    """Trocar o valor no barcode invalida o DV mod 11 — não dá para adulterar em silêncio."""
    ld = montar_boleto_bancario(valor=Decimal("100.00"))
    barcode = list(linha_para_barras_bancario(ld))
    barcode[9] = "9"  # infla o valor
    b = decodificar(barras_para_linha_bancario("".join(barcode)), referencia=date(2026, 8, 31))
    assert not b.valido
    assert any(c.nome == "dv_geral" for c in b.falhas)


def test_valor_zerado_e_sinalizado_mas_nao_bloqueia():
    ld = montar_boleto_bancario(valor=Decimal("0"))
    b = decodificar(ld, referencia=date(2026, 8, 31))
    assert b.valido  # os DVs fecham
    assert b.valor is None  # mas não há valor para conferir
    assert any(c.nome == "valor_presente" and not c.passou for c in b.checks)


def test_tamanho_invalido_levanta_erro_tratavel():
    with pytest.raises(BoletoError):
        decodificar("1234")


# ------------------------------------------------------------------------------------
# Varredura de texto livre
# ------------------------------------------------------------------------------------


def test_encontra_boleto_no_meio_de_texto_livre():
    ld = montar_boleto_bancario(valor=Decimal("890.10"))
    corpo = f"""
    Prezado cliente, segue a cobrança referente ao mês de agosto.
    Linha digitável: {ld[:5]}.{ld[5:10]} {ld[10:15]}.{ld[15:21]} {ld[21:26]}.{ld[26:32]} {ld[32]} {ld[33:]}
    Qualquer dúvida, responda este e-mail.
    """
    achados = encontrar_linhas_digitaveis(corpo, referencia=date(2026, 8, 31))
    assert len(achados) == 1
    assert achados[0].valor == Decimal("890.10")


def test_numeros_aleatorios_nao_viram_boleto():
    """Os DVs filtram falso positivo: ~1 em 10.000 de uma sequência aleatória passar."""
    ruido = "Protocolo 12345678901234567890123456789012345678901234567 registrado."
    assert encontrar_linhas_digitaveis(ruido, referencia=date(2026, 8, 31)) == []


# ------------------------------------------------------------------------------------
# Arrecadação
# ------------------------------------------------------------------------------------


def montar_arrecadacao(valor: Decimal = Decimal("250.00"), identificador: str = "8") -> str:
    """Constrói uma linha de arrecadação de 48 dígitos.

    Layout do código de barras: produto(1) + segmento(1) + identificador(1) + DV(1)
    + valor(11) + campo livre(29) = 44.
    """
    from billpoc.validate.boleto import _IDENTIFICADOR_VALOR

    _, fn_dv = _IDENTIFICADOR_VALOR[identificador]
    centavos = int(valor * 100)
    segmento = "1"  # prefeitura
    sem_dv = f"8{segmento}{identificador}{centavos:011d}" + "1" * 29
    assert len(sem_dv) == 43, len(sem_dv)
    dv = fn_dv(sem_dv)
    barcode = sem_dv[:3] + str(dv) + sem_dv[3:]
    assert len(barcode) == 44
    blocos = [barcode[i * 11 : (i + 1) * 11] for i in range(4)]
    return "".join(b + str(fn_dv(b)) for b in blocos)


def test_arrecadacao_decodifica_valor_e_admite_nao_ter_vencimento():
    linha = montar_arrecadacao(valor=Decimal("250.00"))
    b = decodificar(linha)
    assert b.tipo == "arrecadacao"
    assert b.valido
    assert b.valor == Decimal("250.00")
    assert b.vencimento is None
    # O sistema precisa saber que não pode conferir o vencimento deste documento.
    assert any(c.nome == "vencimento_nao_codificado" and not c.passou for c in b.checks)


def test_arrecadacao_com_identificador_de_referencia_nao_afirma_valor():
    """Identificador 9 significa quantidade de moeda, não reais. Não dá para conferir."""
    linha = montar_arrecadacao(valor=Decimal("250.00"), identificador="9")
    b = decodificar(linha)
    assert b.valor is None
    assert any(c.nome == "valor_efetivo" and not c.passou for c in b.checks)
