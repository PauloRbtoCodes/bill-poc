"""Testes do parser RFC822 e da fonte .eml.

Os casos aqui são todos coisas que e-mail de cobrança real faz: assunto com acento
codificado em base64, corpo só em HTML, logo de assinatura entrando como anexo, charset
declarado errado.
"""

from datetime import UTC, datetime
from email.message import EmailMessage

import pytest

from billpoc.ingest.base import html_para_texto, parse_rfc822
from billpoc.ingest.eml import EmlSource


def montar_email(
    *,
    remetente: str = "Cobrança ACME <cobranca@acme.com.br>",
    assunto: str = "Boleto de agosto",
    texto: str | None = "Segue o boleto em anexo.",
    html: str | None = None,
    anexos: list[tuple[str, str, bytes]] | None = None,
    data: str = "Mon, 24 Aug 2026 09:12:00 -0300",
) -> bytes:
    msg = EmailMessage()
    msg["From"] = remetente
    msg["To"] = "financeiro.test@gmail.com"
    msg["Subject"] = assunto
    msg["Date"] = data
    msg["Message-ID"] = "<abc123@acme.com.br>"

    if texto is not None:
        msg.set_content(texto)
    if html is not None:
        if texto is None:
            msg.set_content("placeholder")
            msg.clear_content()
            msg.set_content(html, subtype="html")
        else:
            msg.add_alternative(html, subtype="html")

    for nome, tipo, conteudo in anexos or []:
        principal, _, sub = tipo.partition("/")
        msg.add_attachment(conteudo, maintype=principal, subtype=sub, filename=nome)

    return msg.as_bytes()


# ------------------------------------------------------------------------------------
# Cabeçalhos
# ------------------------------------------------------------------------------------


def test_extrai_remetente_assunto_e_data():
    e = parse_rfc822(montar_email())
    assert e.remetente == "cobranca@acme.com.br"
    assert e.remetente_nome == "Cobrança ACME"
    assert e.assunto == "Boleto de agosto"
    assert e.recebido_em == datetime(2026, 8, 24, 12, 12, tzinfo=UTC)
    assert e.dominio_remetente == "acme.com.br"


def test_assunto_codificado_em_base64_e_decodificado():
    """Assunto com acento vem como =?UTF-8?B?...?= — sem decodificar, a triagem lê lixo."""
    raw = montar_email(assunto="=?UTF-8?B?Q29icmFuw6dhIC0gdmVuY2ltZW50byBob2pl?=")
    assert parse_rfc822(raw).assunto == "Cobrança - vencimento hoje"


def test_data_ausente_nao_quebra_a_ingestao():
    """Perder um e-mail por causa de header malformado seria péssimo troco."""
    raw = montar_email().replace(b"Date: Mon, 24 Aug 2026 09:12:00 -0300\n", b"")
    e = parse_rfc822(raw)
    assert e.recebido_em.tzinfo is not None


# ------------------------------------------------------------------------------------
# Corpo
# ------------------------------------------------------------------------------------


def test_corpo_texto_simples():
    e = parse_rfc822(montar_email(texto="Segue o boleto de R$ 1.234,56."))
    assert "R$ 1.234,56" in e.corpo_texto


def test_email_so_em_html_vira_texto():
    """Muita cobrança chega só em HTML. Sem o fallback, o corpo simplesmente sumiria."""
    html = "<html><body><p>Linha digitável:</p><p>34191.79001 01043.510047</p></body></html>"
    e = parse_rfc822(montar_email(texto=None, html=html))
    assert "34191.79001 01043.510047" in e.corpo_texto
    assert e.corpo_html is not None


def test_html_preserva_quebras_que_separam_numeros():
    """Uma linha digitável partida por <br> não pode virar um número colado no seguinte."""
    texto = html_para_texto("<div>Valor: 100,00</div><div>Venc: 15/09/2026</div>")
    assert "100,00" in texto
    assert "15/09/2026" in texto
    assert "100,00Venc" not in texto


def test_html_descarta_script_e_style():
    texto = html_para_texto("<style>.x{color:red}</style><p>Boleto</p><script>x=1</script>")
    assert texto.strip() == "Boleto"


def test_entidades_html_sao_resolvidas():
    assert "R$ 1.234,56" in html_para_texto("<p>R$&nbsp;1.234,56</p>")


# ------------------------------------------------------------------------------------
# Anexos
# ------------------------------------------------------------------------------------


def test_anexo_pdf_e_capturado_com_hash():
    conteudo = b"%PDF-1.7\n" + b"x" * 5000
    e = parse_rfc822(montar_email(anexos=[("boleto.pdf", "application/pdf", conteudo)]))
    assert len(e.anexos) == 1
    anexo = e.anexos[0]
    assert anexo.nome_arquivo == "boleto.pdf"
    assert anexo.e_pdf
    assert anexo.tamanho == len(conteudo)
    assert len(anexo.sha256) == 64


def test_logo_de_assinatura_nao_vira_anexo():
    """Imagem pequena em assinatura corporativa poluiria a triagem sem acrescentar nada."""
    e = parse_rfc822(montar_email(anexos=[("logo.png", "image/png", b"\x89PNG" + b"x" * 200)]))
    assert e.anexos == ()


