"""Conexão com o Postgres.

SQL direto, sem ORM. O schema é pequeno, as consultas são específicas, e num projeto que
alguém vai ler para avaliar decisões técnicas, `select` legível vale mais que uma camada
de abstração a mais para entender.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row


class BancoIndisponivel(RuntimeError):
    pass


@contextmanager
def conectar(database_url: str) -> Iterator[psycopg.Connection]:
    """Abre conexão com `dict_row`, commitando ao sair sem exceção."""
    try:
        conexao = psycopg.connect(database_url, row_factory=dict_row, autocommit=False)
    except psycopg.OperationalError as exc:
        raise BancoIndisponivel(
            f"não consegui conectar em {_mascarar(database_url)}.\n"
            "Suba o Postgres local com `docker compose up -d` e aplique o schema:\n"
            '  psql "postgresql://postgres:billpoc@localhost:55432/billpoc" '
            "-f db/schema.sql -f db/seed.sql"
        ) from exc

    try:
        with conexao:
            yield conexao
    finally:
        conexao.close()


def _mascarar(url: str) -> str:
    """Esconde a senha antes de a URL aparecer numa mensagem de erro ou num log."""
    if "@" not in url:
        return url
    inicio, _, fim = url.rpartition("@")
    esquema, _, credenciais = inicio.partition("://")
    usuario, _, _senha = credenciais.partition(":")
    return f"{esquema}://{usuario}:***@{fim}"


def schema_aplicado(conexao: psycopg.Connection) -> bool:
    with conexao.cursor() as cur:
        cur.execute("select to_regclass('public.payables') is not null as ok")
        linha = cur.fetchone()
        return bool(linha and linha["ok"])
