"""Enriquecimento pelo histórico do fornecedor.

A ideia: **o segundo boleto de um fornecedor deveria ser mais fácil que o primeiro.**
Quando a mesma empresa já foi paga antes, o histórico responde coisas que o documento
não responde — em que categoria isso entra, se é mensalidade ou compra avulsa, e se o
valor deste mês fugiu do padrão.

Isso é o oposto do que um LLM faz bem. O modelo lê um documento isolado e não tem como
saber que este fornecedor sempre foi classificado como `SOFTWARE` nesta empresa, ou que
o aluguel vem todo dia 10. O histórico sabe, é determinístico e é de graça.

Três enriquecimentos, em ordem de confiança:

1. **Categoria** — se um humano já categorizou este fornecedor, essa decisão vale mais
   que o palpite do modelo. Ele viu um PDF; o humano conhece o negócio do cliente.
2. **Recorrência** — três cobranças do mesmo fornecedor em meses seguidos é mensalidade,
   independente do que o documento diga.
3. **Valor fora do padrão** — não muda nada, mas alerta. "Esse aluguel veio R$ 400 mais
   caro" é a pergunta que um analista financeiro humano faria.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import pairwise

# Quantas cobranças passadas bastam para afirmar que é recorrente. Três é o mínimo que
# distingue cadência de coincidência: duas podem ser uma compra repetida por acaso.
MINIMO_PARA_RECORRENCIA = 3

# Tolerância padrão antes de alertar sobre variação de valor. Conta de consumo (energia,
# água) varia naturalmente, então 15% evita alerta em todo mês.
TOLERANCIA_PADRAO = Decimal("15.0")

# Janelas de dias entre cobranças que caracterizam cada cadência.
_CADENCIAS = [
    ("mensal", 24, 38),
    ("bimestral", 50, 70),
    ("trimestral", 80, 100),
    ("semestral", 165, 200),
    ("anual", 340, 390),
]


@dataclass(frozen=True)
class Enriquecimento:
    """O que o histórico tem a dizer sobre esta cobrança."""

    categoria: str | None = None
    categoria_origem: str | None = None  # de onde veio: 'historico' ou None
    recorrencia: str | None = None
    cadencia: str | None = None
    ocorrencias: int = 0
    valor_medio_centavos: int | None = None
    variacao_percentual: Decimal | None = None

    @property
    def valor_fora_do_padrao(self) -> bool:
        return (
            self.variacao_percentual is not None
            and abs(self.variacao_percentual) > TOLERANCIA_PADRAO
        )

    def descricao_variacao(self) -> str:
        if self.variacao_percentual is None or self.valor_medio_centavos is None:
            return ""
        sinal = "acima" if self.variacao_percentual > 0 else "abaixo"
        media = Decimal(self.valor_medio_centavos) / 100
        return (
            f"{abs(self.variacao_percentual):.0f}% {sinal} da média das últimas "
            f"{self.ocorrencias} cobranças deste fornecedor (R$ {media:.2f})"
        )


# Fração dos intervalos que precisa cair na mesma janela para afirmar a cadência.
# Dois terços tolera um boleto atrasado sem aceitar datas aleatórias.
_CONSISTENCIA_MINIMA = 2 / 3


def _detectar_cadencia(datas: list[date]) -> str | None:
    """Classifica o intervalo típico entre cobranças consecutivas.

    Exige **consistência**, não só um intervalo típico plausível. A mediana sozinha erra:
    compras avulsas em 05/01, 19/01, 02/06 e 30/06 dão intervalos [14, 134, 28], cuja
    mediana é 28 — e o sistema afirmaria "mensal" para um fornecedor que na verdade
    vendeu duas vezes em janeiro e duas em junho.

    A regra é que a maioria dos intervalos caia na mesma janela. Isso tolera o boleto que
    atrasou (um intervalo fora) sem aceitar datas espalhadas.
    """
    if len(datas) < 2:
        return None
    ordenadas = sorted(datas)
    intervalos = [(b - a).days for a, b in pairwise(ordenadas)]

    melhor: tuple[str, int] | None = None
    for nome, minimo, maximo in _CADENCIAS:
        dentro = sum(1 for d in intervalos if minimo <= d <= maximo)
        if dentro / len(intervalos) >= _CONSISTENCIA_MINIMA and (
            melhor is None or dentro > melhor[1]
        ):
            melhor = (nome, dentro)
    return melhor[0] if melhor else None


def avaliar(
    *,
    valor_centavos: int | None,
    historico_valores: list[int],
    historico_datas: list[date],
    categoria_do_fornecedor: str | None = None,
) -> Enriquecimento:
    """Combina o histórico de um fornecedor com a cobrança atual.

    Função pura: recebe o histórico já carregado e não toca no banco. Isso mantém a
    regra testável sem Postgres, do mesmo jeito que os validadores.
    """
    ocorrencias = len(historico_valores)

    cadencia = _detectar_cadencia(historico_datas)
    recorrencia = (
        "recorrente"
        if ocorrencias >= MINIMO_PARA_RECORRENCIA and cadencia is not None
        else None
    )

    media = variacao = None
    if historico_valores and valor_centavos:
        media = sum(historico_valores) // len(historico_valores)
        if media > 0:
            variacao = (
                (Decimal(valor_centavos) - Decimal(media)) / Decimal(media) * 100
            ).quantize(Decimal("0.1"))

    return Enriquecimento(
        categoria=categoria_do_fornecedor,
        categoria_origem="historico" if categoria_do_fornecedor else None,
        recorrencia=recorrencia,
        cadencia=cadencia,
        ocorrencias=ocorrencias,
        valor_medio_centavos=media,
        variacao_percentual=variacao,
    )
