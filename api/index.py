"""Ponto de entrada da função serverless da Vercel.

A Vercel descobre funções Python por convenção de diretório (`/api`) e serve a variável
`app` como aplicação ASGI. O `vercel.json` roteia `/api/*` para cá, e o resto para o
Next.js.

O `sys.path` precisa apontar para `apps/api/src` porque o pacote `billpoc` mora lá, e
não na raiz do repositório — o monorepo é organizado por aplicação, não achatado para
agradar o runtime.
"""

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "apps" / "api" / "src"))

from billpoc.api import app  # noqa: E402

__all__ = ["app"]
