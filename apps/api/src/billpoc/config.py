"""Configuração via ambiente.

Tudo que é credencial ou endereço vem de `.env`. Nada de segredo no código, e nenhum
caminho absoluto de máquina — o repo tem que rodar na máquina do entrevistador também.

O design privilegia degradar em vez de quebrar: sem chave da Anthropic o pipeline roda
em modo somente-cache; sem Postgres ele avisa qual comando subir. Uma POC que só funciona
com tudo configurado é uma POC que não funciona na hora da demo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# raiz do repositório: .../case-bill
RAIZ = Path(__file__).resolve().parents[4]

load_dotenv(RAIZ / ".env")

ORG_DEMO = "00000000-0000-0000-0000-000000000001"
USUARIO_SISTEMA = "00000000-0000-0000-0000-0000000000f0"
USUARIO_FP = "00000000-0000-0000-0000-0000000000f1"


@dataclass(frozen=True)
class Config:
    # --- banco ---
    database_url: str

    # --- LLM ---
    anthropic_api_key: str | None
    modelo_triagem: str
    modelo_extracao: str

    # --- Gmail ---
    gmail_credentials: Path
    gmail_token: Path
    gmail_query: str
    mailbox: str

    # --- caminhos ---
    fixtures_dir: Path
    cache_dir: Path
    storage_dir: Path

    org_id: str

    @property
    def tem_llm(self) -> bool:
        """Há credencial para chamar a API?

        O SDK também resolve credencial por perfil OAuth (`ant auth login`), então a
        ausência da variável não é prova definitiva — mas é o suficiente para escolher o
        modo padrão e avisar cedo em vez de estourar no meio do processamento.
        """
        return bool(self.anthropic_api_key or os.getenv("ANTHROPIC_AUTH_TOKEN"))

    @property
    def tem_gmail(self) -> bool:
        return self.gmail_token.exists()


def carregar() -> Config:
    return Config(
        database_url=os.getenv(
            "DATABASE_URL", "postgresql://postgres:billpoc@localhost:55432/billpoc"
        ),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        modelo_triagem=os.getenv("MODELO_TRIAGEM", "claude-haiku-4-5"),
        modelo_extracao=os.getenv("MODELO_EXTRACAO", "claude-opus-5"),
        gmail_credentials=Path(os.getenv("GMAIL_CREDENTIALS", RAIZ / "credentials.json")),
        gmail_token=Path(os.getenv("GMAIL_TOKEN", RAIZ / "token.json")),
        gmail_query=os.getenv("GMAIL_QUERY", ""),
        mailbox=os.getenv("MAILBOX", "financeiro.test@gmail.com"),
        fixtures_dir=Path(os.getenv("FIXTURES_DIR", RAIZ / "fixtures")),
        cache_dir=Path(os.getenv("CACHE_DIR", RAIZ / ".cache" / "llm")),
        storage_dir=Path(os.getenv("STORAGE_DIR", RAIZ / ".storage")),
        org_id=os.getenv("ORG_ID", ORG_DEMO),
    )
