"""Decodificação da chave de acesso da NF-e.

A chave de 44 dígitos é um presente para quem precisa auditar extração: ela **contém**
o CNPJ do emitente, o número da nota, a série, o modelo e o mês de emissão, tudo
protegido por um DV mod 11. Ou seja, três dos campos que o desafio pede — CNPJ, nº da NF
e (parcialmente) a data — podem ser conferidos contra o que o LLM leu, sem depender de
confiar no modelo.

Layout (posições 1-indexadas):

===========  ==========================================
 1-2         cUF — código IBGE do estado do emitente
 3-6         AAMM da emissão
 7-20        CNPJ do emitente
 21-22       modelo (55 = NF-e, 65 = NFC-e)
 23-25       série
 26-34       número da NF
 35          tipo de emissão
 36-43       código numérico aleatório
 44          DV mod 11
===========  ==========================================
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import cnpj as cnpj_mod

# Códigos IBGE de UF válidos, usados como sanidade adicional da chave.
_UFS = {
    "11", "12", "13", "14", "15", "16", "17",
    "21", "22", "23", "24", "25", "26", "27", "28", "29",
    "31", "32", "33", "35",
    "41", "42", "43",
    "50", "51", "52", "53",
}

_MODELOS = {"55": "NF-e", "65": "NFC-e"}


class ChaveError(ValueError):
    """A entrada não tem 44 dígitos."""


@dataclass(frozen=True)
class ChaveNFe:
    chave: str
    uf: str
    ano: int
    mes: int
    cnpj_emitente: str
    modelo: str
    serie: int
    numero: int
    dv: int
    dv_valido: bool
    uf_valida: bool
    modelo_valido: bool
    cnpj_valido: bool

    @property
    def valida(self) -> bool:
        return self.dv_valido and self.uf_valida and self.modelo_valido and self.cnpj_valido

    @property
    def descricao_modelo(self) -> str:
        return _MODELOS.get(self.modelo, f"desconhecido ({self.modelo})")


def dv_chave(chave_sem_dv: str) -> int:
    """DV mod 11 da chave, pesos 2..9 da direita para a esquerda. Resto 0 ou 1 → DV 0."""
    soma = 0
    peso = 2
    for ch in reversed(chave_sem_dv):
        soma += int(ch) * peso
        peso = 2 if peso == 9 else peso + 1
    resto = soma % 11
    return 0 if resto in (0, 1) else 11 - resto


def decodificar(texto: str) -> ChaveNFe:
    """Decodifica uma chave de acesso, aceitando espaços entre os grupos de quatro."""
    chave = re.sub(r"\D", "", texto or "")
    if len(chave) != 44:
        raise ChaveError(f"chave de acesso tem 44 dígitos, recebido {len(chave)}")

    emitente = chave[6:20]
    return ChaveNFe(
        chave=chave,
        uf=chave[0:2],
        ano=2000 + int(chave[2:4]),
        mes=int(chave[4:6]),
        cnpj_emitente=emitente,
        modelo=chave[20:22],
        serie=int(chave[22:25]),
        numero=int(chave[25:34]),
        dv=int(chave[43]),
        dv_valido=dv_chave(chave[:43]) == int(chave[43]),
        uf_valida=chave[0:2] in _UFS,
        modelo_valido=chave[20:22] in _MODELOS,
        cnpj_valido=cnpj_mod.valido(emitente),
    )


_PADRAO_CHAVE = re.compile(r"(?<!\d)((?:\d[\s.]?){43}\d)(?!\d)")


def encontrar(texto: str) -> list[ChaveNFe]:
    """Devolve as chaves de acesso válidas encontradas em texto livre."""
    achadas: list[ChaveNFe] = []
    vistas: set[str] = set()
    for match in _PADRAO_CHAVE.finditer(texto or ""):
        try:
            c = decodificar(match.group(1))
        except ChaveError:
            continue
        if c.valida and c.chave not in vistas:
            vistas.add(c.chave)
            achadas.append(c)
    return achadas
