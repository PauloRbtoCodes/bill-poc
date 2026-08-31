"""Gerador mínimo de PDF, só para as fixtures de demonstração.

Escrito à mão em vez de puxar `reportlab` por dois motivos: é uma dependência a menos
num projeto que alguém vai clonar e rodar, e o PDF precisa ser de verdade — com camada
de texto real — para exercitar tanto a varredura determinística quanto o visualizador
da UI. Um retângulo cinza não serviria.

Não é um gerador de PDF de uso geral: faz uma página A4, fonte Helvetica, linhas de
texto posicionadas. É o suficiente para parecer um boleto.
"""

from __future__ import annotations

A4 = (595, 842)


def _escapar(texto: str) -> str:
    return texto.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _para_latin1(texto: str) -> str:
    """PDF com fonte padrão usa WinAnsi. Acento fora da tabela vira o caractere base."""
    substituicoes = str.maketrans("áàâãäéêëíîïóôõöúûüçñÁÀÂÃÄÉÊÍÓÔÕÚÜÇÑ",
                                 "aaaaaeeeiiioooouuucnAAAAAEEIOOOUUCN")
    return texto.translate(substituicoes)


def gerar_pdf(linhas: list[tuple[int, int, int, str]]) -> bytes:
    """Monta um PDF de uma página.

    `linhas` é uma lista de (x, y, tamanho_da_fonte, texto), com y medido a partir do
    topo — mais intuitivo que a origem do PDF, que fica embaixo.
    """
    largura, altura = A4
    comandos = []
    for x, y, tamanho, texto in linhas:
        comandos.append(
            f"BT /F1 {tamanho} Tf {x} {altura - y} Td ({_escapar(_para_latin1(texto))}) Tj ET"
        )
    stream = "\n".join(comandos).encode("latin-1", errors="replace")

    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {largura} {altura}] "
        f"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>".encode(),
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]

    saida = bytearray(b"%PDF-1.4\n")
    posicoes = []
    for numero, corpo in enumerate(objetos, start=1):
        posicoes.append(len(saida))
        saida += f"{numero} 0 obj\n".encode() + corpo + b"\nendobj\n"

    inicio_xref = len(saida)
    saida += f"xref\n0 {len(objetos) + 1}\n".encode()
    saida += b"0000000000 65535 f \n"
    for posicao in posicoes:
        saida += f"{posicao:010d} 00000 n \n".encode()
    saida += (
        f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\n"
        f"startxref\n{inicio_xref}\n%%EOF\n"
    ).encode()
    return bytes(saida)


def boleto_pdf(
    *,
    beneficiario: str,
    cnpj: str,
    sacado: str,
    valor: str,
    vencimento: str,
    linha_digitavel: str,
    documento: str,
    descricao: str,
) -> bytes:
    """Um PDF com a cara de um boleto bancário."""
    formatada = (
        f"{linha_digitavel[:5]}.{linha_digitavel[5:10]} "
        f"{linha_digitavel[10:15]}.{linha_digitavel[15:21]} "
        f"{linha_digitavel[21:26]}.{linha_digitavel[26:32]} "
        f"{linha_digitavel[32]} {linha_digitavel[33:]}"
    ) if len(linha_digitavel) == 47 else linha_digitavel

    return gerar_pdf([
        (40, 50, 14, "BANCO DEMONSTRACAO S.A."),
        (40, 70, 9, "Recibo do Sacado"),
        (40, 100, 11, formatada),
        (40, 140, 9, "Beneficiario"),
        (40, 155, 11, beneficiario),
        (40, 172, 9, f"CNPJ: {cnpj}"),
        (350, 140, 9, "Vencimento"),
        (350, 155, 12, vencimento),
        (350, 185, 9, "Valor do documento"),
        (350, 200, 14, f"R$ {valor}"),
        (40, 210, 9, "Pagador"),
        (40, 225, 11, sacado),
        (40, 260, 9, f"Numero do documento: {documento}"),
        (40, 278, 9, f"Descricao: {descricao}"),
        (40, 320, 8, "Apos o vencimento, cobrar multa de 2% e juros de 1% ao mes."),
        (40, 340, 8, "Documento gerado para demonstracao. Nao possui valor fiscal."),
    ])


def danfe_pdf(
    *, emitente: str, cnpj: str, numero: str, chave: str, valor: str, emissao: str, vencimento: str
) -> bytes:
    """Um PDF com a cara de um DANFE."""
    chave_agrupada = " ".join(chave[i : i + 4] for i in range(0, 44, 4))
    return gerar_pdf([
        (40, 50, 14, "DANFE"),
        (40, 68, 9, "Documento Auxiliar da Nota Fiscal Eletronica"),
        (40, 95, 9, "Chave de acesso"),
        (40, 110, 9, chave_agrupada),
        (40, 140, 9, "Emitente"),
        (40, 155, 11, emitente),
        (40, 172, 9, f"CNPJ: {cnpj}"),
        (350, 140, 9, "Numero"),
        (350, 155, 12, numero),
        (350, 180, 9, "Emissao"),
        (350, 195, 11, emissao),
        (40, 220, 9, "Valor total da nota"),
        (40, 236, 14, f"R$ {valor}"),
        (350, 220, 9, "Vencimento da duplicata"),
        (350, 236, 12, vencimento),
        (40, 290, 8, "Documento gerado para demonstracao. Nao possui valor fiscal."),
    ])
