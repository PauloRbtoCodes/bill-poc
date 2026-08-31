"""Decodificação do Pix Copia e Cola (BR Code, padrão EMV®QRCPS do Bacen).

O BR Code é um TLV: cada campo é ``ID(2) + tamanho(2) + valor``. O último campo é sempre
``63`` — um CRC16-CCITT sobre todo o payload anterior, incluindo o próprio cabeçalho
``6304``. Isso dá, de graça, a mesma garantia que os DVs dão no boleto: se o CRC fecha,
o texto não foi truncado nem corrompido, e o valor no campo ``54`` é confiável.

Nem todo Pix traz valor — cobrança de valor aberto omite o campo 54. Nesse caso o valor
vem do documento e fica sem corroboração determinística, exatamente como na arrecadação.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


class PixError(ValueError):
    """Payload malformado — TLV inconsistente ou campo obrigatório ausente."""


@dataclass(frozen=True)
class Pix:
    payload: str
    chave: str | None
    valor: Decimal | None
    beneficiario: str | None
    cidade: str | None
    txid: str | None
    crc_valido: bool
    campos: dict[str, str]

    @property
    def valido(self) -> bool:
        return self.crc_valido


def crc16(dados: str) -> int:
    """CRC16-CCITT-FALSE: polinômio 0x1021, inicial 0xFFFF, sem reflexão."""
    crc = 0xFFFF
    for byte in dados.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def _parse_tlv(dados: str) -> dict[str, str]:
    """Quebra um bloco TLV em {id: valor}. Levanta se os tamanhos não fecharem."""
    campos: dict[str, str] = {}
    i = 0
    while i < len(dados):
        if i + 4 > len(dados):
            raise PixError(f"TLV truncado na posição {i}")
        ident = dados[i : i + 2]
        try:
            tamanho = int(dados[i + 2 : i + 4])
        except ValueError as exc:
            raise PixError(f"tamanho não numérico no campo {ident!r}") from exc
        fim = i + 4 + tamanho
        if fim > len(dados):
            raise PixError(f"campo {ident!r} declara {tamanho} bytes além do fim do payload")
        campos[ident] = dados[i + 4 : fim]
        i = fim
    return campos


def decodificar(payload: str) -> Pix:
    """Decodifica um Pix Copia e Cola e confere o CRC."""
    payload = (payload or "").strip()
    if len(payload) < 8 or not payload.startswith("00"):
        raise PixError("payload não começa com o campo 00 (Payload Format Indicator)")

    marcador = payload.rfind("6304")
    if marcador == -1 or marcador + 8 != len(payload):
        raise PixError("campo CRC (6304) ausente ou fora da última posição")

    crc_declarado = payload[marcador + 4 :].upper()
    crc_calculado = f"{crc16(payload[: marcador + 4]):04X}"

    campos = _parse_tlv(payload[:marcador])

    # 26 é o Merchant Account Information do Pix; dentro dele, 01 é a chave e 02 o txid.
    conta = _parse_tlv(campos.get("26", "")) if campos.get("26") else {}

    valor = None
    if bruto := campos.get("54"):
        try:
            valor = Decimal(bruto)
        except InvalidOperation as exc:
            raise PixError(f"valor não numérico no campo 54: {bruto!r}") from exc

    return Pix(
        payload=payload,
        chave=conta.get("01"),
        valor=valor,
        beneficiario=campos.get("59"),
        cidade=campos.get("60"),
        txid=(_parse_tlv(campos["62"]).get("05") if campos.get("62") else None),
        crc_valido=crc_declarado == crc_calculado,
        campos=campos,
    )


def montar(
    chave: str,
    beneficiario: str,
    cidade: str,
    valor: Decimal | None = None,
    txid: str = "***",
) -> str:
    """Monta um BR Code estático válido. Usado nos testes e para gerar fixtures."""

    def tlv(ident: str, valor_campo: str) -> str:
        return f"{ident}{len(valor_campo):02d}{valor_campo}"

    conta = tlv("00", "br.gov.bcb.pix") + tlv("01", chave)
    corpo = (
        tlv("00", "01")
        + tlv("26", conta)
        + tlv("52", "0000")
        + tlv("53", "986")
        + (tlv("54", f"{valor:.2f}") if valor is not None else "")
        + tlv("58", "BR")
        + tlv("59", beneficiario[:25])
        + tlv("60", cidade[:15])
        + tlv("62", tlv("05", txid))
    )
    sem_crc = corpo + "6304"
    return sem_crc + f"{crc16(sem_crc):04X}"
