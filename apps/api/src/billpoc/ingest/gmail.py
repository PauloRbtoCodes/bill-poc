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
import json
import os
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .base import EmailCapturado, parse_rfc822

# Só leitura. O pipeline nunca precisa apagar, marcar ou responder nada — e um escopo
# mínimo é o que se quer numa caixa de financeiro de cliente.
ESCOPOS = ["https://www.googleapis.com/auth/gmail.readonly"]

API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


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
        """Carrega o token, do arquivo local ou da variável de ambiente.

        Em deploy serverless não há disco persistente para guardar `token.json`, então o
        conteúdo dele vai como secret em `GMAIL_TOKEN_JSON`. O refresh acontece em
        memória: o token de acesso dura uma hora e é renovado a cada invocação fria, o
        que é aceitável. O que **não** pode acontecer é o refresh token se perder — por
        isso ele vem do secret e não de um arquivo que o host apaga.
        """
        import json

        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        if bruto := os.getenv("GMAIL_TOKEN_JSON"):
            credenciais = Credentials.from_authorized_user_info(json.loads(bruto), ESCOPOS)
            if credenciais.expired and credenciais.refresh_token:
                credenciais.refresh(Request())
            return credenciais

        if not self.token_path.exists():
            raise RuntimeError(
                "não autorizado — rode `billpoc auth`, ou defina GMAIL_TOKEN_JSON"
            )

        credenciais = Credentials.from_authorized_user_file(str(self.token_path), ESCOPOS)
        if credenciais.expired and credenciais.refresh_token:
            credenciais.refresh(Request())
            self.token_path.write_text(credenciais.to_json())
        return credenciais

    def _get(self, caminho: str, **parametros) -> dict:
        """Chamada autenticada à API do Gmail.

        Feita com `urllib` em vez de `google-api-python-client` de propósito. Aquela
        biblioteca embute os documentos de descoberta de 598 APIs do Google — 101 MB para
        usar dois endpoints do Gmail. Numa função serverless isso é a diferença entre
        caber e não caber no limite do pacote, e em qualquer lugar é cold start mais
        lento sem contrapartida.

        A autenticação continua na `google-auth`, que é pequena e sabe renovar o token
        corretamente. O que se descarta é só a camada de descoberta.
        """
        credenciais = self._credenciais()
        query = urlencode({k: v for k, v in parametros.items() if v is not None})
        url = f"{API_BASE}/{caminho}" + (f"?{query}" if query else "")

        requisicao = Request(url, headers={"Authorization": f"Bearer {credenciais.token}"})
        try:
            with urlopen(requisicao, timeout=30) as resposta:
                return json.loads(resposta.read())
        except HTTPError as exc:
            detalhe = exc.read().decode("utf-8", errors="replace")[:400]
            raise RuntimeError(f"Gmail API {exc.code} em {caminho}: {detalhe}") from exc

    # ---------------------------------------------------------------------------------
    # Leitura
    # ---------------------------------------------------------------------------------

    def listar_ids(
        self, limite: int | None = None, desde: datetime | None = None
    ) -> list[str]:
        """Só os identificadores, sem baixar as mensagens.

        Separado de `listar` porque a diferença de custo é enorme: `messages.list`
        devolve cem ids numa chamada, enquanto baixar cada mensagem é uma chamada por
        e-mail. A sincronização incremental precisa saber *quais* e-mails existem para
        decidir o que ainda falta — baixar todos só para descobrir isso transformaria
        cada passo em dezenas de chamadas à API.
        """
        query = self.query
        if desde is not None:
            # O operador `after:` do Gmail tem granularidade de dia; o filtro fino fica
            # no `recebido_em` depois, para não perder mensagem na borda.
            query = f"{query} after:{desde.strftime('%Y/%m/%d')}".strip()

        ids: list[str] = []
        pagina = None
        while True:
            resposta = self._get(
                "messages",
                q=query or None,
                pageToken=pagina,
                maxResults=min(100, limite - len(ids)) if limite else 100,
            )
            ids.extend(m["id"] for m in resposta.get("messages", []))
            pagina = resposta.get("nextPageToken")
            if not pagina or (limite is not None and len(ids) >= limite):
                return ids[:limite] if limite else ids

    def buscar(self, message_id: str) -> EmailCapturado:
        """Baixa uma mensagem específica pelo id."""
        return self._buscar(message_id)

    def listar(
        self, limite: int | None = None, desde: datetime | None = None
    ) -> Iterator[EmailCapturado]:
        for message_id in self.listar_ids(limite, desde):
            yield self._buscar(message_id)

    def _buscar(self, message_id: str) -> EmailCapturado:
        """Baixa a mensagem em RFC822 cru — o mesmo formato de um arquivo .eml."""
        mensagem = self._get(f"messages/{message_id}", format="raw")
        raw = base64.urlsafe_b64decode(mensagem["raw"])
        return parse_rfc822(
            raw, message_id=message_id, thread_id=mensagem.get("threadId")
        )
