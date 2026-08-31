"""Extração direta do XML da NF-e — o caminho sem LLM.

Quando o fornecedor anexa o XML (e no Brasil ele quase sempre anexa, porque é o
documento fiscal de verdade; o PDF do DANFE é só a representação impressa), passar isso
por um modelo seria trocar certeza por probabilidade. O XML é estruturado, assinado
digitalmente e tem os campos nomeados pela própria SEFAZ.

Todo campo daqui sai com confiança 1.0 e origem `nfe_xml`. A evidência é o caminho da
tag, que é literalmente o endereço do dado no documento fiscal.

O que o XML **não** traz é categoria de despesa e recorrência — isso é julgamento sobre
o negócio do cliente, não dado fiscal. Esses dois saem com confiança baixa e categoria
`OUTROS`, o que os coloca na frente do Finance Partner para decidir. Uma vez decidido
para aquele fornecedor, o histórico responde pelos próximos.
"""

from __future__ import annotations

import logging
from xml.etree import ElementTree

from .schemas import (
    CampoCategoria,
    CampoData,
    CampoRecorrencia,
    CampoTexto,
    CampoValor,
    DocumentoExtraido,
)

logger = logging.getLogger(__name__)

NS = {"nfe": "http://www.portalfiscal.inf.br/nfe"}


def _texto(no, caminho: str) -> str | None:
    if no is None:
        return None
    achado = no.find(caminho, NS)
    return achado.text.strip() if achado is not None and achado.text else None


def _campo(valor: str | None, tag: str) -> CampoTexto:
    return CampoTexto(
        valor=valor,
        confianca=1.0 if valor else 0.0,
        evidencia=f"<{tag}> do XML da NF-e" if valor else None,
    )


def extrair_de_xml(conteudo: bytes) -> DocumentoExtraido | None:
    """Converte um XML de NF-e em `DocumentoExtraido`. None se não for uma NF-e."""
    try:
        raiz = ElementTree.fromstring(conteudo)
    except ElementTree.ParseError as exc:
        logger.warning("XML inválido: %s", exc)
        return None

    inf = raiz.find(".//nfe:infNFe", NS)
    if inf is None:
        logger.info("XML anexado não é uma NF-e (sem infNFe) — ignorando")
        return None

    # O atributo Id vem como "NFe" + os 44 dígitos da chave de acesso.
    chave = (inf.get("Id") or "").removeprefix("NFe") or None

    ide = inf.find("nfe:ide", NS)
    emit = inf.find("nfe:emit", NS)

    numero = _texto(ide, "nfe:nNF")
    emissao = (_texto(ide, "nfe:dhEmi") or _texto(ide, "nfe:dEmi") or "")[:10] or None

    cnpj_emit = _texto(emit, "nfe:CNPJ")
    nome_emit = _texto(emit, "nfe:xNome")

    valor_total = _texto(inf, "nfe:total/nfe:ICMSTot/nfe:vNF")

    # A cobrança da NF-e vem em duplicatas: uma por parcela, cada uma com vencimento e
    # valor próprios. Uma duplicata = pagamento único; várias = carnê, e aí a POC registra
    # a primeira e marca para revisão, porque parcelamento é decisão de quem opera.
    duplicatas = inf.findall("nfe:cobr/nfe:dup", NS)
    vencimento = None
    observacoes = None
    if duplicatas:
        vencimento = _texto(duplicatas[0], "nfe:dVenc")
        if len(duplicatas) > 1:
            parcelas = ", ".join(
                f"{_texto(d, 'nfe:nDup') or '?'}: R$ {_texto(d, 'nfe:vDup')} "
                f"em {_texto(d, 'nfe:dVenc')}"
                for d in duplicatas
            )
            observacoes = (
                f"NF-e parcelada em {len(duplicatas)} duplicatas ({parcelas}). "
                "A POC registrou apenas a primeira parcela."
            )

    return DocumentoExtraido(
        tipo_documento="nota_fiscal",
        beneficiario=_campo(nome_emit, "emit/xNome"),
        cnpj=_campo(cnpj_emit, "emit/CNPJ"),
        valor=CampoValor(
            valor_reais=valor_total,
            confianca=1.0 if valor_total else 0.0,
            evidencia="<total/ICMSTot/vNF> do XML da NF-e" if valor_total else None,
        ),
        vencimento=CampoData(
            data=vencimento,
            confianca=1.0 if vencimento else 0.0,
            evidencia="<cobr/dup/dVenc> do XML da NF-e" if vencimento else None,
        ),
        data_emissao=CampoData(
            data=emissao,
            confianca=1.0 if emissao else 0.0,
            evidencia="<ide/dhEmi> do XML da NF-e" if emissao else None,
        ),
        linha_digitavel=CampoTexto(valor=None, confianca=0.0),
        pix_copia_e_cola=CampoTexto(valor=None, confianca=0.0),
        numero_nf=_campo(numero, "ide/nNF"),
        chave_nfe=_campo(chave, "infNFe/@Id"),
        # Categoria e recorrência não são dado fiscal: são julgamento sobre o negócio.
        # Confiança baixa é honestidade, e coloca isso na mão do Finance Partner.
        categoria=CampoCategoria(
            categoria="OUTROS",
            confianca=0.1,
            justificativa="XML da NF-e não carrega categoria de despesa; "
            "classificar pelo histórico do fornecedor ou manualmente",
        ),
        recorrencia=CampoRecorrencia(
            recorrencia="unico",
            confianca=0.2,
            justificativa="recorrência não é dado da NF-e; inferir do histórico do fornecedor",
        ),
        descricao=(
            f"NF-e {numero or 's/n'} — {nome_emit or 'fornecedor não identificado'}"
        ),
        observacoes=observacoes,
    )
