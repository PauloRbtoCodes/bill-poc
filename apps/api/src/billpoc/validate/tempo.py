"""Data corrente no fuso que importa.

`date.today()` usa o fuso do processo. Num servidor em UTC, entre 21h e 00h de Brasília
ele já devolve o dia seguinte — e "esse boleto venceu?" passa a responder errado por três
horas todo dia. Vencimento é fronteira dura: o boleto vence no fim do dia em São Paulo,
não em Londres.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

FUSO_BRASIL = ZoneInfo("America/Sao_Paulo")


def hoje() -> date:
    """Data corrente no horário de Brasília."""
    return datetime.now(FUSO_BRASIL).date()


def agora() -> datetime:
    """Instante corrente, com fuso, para carimbar registros de auditoria."""
    return datetime.now(FUSO_BRASIL)