def test_imagem_grande_e_mantida():
    """Foto de boleto tirada no celular é um caso real e precisa passar."""
    e = parse_rfc822(
        montar_email(anexos=[("foto.jpg", "image/jpeg", b"\xff\xd8" + b"x" * 50_000)])
    )
    assert len(e.anexos) == 1
    assert e.anexos[0].e_imagem


def test_pixel_de_rastreio_e_descartado():
    e = parse_rfc822(montar_email(anexos=[("t.gif", "image/gif", b"GIF89a" + b"x" * 40)]))
    assert e.anexos == ()


@pytest.mark.parametrize(
    ("nome", "tipo", "esperado"),
    [
        ("boleto_agosto.pdf", "application/pdf", "boleto_pdf"),
        ("DANFE_12345.pdf", "application/pdf", "danfe_pdf"),
        ("fatura-2026-08.pdf", "application/pdf", "fatura_pdf"),
        ("NFe35260833000167.xml", "application/xml", "nfe_xml"),
        ("recibo.pdf", "application/pdf", "recibo"),
    ],
)
def test_classificacao_inicial_do_anexo_pelo_nome(nome, tipo, esperado):
    e = parse_rfc822(montar_email(anexos=[(nome, tipo, b"x" * 5000)]))
    assert e.anexos[0].classificar() == esperado


# ------------------------------------------------------------------------------------
# Idempotência
# ------------------------------------------------------------------------------------


def test_content_hash_e_estavel_e_distingue_conteudo():
    a = parse_rfc822(montar_email(texto="Boleto de R$ 100,00"))
    b = parse_rfc822(montar_email(texto="Boleto de R$ 100,00"))
    c = parse_rfc822(montar_email(texto="Boleto de R$ 900,00"))
    assert a.content_hash == b.content_hash
    assert a.content_hash != c.content_hash


def test_anexo_identico_em_emails_diferentes_tem_o_mesmo_sha256():
    """A base do dedup: o mesmo boleto em original e lembrete é um documento só."""
    pdf = b"%PDF-1.7\n" + b"boleto" * 1000
    a = parse_rfc822(montar_email(assunto="Boleto", anexos=[("b.pdf", "application/pdf", pdf)]))
    b = parse_rfc822(
        montar_email(assunto="Lembrete: boleto", anexos=[("b.pdf", "application/pdf", pdf)])
    )
    assert a.anexos[0].sha256 == b.anexos[0].sha256
    assert a.content_hash != b.content_hash


# ------------------------------------------------------------------------------------
# Resumo para a triagem
# ------------------------------------------------------------------------------------


def test_resumo_para_triagem_lista_anexos_sem_abrir_os_pdfs():
    e = parse_rfc822(
        montar_email(anexos=[("boleto.pdf", "application/pdf", b"%PDF" + b"x" * 9000)])
    )
    resumo = e.resumo_para_triagem()
    assert "cobranca@acme.com.br" in resumo
    assert "boleto.pdf" in resumo
    assert "application/pdf" in resumo
    assert "Boleto de agosto" in resumo


def test_resumo_trunca_corpo_gigante():
    e = parse_rfc822(montar_email(texto="x" * 20_000))
    resumo = e.resumo_para_triagem(limite_corpo=1000)
    assert "truncado" in resumo
    assert len(resumo) < 3000


# ------------------------------------------------------------------------------------
# EmlSource
# ------------------------------------------------------------------------------------


def test_eml_source_le_e_ordena_por_data(tmp_path):
    (tmp_path / "b.eml").write_bytes(
        montar_email(assunto="Segundo", data="Tue, 25 Aug 2026 10:00:00 -0300")
    )
    (tmp_path / "a.eml").write_bytes(
        montar_email(assunto="Primeiro", data="Mon, 24 Aug 2026 10:00:00 -0300")
    )
    assuntos = [e.assunto for e in EmlSource(tmp_path).listar()]
    assert assuntos == ["Primeiro", "Segundo"]


def test_eml_source_respeita_limite(tmp_path):
    for i in range(5):
        (tmp_path / f"{i}.eml").write_bytes(
            montar_email(data=f"Mon, {20 + i} Aug 2026 10:00:00 -0300")
        )
    assert len(list(EmlSource(tmp_path).listar(limite=2))) == 2


def test_eml_source_filtra_por_data(tmp_path):
    (tmp_path / "velho.eml").write_bytes(
        montar_email(assunto="Velho", data="Mon, 10 Aug 2026 10:00:00 -0300")
    )
    (tmp_path / "novo.eml").write_bytes(
        montar_email(assunto="Novo", data="Mon, 30 Aug 2026 10:00:00 -0300")
    )
    corte = datetime(2026, 8, 20, tzinfo=UTC)
    assuntos = [e.assunto for e in EmlSource(tmp_path).listar(desde=corte)]
    assert assuntos == ["Novo"]


def test_eml_source_roundtrip_salvar_e_ler(tmp_path):
    origem = parse_rfc822(montar_email(assunto="Cobrança"))
    fonte = EmlSource(tmp_path)
    fonte.salvar(origem)
    lido = next(iter(fonte.listar()))
    assert lido.assunto == origem.assunto
    assert lido.content_hash == origem.content_hash


def test_diretorio_inexistente_da_mensagem_util(tmp_path):
    with pytest.raises(FileNotFoundError, match="billpoc ingest"):
        list(EmlSource(tmp_path / "nao-existe").listar())
