"""Validação de CNPJ, incluindo o formato alfanumérico.

Desde julho de 2026 o CNPJ pode ter letras nas doze primeiras posições (IN RFB
2.229/2024). Os dois dígitos verificadores continuam numéricos, e o cálculo passa a usar
o valor ASCII do caractere menos 48 — o que faz `'0'` valer 0 e `'A'` valer 17, mantendo
compatibilidade com todos os CNPJ numéricos já emitidos.

Um CNPJ com DV inválido é sinal forte de erro de leitura (OCR trocando 0 por O, 1 por I,
5 por S) e derruba o registro para revisão.
"""

from __future__ import annotations

import re

_PESOS_DV1 = (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
_PESOS_DV2 = (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)

# Alfanumérico: dígitos e letras maiúsculas na raiz, dígitos nos dois DVs.
_PADRAO_CNPJ = re.compile(r"^[0-9A-Z]{12}[0-9]{2}$")

# Sequências de caractere repetido passam nos DVs por construção, mas não são CNPJ reais.
_REPETIDOS = {c * 14 for c in "0123456789"}


def normalizar(texto: str) -> str:
    """Remove pontuação e uniformiza para maiúsculas. Não valida."""
    return re.sub(r"[^0-9A-Za-z]", "", texto or "").upper()


def _valor(ch: str) -> int:
    """Valor do caractere no cálculo do DV: ASCII menos 48."""
    return ord(ch) - 48


def _calcular_dv(base: str, pesos: tuple[int, ...]) -> int:
    soma = sum(_valor(ch) * peso for ch, peso in zip(base, pesos, strict=True))
    resto = soma % 11
    return 0 if resto < 2 else 11 - resto


def valido(texto: str) -> bool:
    """True se os dois dígitos verificadores fecham."""
    cnpj = normalizar(texto)
    if not _PADRAO_CNPJ.match(cnpj) or cnpj in _REPETIDOS:
        return False
    return (
        _calcular_dv(cnpj[:12], _PESOS_DV1) == int(cnpj[12])
        and _calcular_dv(cnpj[:13], _PESOS_DV2) == int(cnpj[13])
    )


def formatar(texto: str) -> str:
    """Formata como ``00.000.000/0001-00``. Devolve a entrada crua se não tiver 14."""
    c = normalizar(texto)
    if len(c) != 14:
        return texto
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"


def alfanumerico(texto: str) -> bool:
    """True se o CNPJ usa o formato novo, com letras na raiz."""
    return any(ch.isalpha() for ch in normalizar(texto))


# Um CNPJ aparece no corpo do e-mail e no PDF em formatos variados. A filtragem dura é
# o DV, não o padrão.
_PADRAO_TEXTO = re.compile(r"(?<![0-9A-Za-z])([0-9A-Z]{2}[.\s]?[0-9A-Z]{3}[.\s]?[0-9A-Z]{3}[/\s]?[0-9A-Z]{4}[-\s]?\d{2})(?![0-9A-Za-z])")


def encontrar(texto: str) -> list[str]:
    """Devolve os CNPJ válidos encontrados no texto, sem repetição e na ordem de aparição."""
    achados: list[str] = []
    for match in _PADRAO_TEXTO.finditer(texto or ""):
        cnpj = normalizar(match.group(1))
        if valido(cnpj) and cnpj not in achados:
            achados.append(cnpj)
    return achados
