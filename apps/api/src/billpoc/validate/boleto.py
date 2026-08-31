"""Decodificação e validação de boletos brasileiros.

Este é o núcleo determinístico da POC. A tese: **valor e vencimento de um boleto não
precisam ser confiados ao LLM — eles estão aritmeticamente codificados na própria
linha digitável.** Aqui só se faz aritmética: nenhum I/O, nenhuma rede, nenhum modelo.

Dois formatos convivem no Brasil:

1. **Boleto bancário de cobrança** — linha digitável de 47 dígitos, código de barras de
   44. Carrega banco, fator de vencimento e valor. Três DVs mod 10 (um por campo) e um
   DV geral mod 11.

2. **Boleto de arrecadação / convênio** (concessionárias, tributos, FGTS) — linha
   digitável de 48 dígitos iniciada em ``8``, código de barras de 44. Carrega valor,
   mas **não carrega vencimento**. Os DVs são mod 10 ou mod 11 conforme o 3º dígito.

Referência: FEBRABAN, Layout de Código de Barras (padrão vigente).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from .tempo import hoje as hoje_brasil

# Data-base do fator de vencimento FEBRABAN. O fator é a quantidade de dias corridos
# desde esta data; o primeiro fator efetivamente usado foi 1000 = 03/07/2000.
FATOR_BASE = date(1997, 10, 7)

# O fator tem 4 dígitos, então estourou em 9999 (21/02/2025) e reiniciou em 1000 no dia
# seguinte. Boletos emitidos a partir daí usam o segundo ciclo. Como o mesmo fator agora
# aponta para duas datas possíveis, `decodificar_fator` devolve as duas e escolhe a
# plausível em relação a uma data de referência.
FATOR_ROLLOVER = date(2025, 2, 22)
FATOR_MIN = 1000
FATOR_MAX = 9999


class BoletoError(ValueError):
    """Entrada que não é um boleto reconhecível (tamanho ou formato inválido)."""


@dataclass(frozen=True)
class Boleto:
    """Resultado da decodificação. Todo campo aqui veio de aritmética, não de leitura.

    `checks` lista cada verificação executada com seu resultado — é o que a UI mostra
    como badge e o que vai para a tabela `validation_results`.
    """

    tipo: str  # "bancario" | "arrecadacao"
    linha_digitavel: str  # só dígitos
    codigo_barras: str  # 44 dígitos
    valor: Decimal | None  # em reais; None quando o boleto é de valor aberto
    vencimento: date | None  # None em arrecadação e em boleto sem vencimento
    banco: str | None  # código de 3 dígitos, só em boleto bancário
    fator_vencimento: int | None
    checks: tuple[Check, ...] = ()

    @property
    def valido(self) -> bool:
        """True quando nenhum check bloqueante falhou."""
        return all(c.passou for c in self.checks if c.bloqueante)

    @property
    def falhas(self) -> tuple[Check, ...]:
        return tuple(c for c in self.checks if not c.passou)


@dataclass(frozen=True)
class Check:
    nome: str
    passou: bool
    bloqueante: bool = True
    esperado: str | None = None
    encontrado: str | None = None
    detalhe: str = ""


# --------------------------------------------------------------------------------------
# Dígitos verificadores
# --------------------------------------------------------------------------------------


def dv_mod10(bloco: str) -> int:
    """DV mod 10 usado nos três campos da linha digitável bancária.

    Multiplica os dígitos da direita para a esquerda alternando 2 e 1. Produto maior que
    9 tem seus algarismos somados (equivalente a subtrair 9). O DV é o que falta para o
    próximo múltiplo de 10.
    """
    soma = 0
    peso = 2
    for ch in reversed(bloco):
        produto = int(ch) * peso
        soma += produto if produto < 10 else produto - 9
        peso = 1 if peso == 2 else 2
    return (10 - soma % 10) % 10


def dv_mod11_barras(barcode_sem_dv: str) -> int:
    """DV geral (posição 5) do código de barras bancário, mod 11 com pesos 2..9.

    Calculado sobre os 43 dígitos restantes. Pela regra FEBRABAN, resultado 0, 10 ou 11
    vira DV 1 — é o caso especial que mais aparece implementado errado por aí.
    """
    soma = 0
    peso = 2
    for ch in reversed(barcode_sem_dv):
        soma += int(ch) * peso
        peso = 2 if peso == 9 else peso + 1
    resto = soma % 11
    dv = 11 - resto
    return 1 if dv in (0, 10, 11) else dv


def dv_mod11_arrecadacao(bloco: str) -> int:
    """DV mod 11 dos blocos de arrecadação. Pesos 2..9; resto 0 ou 1 → DV 0."""
    soma = 0
    peso = 2
    for ch in reversed(bloco):
        soma += int(ch) * peso
        peso = 2 if peso == 9 else peso + 1
    resto = soma % 11
    if resto in (0, 1):
        return 0
    return 11 - resto


# --------------------------------------------------------------------------------------
# Fator de vencimento
# --------------------------------------------------------------------------------------


def decodificar_fator(fator: int, referencia: date | None = None) -> date | None:
    """Converte fator de vencimento em data, resolvendo a ambiguidade do rollover.

    Desde 22/02/2025 o contador reiniciou, então um mesmo fator aponta para duas datas
    possíveis, separadas por 9000 dias (~24,6 anos). Escolhemos a mais próxima da data de
    referência — na prática a do ciclo novo, já que a antiga cairia nos anos 2000.

    Fator 0 significa "sem vencimento" (boleto à vista) e devolve None.
    """
    if fator == 0:
        return None
    if not (FATOR_MIN <= fator <= FATOR_MAX):
        # Fora da faixa válida: não dá para confiar. Deixa o LLM decidir e cai em revisão.
        return None

    referencia = referencia or hoje_brasil()
    ciclo_antigo = FATOR_BASE + timedelta(days=fator)
    ciclo_novo = FATOR_ROLLOVER + timedelta(days=fator - FATOR_MIN)

    candidatos = [d for d in (ciclo_antigo, ciclo_novo) if d is not None]
    return min(candidatos, key=lambda d: abs((d - referencia).days))


def codificar_fator(vencimento: date, ciclo_novo: bool = True) -> int:
    """Inverso de `decodificar_fator`. Usado nos testes para montar vetores."""
    if ciclo_novo:
        return (vencimento - FATOR_ROLLOVER).days + FATOR_MIN
    return (vencimento - FATOR_BASE).days


# --------------------------------------------------------------------------------------
# Normalização
# --------------------------------------------------------------------------------------


def apenas_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto or "")


def detectar_tipo(digitos: str) -> str:
    """Distingue boleto bancário de arrecadação pelo tamanho e pelo primeiro dígito."""
    if len(digitos) == 47:
        return "bancario"
    if len(digitos) == 48 and digitos.startswith("8"):
        return "arrecadacao"
    if len(digitos) == 44:
        return "arrecadacao" if digitos.startswith("8") else "bancario"
    raise BoletoError(
        f"esperado 47 dígitos (bancário), 48 iniciados em 8 (arrecadação) "
        f"ou 44 (código de barras); recebido {len(digitos)}"
    )


# --------------------------------------------------------------------------------------
# Boleto bancário — 47 dígitos
# --------------------------------------------------------------------------------------


def linha_para_barras_bancario(ld: str) -> str:
    """Remonta o código de barras de 44 dígitos a partir da linha digitável de 47.

    A linha digitável é o código de barras embaralhado com DVs intercalados. O campo
    livre (posições 20-44 do barcode) foi quebrado em três pedaços e movido para o começo;
    o DV geral e o bloco fator+valor foram movidos para o fim.
    """
    if len(ld) != 47:
        raise BoletoError(f"linha digitável bancária tem 47 dígitos, recebido {len(ld)}")
    return (
        ld[0:4]  # banco (3) + moeda (1)
        + ld[32]  # DV geral do código de barras
        + ld[33:47]  # fator de vencimento (4) + valor (10)
        + ld[4:9]  # campo livre, parte 1
        + ld[10:20]  # campo livre, parte 2
        + ld[21:31]  # campo livre, parte 3
    )


def barras_para_linha_bancario(barcode: str) -> str:
    """Inverso de `linha_para_barras_bancario`, com os DVs mod 10 recalculados."""
    if len(barcode) != 44:
        raise BoletoError(f"código de barras tem 44 dígitos, recebido {len(barcode)}")
    campo1 = barcode[0:4] + barcode[19:24]
    campo2 = barcode[24:34]
    campo3 = barcode[34:44]
    return (
        campo1
        + str(dv_mod10(campo1))
        + campo2
        + str(dv_mod10(campo2))
        + campo3
        + str(dv_mod10(campo3))
        + barcode[4]
        + barcode[5:19]
    )


def _decodificar_bancario(digitos: str, referencia: date | None) -> Boleto:
    checks: list[Check] = []

    if len(digitos) == 44:
        barcode = digitos
        linha = barras_para_linha_bancario(barcode)
    else:
        linha = digitos
        barcode = linha_para_barras_bancario(linha)

        # Os três DVs mod 10 provam que a linha digitável não foi lida ou digitada errado.
        for i, (ini, fim, pos_dv) in enumerate([(0, 9, 9), (10, 20, 20), (21, 31, 31)], 1):
            esperado = dv_mod10(linha[ini:fim])
            encontrado = int(linha[pos_dv])
            checks.append(
                Check(
                    nome=f"dv_campo_{i}",
                    passou=esperado == encontrado,
                    esperado=str(esperado),
                    encontrado=str(encontrado),
                    detalhe=f"DV mod 10 do campo {i} da linha digitável",
                )
            )

    dv_esperado = dv_mod11_barras(barcode[:4] + barcode[5:])
    dv_encontrado = int(barcode[4])
    checks.append(
        Check(
            nome="dv_geral",
            passou=dv_esperado == dv_encontrado,
            esperado=str(dv_esperado),
            encontrado=str(dv_encontrado),
            detalhe="DV geral mod 11 do código de barras",
        )
    )

    moeda = barcode[3]
    checks.append(
        Check(
            nome="moeda",
            passou=moeda == "9",
            bloqueante=False,
            esperado="9",
            encontrado=moeda,
            detalhe="código de moeda (9 = real)",
        )
    )

    fator = int(barcode[5:9])
    vencimento = decodificar_fator(fator, referencia)
    valor_centavos = int(barcode[9:19])
    valor = Decimal(valor_centavos) / 100 if valor_centavos > 0 else None

    checks.append(
        Check(
            nome="fator_vencimento",
            passou=fator == 0 or vencimento is not None,
            bloqueante=False,
            encontrado=str(fator),
            detalhe="fator fora da faixa 1000-9999 não decodifica para data confiável",
        )
    )
    checks.append(
        Check(
            nome="valor_presente",
            passou=valor is not None,
            bloqueante=False,
            encontrado=str(valor) if valor is not None else "0",
            detalhe="valor zerado significa boleto de valor aberto — exige confirmação humana",
        )
    )

    return Boleto(
        tipo="bancario",
        linha_digitavel=linha,
        codigo_barras=barcode,
        valor=valor,
        vencimento=vencimento,
        banco=barcode[0:3],
        fator_vencimento=fator,
        checks=tuple(checks),
    )


# --------------------------------------------------------------------------------------
# Arrecadação / convênio — 48 dígitos
# --------------------------------------------------------------------------------------

# 3º dígito do código de barras: identifica se o valor é efetivo em reais ou uma
# quantidade de moeda/referência, e qual mod usar nos DVs dos blocos.
_IDENTIFICADOR_VALOR = {
    "6": ("reais", dv_mod10),
    "7": ("referencia", dv_mod10),
    "8": ("reais", dv_mod11_arrecadacao),
    "9": ("referencia", dv_mod11_arrecadacao),
}


def _decodificar_arrecadacao(digitos: str, referencia: date | None) -> Boleto:
    checks: list[Check] = []

    if len(digitos) == 44:
        barcode = digitos
        linha = None
    else:
        linha = digitos
        # 4 blocos de 12: 11 dígitos de dado + 1 DV. O barcode é a concatenação dos dados.
        barcode = "".join(linha[i * 12 : i * 12 + 11] for i in range(4))

    identificador = barcode[2]
    if identificador not in _IDENTIFICADOR_VALOR:
        raise BoletoError(
            f"identificador de valor inválido em boleto de arrecadação: {identificador!r} "
            "(esperado 6, 7, 8 ou 9)"
        )
    natureza_valor, fn_dv = _IDENTIFICADOR_VALOR[identificador]

    if linha is not None:
        for i in range(4):
            bloco = linha[i * 12 : i * 12 + 11]
            esperado = fn_dv(bloco)
            encontrado = int(linha[i * 12 + 11])
            checks.append(
                Check(
                    nome=f"dv_bloco_{i + 1}",
                    passou=esperado == encontrado,
                    esperado=str(esperado),
                    encontrado=str(encontrado),
                    detalhe=f"DV do bloco {i + 1} ({'mod 11' if fn_dv is dv_mod11_arrecadacao else 'mod 10'})",
                )
            )

    # DV geral: posição 4 do barcode, calculado sobre os outros 43 dígitos.
    dv_esperado = fn_dv(barcode[:3] + barcode[4:])
    dv_encontrado = int(barcode[3])
    checks.append(
        Check(
            nome="dv_geral",
            passou=dv_esperado == dv_encontrado,
            esperado=str(dv_esperado),
            encontrado=str(dv_encontrado),
            detalhe="DV geral do código de barras de arrecadação",
        )
    )

    valor_centavos = int(barcode[4:15])
    valor = None
    if natureza_valor == "reais" and valor_centavos > 0:
        valor = Decimal(valor_centavos) / 100

    checks.append(
        Check(
            nome="valor_efetivo",
            passou=valor is not None,
            bloqueante=False,
            encontrado=str(valor) if valor is not None else natureza_valor,
            detalhe=(
                "identificador 7/9 indica quantidade de moeda, não valor em reais — "
                "o valor tem que vir do documento e não pode ser conferido aqui"
            ),
        )
    )
    # Arrecadação não codifica vencimento. Isso é uma limitação do formato, não um erro:
    # o vencimento vem do LLM e fica sem corroboração determinística.
    checks.append(
        Check(
            nome="vencimento_nao_codificado",
            passou=False,
            bloqueante=False,
            detalhe=(
                "boleto de arrecadação não carrega data de vencimento no código de barras; "
                "o vencimento extraído do documento não tem como ser conferido"
            ),
        )
    )

    return Boleto(
        tipo="arrecadacao",
        linha_digitavel=linha or "",
        codigo_barras=barcode,
        valor=valor,
        vencimento=None,
        banco=None,
        fator_vencimento=None,
        checks=tuple(checks),
    )


# --------------------------------------------------------------------------------------
# Ponto de entrada
# --------------------------------------------------------------------------------------


def decodificar(texto: str, referencia: date | None = None) -> Boleto:
    """Decodifica uma linha digitável ou código de barras, com formatação livre.

    Aceita a linha com pontos e espaços como aparece no PDF. Levanta `BoletoError` se o
    texto não tiver a cara de um boleto — o chamador trata isso como "sem corroboração
    determinística" e manda para revisão, nunca como erro fatal do pipeline.
    """
    digitos = apenas_digitos(texto)
    tipo = detectar_tipo(digitos)
    if tipo == "bancario":
        return _decodificar_bancario(digitos, referencia)
    return _decodificar_arrecadacao(digitos, referencia)


# Linha digitável costuma aparecer no PDF/e-mail formatada de várias formas. Este padrão
# é deliberadamente frouxo: encontra candidatos, e `decodificar` faz a filtragem dura via
# dígitos verificadores. Um falso positivo é barato; um boleto perdido não é.
_PADRAO_LINHA = re.compile(r"(?<![\d.])(\d[\d\s.\-]{44,60}\d)(?![\d.])")


def encontrar_linhas_digitaveis(texto: str, referencia: date | None = None) -> list[Boleto]:
    """Varre um texto livre e devolve todo boleto cujos dígitos verificadores fecham.

    A varredura só considera os formatos **humanos** — 47 dígitos (bancário) e 48
    (arrecadação) — e nunca o código de barras cru de 44. O motivo é probabilístico: a
    linha digitável de 47 carrega quatro DVs independentes, então uma sequência aleatória
    tem ~1 em 10.000 de passar; o barcode de 44 tem um único DV mod 11, ou seja 1 em 11.
    Varrer texto livre atrás de 44 dígitos gera falso positivo com frequência absurda —
    e um falso positivo aqui é uma conta a pagar inventada.
    """
    achados: list[Boleto] = []
    vistos: set[str] = set()
    for match in _PADRAO_LINHA.finditer(texto or ""):
        digitos = apenas_digitos(match.group(1))
        for tamanho in (47, 48):
            for inicio in range(max(0, len(digitos) - tamanho + 1)):
                candidato = digitos[inicio : inicio + tamanho]
                if len(candidato) != tamanho or candidato in vistos:
                    continue
                try:
                    boleto = decodificar(candidato, referencia)
                except (BoletoError, ValueError):
                    continue
                if boleto.valido:
                    vistos.add(candidato)
                    achados.append(boleto)
    return achados
