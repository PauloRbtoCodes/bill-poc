"""Modelo do e-mail capturado e o parser RFC822 compartilhado.

Toda fonte de e-mail — Gmail API hoje, endereço de encaminhamento amanhã, IMAP de um
cliente que insiste — produz o mesmo `EmailCapturado`. O pipeline nunca sabe de onde o
e-mail veio, o que é o ponto: trocar de canal de entrada não deveria tocar em extração,
validação ou persistência.

O parser é compartilhado de propósito. O Gmail API devolve RFC822 cru quando pedido com
``format='raw'``, que é exatamente o que um arquivo ``.eml`` contém. Uma implementação
só, exercitada pelos dois caminhos.
"""

from __future__ import annotations

import email
import email.policy
import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime
from typing import Protocol

# Partes que são decoração do e-mail, não documento. Assinatura corporativa em PNG e
# rastreador de abertura em GIF de 1px entrariam como "anexo" e poluiriam a triagem.
_MIME_IGNORADOS = {"image/gif"}
_TAMANHO_MINIMO_ANEXO = 2048  # bytes; abaixo disso é logo de assinatura, não boleto


@dataclass(frozen=True)
class Anexo:
    nome_arquivo: str
    mime_type: str
    conteudo: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.conteudo).hexdigest()

    @property
    def tamanho(self) -> int:
        return len(self.conteudo)

    @property
    def extensao(self) -> str:
        _, _, ext = self.nome_arquivo.rpartition(".")
        return ext.lower() if ext else ""

    @property
    def e_pdf(self) -> bool:
        return self.mime_type == "application/pdf" or self.extensao == "pdf"

    @property
    def e_xml(self) -> bool:
        return self.mime_type in ("application/xml", "text/xml") or self.extensao == "xml"

    @property
    def e_imagem(self) -> bool:
        return self.mime_type.startswith("image/")

    def classificar(self) -> str:
        """Palpite inicial pelo nome e tipo. A triagem refina depois."""
        nome = self.nome_arquivo.lower()
        if self.e_xml:
            return "nfe_xml"
        if self.e_pdf:
            if "boleto" in nome or "cobranca" in nome or "cobrança" in nome:
                return "boleto_pdf"
            if "danfe" in nome or "nfe" in nome or "nota" in nome:
                return "danfe_pdf"
            if "fatura" in nome or "invoice" in nome:
                return "fatura_pdf"
            if "recibo" in nome:
                return "recibo"
            return "boleto_pdf" if "pdf" == self.extensao else "desconhecido"
        if self.e_imagem:
            return "imagem"
        return "desconhecido"


@dataclass(frozen=True)
class EmailCapturado:
    message_id: str
    remetente: str
    assunto: str
    recebido_em: datetime
    corpo_texto: str
    raw: bytes
    thread_id: str | None = None
    remetente_nome: str | None = None
    destinatarios: tuple[str, ...] = ()
    corpo_html: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    anexos: tuple[Anexo, ...] = ()

    @property
    def content_hash(self) -> str:
        """Hash do RFC822 inteiro.

        Complementa o `message_id`: pega o caso do mesmo e-mail reenviado por um sistema
        que gera um Message-ID novo a cada disparo — comum em régua de cobrança.
        """
        return hashlib.sha256(self.raw).hexdigest()

    @property
    def dominio_remetente(self) -> str:
        _, _, dominio = self.remetente.partition("@")
        return dominio.lower()

    def resumo_para_triagem(self, limite_corpo: int = 4000) -> str:
        """O que a triagem enxerga: cabeçalho, corpo truncado e a lista de anexos.

        Não abre os PDFs de propósito — a triagem existe justamente para decidir se vale
        gastar o modelo caro abrindo os anexos.
        """
        anexos = "\n".join(
            f"  - {a.nome_arquivo} ({a.mime_type}, {a.tamanho / 1024:.0f} KB)"
            for a in self.anexos
        ) or "  (nenhum)"
        corpo = self.corpo_texto[:limite_corpo]
        if len(self.corpo_texto) > limite_corpo:
            corpo += f"\n[... truncado, {len(self.corpo_texto) - limite_corpo} caracteres a mais]"
        return (
            f"De: {self.remetente_nome or ''} <{self.remetente}>\n"
            f"Para: {', '.join(self.destinatarios)}\n"
            f"Data: {self.recebido_em.isoformat()}\n"
            f"Assunto: {self.assunto}\n"
            f"Anexos:\n{anexos}\n"
            f"\n--- corpo ---\n{corpo}"
        )


class MailSource(Protocol):
    """Contrato de qualquer canal de entrada de e-mail."""

    nome: str

    def listar(self, limite: int | None = None, desde: datetime | None = None) -> Iterator[EmailCapturado]:
        ...


# --------------------------------------------------------------------------------------
# Parser RFC822
# --------------------------------------------------------------------------------------


def _decodificar_header(valor: str | None) -> str:
    """Resolve headers codificados (=?UTF-8?B?...?=) sem explodir em charset exótico."""
    if not valor:
        return ""
    try:
        return str(make_header(decode_header(valor))).strip()
    except (UnicodeDecodeError, LookupError, ValueError):
        return valor.strip()


