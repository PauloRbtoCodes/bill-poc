"""Captura via Gmail API.

**Por que não IMAP.** A primeira coisa que testei com as credenciais do desafio foi
IMAP, e o Gmail respondeu ``[AUTHENTICATIONFAILED] Invalid credentials``: desde 2022 o
Google não aceita mais a senha da conta em cliente externo. Restam App Password (que
exige 2FA ligado) ou OAuth. Escolhi OAuth porque é também o caminho de produção.

**Como escalaria.** Este módulo faz *polling*, que serve para uma caixa e não serve para
cem. Em produção seriam duas mudanças: ``users.watch`` publicando em Pub/Sub para
receber push em vez de perguntar, e — mais importante — um endereço de encaminhamento
por cliente (``cliente@bills.…``), que elimina o consentimento OAuth por caixa e funciona
em qualquer provedor de e-mail, não só no Gmail. O `historyId` abaixo é o gancho para a
primeira; a segunda é outra implementação de `MailSource`.
"""

from __future__ import annotations

import base64
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .base import EmailCapturado, parse_rfc822

# Só leitura. O pipeline nunca precisa apagar, marcar ou responder nada — e um escopo
# mínimo é o que se quer numa caixa de financeiro de cliente.
ESCOPOS = ["https://www.googleapis.com/auth/gmail.readonly"]


class GmailSource:
    """Lê mensagens da caixa autenticada via Gmail API."""

    nome = "gmail"

    def __init__(
        self,
        credentials_path: str | Path = "credentials.json",
        token_path: str | Path = "token.json",
        query: str = "",
    ):
        self.credentials_path = Path(credentials_path)
        self.token_path = Path(token_path)
        # Query no dialeto de busca do Gmail. Vazia = caixa inteira.
        self.query = query
        self._service = None

    # ---------------------------------------------------------------------------------
    # Autenticação
    # ---------------------------------------------------------------------------------

    def autorizar(self) -> None:
        """Roda o fluxo OAuth de aplicativo desktop e guarda o token.

        Abre o navegador para o usuário logar e consentir. Nenhuma senha passa por aqui:
        o consentimento acontece na tela do Google, e o que fica em disco é um token de
        atualização com escopo de leitura.
        """
        from google_auth_oauthlib.flow import InstalledAppFlow

        if not self.credentials_path.exists():
            raise FileNotFoundError(
                f"{self.credentials_path} não encontrado.\n\n"
                "Para gerar:\n"
                "  1. console.cloud.google.com → criar projeto\n"
                "  2. APIs e Serviços → Biblioteca → habilitar 'Gmail API'\n"
                "  3. Credenciais → Criar → ID do cliente OAuth → tipo 'App para computador'\n"
                "  4. Baixar o JSON e salvar como credentials.json na raiz do repo"
            )

        fluxo = InstalledAppFlow.from_client_secrets_file(str(self.credentials_path), ESCOPOS)
        credenciais = fluxo.run_local_server(port=0)
        self.token_path.write_text(credenciais.to_json())

    def _credenciais(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        if not self.token_path.exists():
            raise RuntimeError("não autorizado — rode `billpoc auth` primeiro")

        credenciais = Credentials.from_authorized_user_file(str(self.token_path), ESCOPOS)
        if credenciais.expired and credenciais.refresh_token:
            credenciais.refresh(Request())
            self.token_path.write_text(credenciais.to_json())
        return credenciais

    @property
    def service(self):
        if self._service is None:
            from googleapiclient.discovery import build

            self._service = build("gmail", "v1", credentials=self._credenciais())
        return self._service

    # ---------------------------------------------------------------------------------
    # Leitura
    # ---------------------------------------------------------------------------------

    def listar(
        self, limite: int | None = None, desde: datetime | None = None
    ) -> Iterator[EmailCapturado]:
        query = self.query
        if desde is not None:
            # O operador `after:` do Gmail tem granularidade de dia; o filtro fino fica
            # no `recebido_em` depois, para não perder mensagem na borda.
            query = f"{query} after:{desde.strftime('%Y/%m/%d')}".strip()

        pagina = None
        vistos = 0
        while True:
            resposta = (
                self.service.users()
                .messages()
                .list(
                    userId="me",
                    q=query or None,
                    pageToken=pagina,
                    maxResults=min(100, limite - vistos) if limite else 100,
                )
                .execute()
            )

            for referencia in resposta.get("messages", []):
                if limite is not None and vistos >= limite:
                    return
                yield self._buscar(referencia["id"])
                vistos += 1

            pagina = resposta.get("nextPageToken")
            if not pagina or (limite is not None and vistos >= limite):
                return

    def _buscar(self, message_id: str) -> EmailCapturado:
        """Baixa a mensagem em RFC822 cru — o mesmo formato de um arquivo .eml."""
        mensagem = (
            self.service.users()
            .messages()
            .get(userId="me", id=message_id, format="raw")
            .execute()
        )
        raw = base64.urlsafe_b64decode(mensagem["raw"])
        return parse_rfc822(
            raw, message_id=message_id, thread_id=mensagem.get("threadId")
        )
