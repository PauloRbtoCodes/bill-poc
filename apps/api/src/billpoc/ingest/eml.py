"""Fonte de e-mails a partir de arquivos ``.eml`` em disco.

Existe por dois motivos, e os dois importam:

1. **A demo não pode depender de rede nem de OAuth.** Um token expirado no meio da call
   é um jeito ruim de descobrir que a apresentação acabou.
2. **Reprocessamento determinístico.** Mexer no prompt e rodar de novo sobre exatamente
   os mesmos e-mails é o que torna possível medir se a mudança melhorou ou piorou.

Os arquivos vêm do `billpoc ingest`, que salva o RFC822 cru de cada e-mail capturado do
Gmail. O mesmo parser lê os dois lados.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from .base import EmailCapturado, parse_rfc822


class EmlSource:
    """Lê ``*.eml`` de um diretório, em ordem cronológica."""

    nome = "eml"

    def __init__(self, diretorio: str | Path):
        self.diretorio = Path(diretorio)

    def listar(
        self, limite: int | None = None, desde: datetime | None = None
    ) -> Iterator[EmailCapturado]:
        if not self.diretorio.is_dir():
            raise FileNotFoundError(
                f"diretório de fixtures não encontrado: {self.diretorio}. "
                "Rode `billpoc ingest` para baixar os e-mails da caixa."
            )

        capturados: list[EmailCapturado] = []
        for caminho in sorted(self.diretorio.glob("*.eml")):
            email = parse_rfc822(caminho.read_bytes(), message_id=caminho.stem)
            if desde is not None and email.recebido_em < desde:
                continue
            capturados.append(email)

        capturados.sort(key=lambda e: e.recebido_em)
        yield from capturados[:limite] if limite else capturados

    def salvar(self, email: EmailCapturado) -> Path:
        """Grava um e-mail capturado como fixture, nomeado pelo message_id."""
        self.diretorio.mkdir(parents=True, exist_ok=True)
        seguro = "".join(c if c.isalnum() or c in "-_" else "_" for c in email.message_id)[:120]
        caminho = self.diretorio / f"{seguro}.eml"
        caminho.write_bytes(email.raw)
        return caminho