def _texto_da_parte(parte: EmailMessage) -> str:
    """Extrai texto de uma parte, tolerando charset declarado errado.

    E-mail de sistema de cobrança declara charset errado com frequência suficiente para
    valer o fallback: perder um boleto por UnicodeDecodeError seria absurdo.
    """
    try:
        conteudo = parte.get_payload(decode=True)
    except Exception:  # noqa: BLE001 — charset exótico não pode perder o e-mail
        return ""
    if conteudo is None:
        return ""
    for charset in (parte.get_content_charset(), "utf-8", "latin-1"):
        if not charset:
            continue
        try:
            return conteudo.decode(charset)
        except (UnicodeDecodeError, LookupError):
            continue
    return conteudo.decode("utf-8", errors="replace")


_TAG_HTML = re.compile(r"<[^>]+>")
_ESPACOS = re.compile(r"[ \t]+")
_LINHAS_VAZIAS = re.compile(r"\n{3,}")


def html_para_texto(html: str) -> str:
    """Conversão grosseira de HTML para texto.

    Não é um renderizador: só precisa preservar a linha digitável e os números para a
    varredura por regex e para o LLM. Quebras de linha em <br> e </p> importam porque
    uma linha digitável partida no meio ainda precisa ser reconhecível.
    """
    texto = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    texto = re.sub(r"(?i)<br\s*/?>", "\n", texto)
    texto = re.sub(r"(?i)</(p|div|tr|li|h[1-6])>", "\n", texto)
    texto = re.sub(r"(?i)</t[dh]>", "\t", texto)
    texto = _TAG_HTML.sub(" ", texto)
    texto = (
        texto.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    texto = _ESPACOS.sub(" ", texto)
    return _LINHAS_VAZIAS.sub("\n\n", texto).strip()


def _relevante(anexo: Anexo) -> bool:
    """Descarta o que é decoração: logo de assinatura, pixel de rastreio."""
    if anexo.mime_type in _MIME_IGNORADOS:
        return False
    if anexo.e_imagem and anexo.tamanho < _TAMANHO_MINIMO_ANEXO:
        return False
    return anexo.tamanho > 0


def parse_rfc822(raw: bytes, *, message_id: str | None = None, thread_id: str | None = None) -> EmailCapturado:
    """Converte um e-mail cru em `EmailCapturado`."""
    msg: EmailMessage = email.message_from_bytes(raw, policy=email.policy.default)  # type: ignore[assignment]

    remetentes = getaddresses([msg.get("From", "")])
    nome, endereco = remetentes[0] if remetentes else ("", "")
    destinatarios = tuple(
        addr
        for _, addr in getaddresses(
            [msg.get("To", ""), msg.get("Cc", ""), msg.get("Delivered-To", "")]
        )
        if addr
    )

    try:
        recebido = parsedate_to_datetime(msg.get("Date", ""))
    except (TypeError, ValueError):
        recebido = None
    if recebido is None:
        recebido = datetime.now(UTC)
    if recebido.tzinfo is None:
        recebido = recebido.replace(tzinfo=UTC)

    corpo_texto_partes: list[str] = []
    corpo_html_partes: list[str] = []
    anexos: list[Anexo] = []

    for parte in msg.walk():
        if parte.is_multipart():
            continue
        tipo = parte.get_content_type()
        disposicao = (parte.get_content_disposition() or "").lower()
        nome_arquivo = _decodificar_header(parte.get_filename())

        e_anexo = disposicao == "attachment" or bool(nome_arquivo)
        if e_anexo:
            conteudo = parte.get_payload(decode=True) or b""
            anexo = Anexo(
                nome_arquivo=nome_arquivo or f"sem-nome.{tipo.split('/')[-1]}",
                mime_type=tipo,
                conteudo=conteudo,
            )
            if _relevante(anexo):
                anexos.append(anexo)
            continue

        if tipo == "text/plain":
            corpo_texto_partes.append(_texto_da_parte(parte))
        elif tipo == "text/html":
            corpo_html_partes.append(_texto_da_parte(parte))

    corpo_html = "\n".join(p for p in corpo_html_partes if p) or None
    corpo_texto = "\n".join(p for p in corpo_texto_partes if p).strip()
    # Muita cobrança chega só em HTML. Sem esse fallback, a linha digitável no corpo
    # simplesmente não existiria para o pipeline.
    if not corpo_texto and corpo_html:
        corpo_texto = html_para_texto(corpo_html)

    return EmailCapturado(
        message_id=message_id or _decodificar_header(msg.get("Message-ID")) or hashlib.sha256(raw).hexdigest(),
        thread_id=thread_id,
        remetente=endereco.lower(),
        remetente_nome=_decodificar_header(nome) or None,
        destinatarios=destinatarios,
        assunto=_decodificar_header(msg.get("Subject")),
        recebido_em=recebido,
        corpo_texto=corpo_texto,
        corpo_html=corpo_html,
        headers={
            k: _decodificar_header(v)
            for k, v in msg.items()
            if k.lower()
            in {"message-id", "from", "to", "subject", "date", "return-path",
                "reply-to", "list-unsubscribe", "x-mailer", "dkim-signature"}
        },
        anexos=tuple(anexos),
        raw=raw,
    )
