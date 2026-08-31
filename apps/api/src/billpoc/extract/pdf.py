"""Extração de texto de PDF.

O texto serve a dois consumidores com propósitos diferentes:

1. **A varredura determinística.** Se a linha digitável está no texto do PDF, ela é
   encontrada por regex e validada pelos dígitos verificadores — sem passar pelo modelo.
   Esta é a melhor situação possível: valor e vencimento vêm de aritmética sobre um dado
   que ninguém transcreveu. É também o caminho mais barato e o mais rápido.

2. **O contexto do LLM.** O PDF vai para o modelo como documento nativo (ele lê a página
   renderizada, não só o texto), mas o texto extraído acompanha porque ajuda em tabela e
   em fonte pequena.

PDF escaneado não tem camada de texto: `texto_de_pdf` devolve string vazia e o caminho
determinístico não se aplica. O modelo ainda lê a imagem, e o resultado cai em revisão
por falta de corroboração — que é exatamente o comportamento correto.
"""

from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)


def texto_de_pdf(conteudo: bytes, max_paginas: int = 20) -> str:
    """Extrai a camada de texto de um PDF. Devolve '' se não houver ou se falhar.

    Nunca levanta: um PDF corrompido não pode derrubar o processamento do e-mail inteiro.
    O pior caso é ficar sem o atalho determinístico e depender do modelo.
    """
    try:
        import pdfplumber
    except ImportError:  # pragma: no cover
        logger.warning("pdfplumber não instalado — extração de texto de PDF desabilitada")
        return ""

    try:
        with pdfplumber.open(io.BytesIO(conteudo)) as pdf:
            partes = [(pagina.extract_text() or "") for pagina in pdf.pages[:max_paginas]]
        return "\n\n".join(p for p in partes if p).strip()
    except Exception as exc:  # noqa: BLE001 — PDF corrompido, protegido por senha, formato exótico
        logger.warning("falha ao extrair texto do PDF: %s", exc)
        return ""


def contar_paginas(conteudo: bytes) -> int | None:
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(conteudo)) as pdf:
            return len(pdf.pages)
    except Exception:  # noqa: BLE001 — contagem de páginas é informativa
        return None
