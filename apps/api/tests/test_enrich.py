"""Testes do enriquecimento pelo histórico do fornecedor."""

from datetime import date, timedelta
from decimal import Decimal

from billpoc.enrich import MINIMO_PARA_RECORRENCIA, avaliar


def mensal(n: int, inicio: date = date(2026, 1, 10)) -> list[date]:
    """n vencimentos mensais, com o desalinhamento normal de dias úteis."""
    return [inicio + timedelta(days=30 * i + (i % 3)) for i in range(n)]


# ------------------------------------------------------------------------------------
# Recorrência
# ------------------------------------------------------------------------------------


def test_tres_cobrancas_mensais_caracterizam_recorrencia():
    r = avaliar(
        valor_centavos=50000,
        historico_valores=[50000] * 3,
        historico_datas=mensal(3),
    )
    assert r.recorrencia == "recorrente"
    assert r.cadencia == "mensal"


def test_duas_cobrancas_ainda_nao_sao_cadencia():
    """Duas podem ser compra repetida por acaso. Três distinguem padrão de coincidência."""
    r = avaliar(valor_centavos=50000, historico_valores=[50000] * 2, historico_datas=mensal(2))
    assert r.recorrencia is None


def test_fornecedor_novo_nao_e_recorrente():
    r = avaliar(valor_centavos=50000, historico_valores=[], historico_datas=[])
    assert r.recorrencia is None
    assert r.ocorrencias == 0


def test_cadencia_anual_e_reconhecida():
    datas = [date(2024, 3, 5), date(2025, 3, 7), date(2026, 3, 4)]
    r = avaliar(valor_centavos=120000, historico_valores=[120000] * 3, historico_datas=datas)
    assert r.cadencia == "anual"
    assert r.recorrencia == "recorrente"


def test_compras_avulsas_sem_cadencia_nao_viram_recorrencia():
    """Mesmo fornecedor, mas em datas irregulares: é compra, não mensalidade."""
    datas = [date(2026, 1, 5), date(2026, 1, 19), date(2026, 6, 2), date(2026, 6, 30)]
    r = avaliar(valor_centavos=8000, historico_valores=[8000] * 4, historico_datas=datas)
    assert r.cadencia is None
    assert r.recorrencia is None


def test_boleto_atrasado_nao_muda_a_cadencia():
    """A mediana ignora o outlier; a média não ignoraria."""
    datas = [date(2026, 1, 10), date(2026, 2, 10), date(2026, 3, 10), date(2026, 7, 10)]
    r = avaliar(valor_centavos=50000, historico_valores=[50000] * 4, historico_datas=datas)
    assert r.cadencia == "mensal"


def test_minimo_para_recorrencia_e_respeitado():
    r = avaliar(
        valor_centavos=1,
        historico_valores=[1] * (MINIMO_PARA_RECORRENCIA - 1),
        historico_datas=mensal(MINIMO_PARA_RECORRENCIA - 1),
    )
    assert r.recorrencia is None


# ------------------------------------------------------------------------------------
# Categoria
# ------------------------------------------------------------------------------------


def test_categoria_confirmada_vem_do_historico():
    r = avaliar(
        valor_centavos=50000,
        historico_valores=[50000],
        historico_datas=[date(2026, 1, 10)],
        categoria_do_fornecedor="SOFTWARE",
    )
    assert r.categoria == "SOFTWARE"
    assert r.categoria_origem == "historico"


def test_sem_categoria_confirmada_o_historico_nao_opina():
    """O palpite do LLM em cobranças passadas não vira 'histórico' — só decisão humana."""
    r = avaliar(valor_centavos=50000, historico_valores=[50000], historico_datas=[])
    assert r.categoria is None
    assert r.categoria_origem is None


# ------------------------------------------------------------------------------------
# Valor fora do padrão
# ------------------------------------------------------------------------------------


def test_valor_muito_acima_da_media_gera_alerta():
    """'Esse aluguel veio R$ 400 mais caro' é a pergunta que um humano faria."""
    r = avaliar(
        valor_centavos=150000,
        historico_valores=[100000, 100000, 100000],
        historico_datas=mensal(3),
    )
    assert r.valor_fora_do_padrao
    assert r.variacao_percentual == Decimal("50.0")
    assert "acima" in r.descricao_variacao()


def test_variacao_pequena_nao_alerta():
    """Conta de consumo varia naturalmente — alertar todo mês seria ruído."""
    r = avaliar(
        valor_centavos=105000,
        historico_valores=[100000, 100000, 100000],
        historico_datas=mensal(3),
    )
    assert not r.valor_fora_do_padrao


def test_valor_muito_abaixo_tambem_alerta():
    """Cobrança menor que o normal também merece olho: pode ser parcial ou erro."""
    r = avaliar(
        valor_centavos=20000,
        historico_valores=[100000, 100000, 100000],
        historico_datas=mensal(3),
    )
    assert r.valor_fora_do_padrao
    assert "abaixo" in r.descricao_variacao()


def test_sem_historico_nao_ha_variacao_a_medir():
    r = avaliar(valor_centavos=50000, historico_valores=[], historico_datas=[])
    assert r.variacao_percentual is None
    assert not r.valor_fora_do_padrao
    assert r.descricao_variacao() == ""


def test_sem_valor_atual_nao_quebra():
    r = avaliar(valor_centavos=None, historico_valores=[100000], historico_datas=mensal(1))
    assert r.variacao_percentual is None
