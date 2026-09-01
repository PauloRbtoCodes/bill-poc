"""Gera a caixa de demonstração: fixtures .eml + cache de LLM pré-populado.

Existe para o projeto ser executável por qualquer pessoa que clone o repositório, sem
credencial nenhuma — `billpoc semear && billpoc run` funciona offline. E existe para a
demo ao vivo ter cenários escolhidos em vez de sorteados: um conflito de valor, um
comprovante que parece cobrança, um boleto reenviado, um documento ilegível.

As respostas "do LLM" aqui são escritas à mão e gravadas no mesmo cache que a API real
usa. Não é simulação preguiçosa: é o caminho de código idêntico, com a resposta fixada.
Quando a chave da Anthropic estiver disponível, `billpoc run` sobre a caixa real usa
exatamente o mesmo pipeline — só troca quem preenche o cache.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from email.message import EmailMessage
from email.utils import format_datetime

from ..extract.claude import Cache, Uso, _chave_cache
from ..extract.prompts import EXTRACAO, TRIAGEM
from ..extract.schemas import (
    CampoCategoria,
    CampoData,
    CampoRecorrencia,
    CampoTexto,
    CampoValor,
    DocumentoExtraido,
    Triagem,
)
from ..ingest.base import parse_rfc822
from ..validate.boleto import barras_para_linha_bancario, codificar_fator, dv_mod11_barras
from .pdfgen import boleto_pdf, danfe_pdf

MODELO_TRIAGEM = "claude-haiku-4-5"
MODELO_EXTRACAO = "claude-opus-5"

HOJE = date(2026, 8, 31)
NOSSA_EMPRESA = "Cliente Demo Ltda"


# --------------------------------------------------------------------------------------
# Utilitários de construção
# --------------------------------------------------------------------------------------


def linha_digitavel(banco: str, vencimento: date, valor: Decimal, campo_livre: str) -> str:
    """Monta uma linha digitável de 47 dígitos com todos os DVs corretos."""
    fator = codificar_fator(vencimento)
    centavos = int(valor * 100)
    sem_dv = f"{banco}9{fator:04d}{centavos:010d}{campo_livre}"
    dv = dv_mod11_barras(sem_dv)
    return barras_para_linha_bancario(f"{banco}9{dv}{fator:04d}{centavos:010d}{campo_livre}")


def brl(valor: Decimal) -> str:
    inteiro, _, centavos = f"{valor:.2f}".partition(".")
    return f"{int(inteiro):,}".replace(",", ".") + f",{centavos}"


def _campo(valor, conf: float, evidencia: str | None = None) -> CampoTexto:
    return CampoTexto(valor=valor, confianca=conf, evidencia=evidencia)


def _nada() -> CampoTexto:
    return CampoTexto(valor=None, confianca=0.0)


def montar_eml(
    *,
    de: str,
    nome: str,
    assunto: str,
    corpo: str,
    quando: datetime,
    anexos: list[tuple[str, str, bytes]] | None = None,
) -> bytes:
    msg = EmailMessage()
    msg["From"] = f"{nome} <{de}>"
    msg["To"] = "financeiro.test@gmail.com"
    msg["Subject"] = assunto
    msg["Date"] = format_datetime(quando)
    msg["Message-ID"] = f"<{abs(hash((de, assunto, quando))):x}@demo.billpoc>"
    msg.set_content(corpo)
    for nome_arquivo, tipo, conteudo in anexos or []:
        principal, _, sub = tipo.partition("/")
        msg.add_attachment(conteudo, maintype=principal, subtype=sub, filename=nome_arquivo)
    return msg.as_bytes()


@dataclass
class Cenario:
    """Um e-mail de demonstração com as respostas de LLM que ele deve produzir."""

    nome: str
    raw: bytes
    triagem: Triagem
    extracao: DocumentoExtraido | None = None
    explicacao: str = ""


# --------------------------------------------------------------------------------------
# Cenários
# --------------------------------------------------------------------------------------


def _cenarios() -> list[Cenario]:
    cenarios: list[Cenario] = []
    quando = datetime(2026, 8, 20, 9, 14, tzinfo=None).astimezone()

    def proximo(dias: int) -> datetime:
        return quando + timedelta(days=dias, hours=dias % 7)

    # ---- 1. Boleto limpo: tudo bate ---------------------------------------------------
    venc1, valor1 = date(2026, 9, 15), Decimal("1234.56")
    ld1 = linha_digitavel("341", venc1, valor1, "1790001043510049102015000")
    pdf1 = boleto_pdf(
        beneficiario="ACME SERVICOS DE TECNOLOGIA LTDA",
        cnpj="33.000.167/0001-01",
        sacado=NOSSA_EMPRESA,
        valor=brl(valor1),
        vencimento="15/09/2026",
        linha_digitavel=ld1,
        documento="2026-0812",
        descricao="Consultoria tecnica agosto/2026",
    )
    cenarios.append(
        Cenario(
            nome="boleto-limpo",
            explicacao="Caminho feliz: o modelo lê o mesmo que o código de barras diz.",
            raw=montar_eml(
                de="financeiro@acmetecnologia.com.br",
                nome="ACME Tecnologia",
                assunto="Boleto referente a agosto/2026 - vencimento 15/09",
                corpo=(
                    "Prezados,\n\nSegue em anexo o boleto referente aos serviços de "
                    "consultoria prestados em agosto/2026.\n\n"
                    f"Valor: R$ {brl(valor1)}\nVencimento: 15/09/2026\n\n"
                    "Atenciosamente,\nFinanceiro ACME"
                ),
                quando=proximo(0),
                anexos=[("boleto_acme_082026.pdf", "application/pdf", pdf1)],
            ),
            triagem=Triagem(
                e_conta_a_pagar=True,
                confianca=0.98,
                tipo_documento="boleto",
                justificativa="Boleto de fornecedor em anexo, com valor e vencimento no corpo.",
                anexos_relevantes=["boleto_acme_082026.pdf"],
            ),
            extracao=DocumentoExtraido(
                tipo_documento="boleto",
                beneficiario=_campo("ACME SERVICOS DE TECNOLOGIA LTDA", 0.97,
                                    "Beneficiario ACME SERVICOS DE TECNOLOGIA LTDA"),
                cnpj=_campo("33000167000101", 0.96, "CNPJ: 33.000.167/0001-01"),
                valor=CampoValor(valor_reais="1234.56", confianca=0.95,
                                 evidencia="Valor do documento R$ 1.234,56"),
                vencimento=CampoData(data="2026-09-15", confianca=0.96,
                                     evidencia="Vencimento 15/09/2026"),
                data_emissao=CampoData(data=None, confianca=0.0),
                linha_digitavel=_campo(ld1, 0.94, ld1),
                pix_copia_e_cola=_nada(),
                numero_nf=_campo("2026-0812", 0.9, "Numero do documento: 2026-0812"),
                chave_nfe=_nada(),
                categoria=CampoCategoria(categoria="SERVICOS_PJ", confianca=0.88,
                                         justificativa="Consultoria técnica prestada por PJ."),
                recorrencia=CampoRecorrencia(recorrencia="recorrente", confianca=0.72,
                                             justificativa="Menção a competência mensal (agosto/2026)."),
                descricao="Consultoria técnica — competência agosto/2026",
            ),
        )
    )

    # ---- 2. Divergência de valor: o cenário que a POC existe para pegar ----------------
    venc2, valor_real = date(2026, 9, 10), Decimal("9870.00")
    ld2 = linha_digitavel("237", venc2, valor_real, "3812860007827136950000633")
    pdf2 = boleto_pdf(
        beneficiario="NORTE LOGISTICA E TRANSPORTES LTDA",
        cnpj="60.746.948/0001-12",
        sacado=NOSSA_EMPRESA,
        valor=brl(valor_real),
        vencimento="10/09/2026",
        linha_digitavel=ld2,
        documento="NF 4471",
        descricao="Frete e armazenagem agosto/2026",
    )
    cenarios.append(
        Cenario(
            nome="divergencia-valor",
            explicacao=(
                "O modelo lê R$ 987,00; o código de barras diz R$ 9.870,00. "
                "O sistema grava o valor da aritmética e manda para revisão com o conflito."
            ),
            raw=montar_eml(
                de="cobranca@nortelogistica.com.br",
                nome="Norte Logistica",
                assunto="Cobranca NF 4471 - frete agosto",
                corpo=(
                    "Olá,\n\nSegue boleto da NF 4471, referente a frete e armazenagem "
                    "de agosto.\n\nQualquer dúvida estamos à disposição.\n\nNorte Logística"
                ),
                quando=proximo(1),
                anexos=[("boleto_nf4471.pdf", "application/pdf", pdf2)],
            ),
            triagem=Triagem(
                e_conta_a_pagar=True,
                confianca=0.96,
                tipo_documento="boleto",
                justificativa="Cobrança de fornecedor de logística referente a nota fiscal.",
                anexos_relevantes=["boleto_nf4471.pdf"],
            ),
            extracao=DocumentoExtraido(
                tipo_documento="boleto",
                beneficiario=_campo("NORTE LOGISTICA E TRANSPORTES LTDA", 0.95,
                                    "NORTE LOGISTICA E TRANSPORTES LTDA"),
                cnpj=_campo("60746948000112", 0.94, "CNPJ: 60.746.948/0001-12"),
                # A leitura errada: uma casa decimal a menos.
                valor=CampoValor(valor_reais="987.00", confianca=0.81,
                                 evidencia="R$ 9.870,00"),
                vencimento=CampoData(data="2026-09-10", confianca=0.93,
                                     evidencia="Vencimento 10/09/2026"),
                data_emissao=CampoData(data=None, confianca=0.0),
                linha_digitavel=_campo(ld2, 0.93, ld2),
                pix_copia_e_cola=_nada(),
                numero_nf=_campo("4471", 0.88, "Numero do documento: NF 4471"),
                chave_nfe=_nada(),
                categoria=CampoCategoria(categoria="FORNECEDORES", confianca=0.8,
                                         justificativa="Frete e armazenagem de insumos."),
                recorrencia=CampoRecorrencia(recorrencia="unico", confianca=0.7,
                                             justificativa="Cobrança vinculada a uma NF específica."),
                descricao="Frete e armazenagem — NF 4471",
            ),
        )
    )

    # ---- 3. NF-e com XML: caminho sem LLM ---------------------------------------------
    chave3 = _chave_nfe("35", 26, 8, "00000000000191", 1, 88213)
    xml3 = _xml_nfe(
        chave=chave3,
        emitente="ALFA DISTRIBUIDORA DE MATERIAIS SA",
        cnpj="00000000000191",
        numero="88213",
        emissao="2026-08-22T14:03:00-03:00",
        valor="4560.90",
        vencimento="2026-09-21",
    )
    danfe3 = danfe_pdf(
        emitente="ALFA DISTRIBUIDORA DE MATERIAIS SA",
        cnpj="00.000.000/0001-91",
        numero="88213",
        chave=chave3,
        valor="4.560,90",
        emissao="22/08/2026",
        vencimento="21/09/2026",
    )
    cenarios.append(
        Cenario(
            nome="nfe-xml",
            explicacao=(
                "XML da NF-e anexado: os campos saem do documento fiscal por parser, "
                "com confiança 1.0 e zero chamada ao modelo caro."
            ),
            raw=montar_eml(
                de="nfe@alfadistribuidora.com.br",
                nome="Alfa Distribuidora",
                assunto="NF-e 88213 - Alfa Distribuidora",
                corpo=(
                    "Segue NF-e 88213 e respectivo DANFE.\n\n"
                    "Vencimento da duplicata: 21/09/2026\n"
                ),
                quando=proximo(2),
                anexos=[
                    (f"NFe{chave3}.xml", "application/xml", xml3),
                    ("DANFE_88213.pdf", "application/pdf", danfe3),
                ],
            ),
            triagem=Triagem(
                e_conta_a_pagar=True,
                confianca=0.97,
                tipo_documento="nota_fiscal",
                justificativa="NF-e emitida contra a empresa, com XML e DANFE anexados.",
                anexos_relevantes=[f"NFe{chave3}.xml", "DANFE_88213.pdf"],
            ),
            extracao=DocumentoExtraido(
                tipo_documento="nota_fiscal",
                beneficiario=_campo("ALFA DISTRIBUIDORA DE MATERIAIS SA", 0.95,
                                    "Emitente ALFA DISTRIBUIDORA DE MATERIAIS SA"),
                cnpj=_campo("00000000000191", 0.94, "CNPJ: 00.000.000/0001-91"),
                valor=CampoValor(valor_reais="4560.90", confianca=0.93,
                                 evidencia="Valor total da nota R$ 4.560,90"),
                vencimento=CampoData(data="2026-09-21", confianca=0.92,
                                     evidencia="Vencimento da duplicata 21/09/2026"),
                data_emissao=CampoData(data="2026-08-22", confianca=0.9, evidencia="Emissao 22/08/2026"),
                linha_digitavel=_nada(),
                pix_copia_e_cola=_nada(),
                numero_nf=_campo("88213", 0.94, "Numero 88213"),
                chave_nfe=_campo(chave3, 0.9, chave3),
                categoria=CampoCategoria(categoria="FORNECEDORES", confianca=0.82,
                                         justificativa="Distribuidora de materiais."),
                recorrencia=CampoRecorrencia(recorrencia="unico", confianca=0.75,
                                             justificativa="Compra pontual de materiais."),
                descricao="Materiais — NF-e 88213",
            ),
        )
    )

    # ---- 4. Ruído: newsletter ----------------------------------------------------------
    cenarios.append(
        Cenario(
            nome="ruido-newsletter",
            explicacao="Ruído óbvio. A triagem barata resolve sem abrir o modelo caro.",
            raw=montar_eml(
                de="news@contabilidadehoje.com.br",
                nome="Contabilidade Hoje",
                assunto="As 7 mudancas tributarias que voce precisa conhecer",
                corpo=(
                    "Confira nosso artigo da semana sobre a reforma tributária.\n\n"
                    "Leia mais no blog.\n\nPara cancelar a inscrição, clique aqui."
                ),
                quando=proximo(3),
            ),
            triagem=Triagem(
                e_conta_a_pagar=False,
                confianca=0.97,
                tipo_documento="outro",
                justificativa=(
                    "Newsletter de conteúdo com link de descadastro. "
                    "Não há documento de cobrança nem obrigação de pagamento."
                ),
            ),
        )
    )

    # ---- 5. Ruído difícil: comprovante de pagamento -------------------------------------
    cenarios.append(
        Cenario(
            nome="ruido-comprovante",
            explicacao=(
                "Parece cobrança — tem valor, tem fornecedor, tem boleto no assunto — "
                "mas o dinheiro já saiu. Registrar isso seria pagar duas vezes."
            ),
            raw=montar_eml(
                de="naoresponda@bancodemonstracao.com.br",
                nome="Banco Demonstracao",
                assunto="Comprovante de pagamento de boleto - R$ 2.310,00",
                corpo=(
                    "Pagamento efetuado com sucesso.\n\n"
                    "Beneficiário: SUL SERVICOS GERAIS LTDA\n"
                    "Valor: R$ 2.310,00\n"
                    "Data do pagamento: 19/08/2026\n"
                    "Autenticação: 8812.4471.9903.1120\n\n"
                    "Este é um comprovante. Guarde-o para sua segurança."
                ),
                quando=proximo(4),
            ),
            triagem=Triagem(
                e_conta_a_pagar=False,
                confianca=0.93,
                tipo_documento="recibo",
                justificativa=(
                    "Comprovante de pagamento já realizado, emitido pelo banco "
                    '("Pagamento efetuado com sucesso", com código de autenticação). '
                    "O dinheiro já saiu; registrar como conta a pagar geraria pagamento em dobro."
                ),
            ),
        )
    )

    # ---- 6. Duplicata: o mesmo boleto reenviado como lembrete ---------------------------
    cenarios.append(
        Cenario(
            nome="duplicata-lembrete",
            explicacao=(
                "Mesma linha digitável do cenário 1. É o caso real mais comum de "
                "pagamento em dobro: original, lembrete e segunda via na mesma caixa."
            ),
            raw=montar_eml(
                de="financeiro@acmetecnologia.com.br",
                nome="ACME Tecnologia",
                assunto="LEMBRETE: boleto vence em 5 dias",
                corpo=(
                    "Olá,\n\nLembramos que o boleto de agosto/2026 vence em 15/09.\n"
                    f"Valor: R$ {brl(valor1)}\n\n"
                    "Caso já tenha efetuado o pagamento, desconsidere.\n\nACME"
                ),
                quando=proximo(9),
                anexos=[("2via_boleto_acme.pdf", "application/pdf", pdf1)],
            ),
            triagem=Triagem(
                e_conta_a_pagar=True,
                confianca=0.94,
                tipo_documento="boleto",
                justificativa="Lembrete de cobrança com segunda via do boleto em anexo.",
                anexos_relevantes=["2via_boleto_acme.pdf"],
            ),
            extracao=DocumentoExtraido(
                tipo_documento="boleto",
                beneficiario=_campo("ACME SERVICOS DE TECNOLOGIA LTDA", 0.96,
                                    "ACME SERVICOS DE TECNOLOGIA LTDA"),
                cnpj=_campo("33000167000101", 0.95, "CNPJ: 33.000.167/0001-01"),
                valor=CampoValor(valor_reais="1234.56", confianca=0.94, evidencia="R$ 1.234,56"),
                vencimento=CampoData(data="2026-09-15", confianca=0.95, evidencia="15/09/2026"),
                data_emissao=CampoData(data=None, confianca=0.0),
                linha_digitavel=_campo(ld1, 0.93, ld1),
                pix_copia_e_cola=_nada(),
                numero_nf=_campo("2026-0812", 0.88, "2026-0812"),
                chave_nfe=_nada(),
                categoria=CampoCategoria(categoria="SERVICOS_PJ", confianca=0.86,
                                         justificativa="Mesma consultoria do boleto original."),
                recorrencia=CampoRecorrencia(recorrencia="recorrente", confianca=0.7,
                                             justificativa="Competência mensal."),
                descricao="Consultoria técnica — competência agosto/2026 (2ª via)",
            ),
        )
    )

    # ---- 7. Conta de energia: arrecadação, sem vencimento no código de barras ------------
    valor7 = Decimal("1876.43")
    ld7 = _linha_arrecadacao(valor7)
    pdf7 = boleto_pdf(
        beneficiario="COMPANHIA DE ENERGIA DEMONSTRACAO",
        cnpj="12.345.678/0001-95",
        sacado=NOSSA_EMPRESA,
        valor=brl(valor7),
        vencimento="05/09/2026",
        linha_digitavel=ld7,
        documento="UC 7781234",
        descricao="Fatura de energia eletrica 08/2026",
    )
    cenarios.append(
        Cenario(
            nome="arrecadacao-energia",
            explicacao=(
                "Boleto de concessionária: o código de barras confirma o valor, mas "
                "não carrega vencimento. O sistema sabe que não pode conferir a data."
            ),
            raw=montar_eml(
                de="faturas@energiademonstracao.com.br",
                nome="Energia Demonstracao",
                assunto="Sua fatura de energia esta disponivel - UC 7781234",
                corpo=(
                    "Sua fatura de agosto está disponível.\n\n"
                    f"Total a pagar: R$ {brl(valor7)}\nVencimento: 05/09/2026\n"
                    "Unidade consumidora: 7781234\n"
                ),
                quando=proximo(5),
                anexos=[("fatura_energia_082026.pdf", "application/pdf", pdf7)],
            ),
            triagem=Triagem(
                e_conta_a_pagar=True,
                confianca=0.97,
                tipo_documento="fatura",
                justificativa="Fatura de energia elétrica da unidade consumidora da empresa.",
                anexos_relevantes=["fatura_energia_082026.pdf"],
            ),
            extracao=DocumentoExtraido(
                tipo_documento="fatura",
                beneficiario=_campo("COMPANHIA DE ENERGIA DEMONSTRACAO", 0.96,
                                    "COMPANHIA DE ENERGIA DEMONSTRACAO"),
                cnpj=_campo("12345678000195", 0.93, "CNPJ: 12.345.678/0001-95"),
                valor=CampoValor(valor_reais="1876.43", confianca=0.95, evidencia="R$ 1.876,43"),
                vencimento=CampoData(data="2026-09-05", confianca=0.94,
                                     evidencia="Vencimento: 05/09/2026"),
                data_emissao=CampoData(data=None, confianca=0.0),
                linha_digitavel=_campo(ld7, 0.92, ld7),
                pix_copia_e_cola=_nada(),
                numero_nf=_nada(),
                chave_nfe=_nada(),
                categoria=CampoCategoria(categoria="UTILIDADES", confianca=0.95,
                                         justificativa="Fatura de energia elétrica."),
                recorrencia=CampoRecorrencia(recorrencia="recorrente", confianca=0.94,
                                             justificativa="Conta de consumo mensal."),
                descricao="Energia elétrica — UC 7781234, agosto/2026",
            ),
        )
    )

    # ---- 8. Cobrança só no corpo, sem anexo ---------------------------------------------
    venc8, valor8 = date(2026, 9, 30), Decimal("450.00")
    ld8 = linha_digitavel("033", venc8, valor8, "9001234500067890000112233")
    cenarios.append(
        Cenario(
            nome="linha-no-corpo",
            explicacao=(
                "Fornecedor pequeno manda a linha digitável no corpo, sem anexo. "
                "A varredura acha por regex e valida por DV — o modelo nem precisa ler."
            ),
            raw=montar_eml(
                de="contato@limpezatotal.com.br",
                nome="Limpeza Total ME",
                assunto="Cobranca mensal - setembro",
                corpo=(
                    "Bom dia!\n\nSegue o código do boleto de setembro:\n\n"
                    f"{ld8}\n\n"
                    f"Valor R$ {brl(valor8)}, vencimento 30/09/2026.\n\n"
                    "Obrigado!\nLimpeza Total"
                ),
                quando=proximo(6),
            ),
            triagem=Triagem(
                e_conta_a_pagar=True,
                confianca=0.92,
                tipo_documento="boleto",
                justificativa="Cobrança mensal com linha digitável no corpo do e-mail.",
            ),
            extracao=DocumentoExtraido(
                tipo_documento="boleto",
                beneficiario=_campo("Limpeza Total ME", 0.82, "Limpeza Total"),
                # Sem documento formal, o CNPJ não aparece — e o modelo não inventa.
                cnpj=_nada(),
                valor=CampoValor(valor_reais="450.00", confianca=0.9, evidencia="Valor R$ 450,00"),
                vencimento=CampoData(data="2026-09-30", confianca=0.9,
                                     evidencia="vencimento 30/09/2026"),
                data_emissao=CampoData(data=None, confianca=0.0),
                linha_digitavel=_nada(),  # o modelo não transcreveu; a varredura acha
                pix_copia_e_cola=_nada(),
                numero_nf=_nada(),
                chave_nfe=_nada(),
                categoria=CampoCategoria(categoria="SERVICOS_PJ", confianca=0.8,
                                         justificativa="Serviço de limpeza terceirizado."),
                recorrencia=CampoRecorrencia(recorrencia="recorrente", confianca=0.88,
                                             justificativa='Assunto menciona "cobrança mensal".'),
                descricao="Limpeza — mensalidade setembro/2026",
            ),
        )
    )

    # ---- 8b. O histórico do mesmo fornecedor ---------------------------------------------
    # Três meses anteriores da mesma mensalidade, para o enriquecimento ter o que aprender.
    # Sem histórico, o sistema depende do palpite do modelo sobre recorrência; com ele, a
    # cadência é um fato aritmético. É o cenário que mostra o produto ficando melhor com
    # o uso, que é a curva que importa num produto que ganha clientes.
    for indice, (mes, venc_hist) in enumerate(
        [(6, date(2026, 6, 30)), (7, date(2026, 7, 30)), (8, date(2026, 8, 30))]
    ):
        valor_hist = Decimal("450.00")
        ld_hist = linha_digitavel(
            "033", venc_hist, valor_hist, f"90012345000678900001122{mes:02d}"
        )
        nome_mes = {6: "junho", 7: "julho", 8: "agosto"}[mes]
        cenarios.append(
            Cenario(
                nome=f"historico-limpeza-{mes:02d}",
                explicacao=(
                    f"Mensalidade de {nome_mes} — histórico que faz o fornecedor virar "
                    "recorrente por cadência, não por palpite"
                    if indice == 2
                    else f"Mensalidade de {nome_mes} do mesmo fornecedor"
                ),
                raw=montar_eml(
                    de="contato@limpezatotal.com.br",
                    nome="Limpeza Total ME",
                    assunto=f"Cobranca mensal - {nome_mes}",
                    corpo=(
                        f"Bom dia!\n\nSegue o código do boleto de {nome_mes}:\n\n"
                        f"{ld_hist}\n\n"
                        f"Valor R$ {brl(valor_hist)}, "
                        f"vencimento {venc_hist.strftime('%d/%m/%Y')}.\n\n"
                        "Obrigado!\nLimpeza Total"
                    ),
                    quando=proximo(-90 + mes * 10),
                ),
                triagem=Triagem(
                    e_conta_a_pagar=True,
                    confianca=0.92,
                    tipo_documento="boleto",
                    justificativa="Cobrança mensal com linha digitável no corpo do e-mail.",
                ),
                extracao=DocumentoExtraido(
                    tipo_documento="boleto",
                    beneficiario=_campo("Limpeza Total ME", 0.82, "Limpeza Total"),
                    cnpj=_nada(),
                    valor=CampoValor(valor_reais="450.00", confianca=0.9,
                                     evidencia="Valor R$ 450,00"),
                    vencimento=CampoData(data=venc_hist.isoformat(), confianca=0.9,
                                         evidencia=f"vencimento {venc_hist.strftime('%d/%m/%Y')}"),
                    data_emissao=CampoData(data=None, confianca=0.0),
                    linha_digitavel=_nada(),
                    pix_copia_e_cola=_nada(),
                    numero_nf=_nada(),
                    chave_nfe=_nada(),
                    categoria=CampoCategoria(categoria="SERVICOS_PJ", confianca=0.8,
                                             justificativa="Serviço de limpeza terceirizado."),
                    # O modelo chuta 'unico' aqui: sem histórico ele não tem como saber.
                    # Quem corrige é o enriquecimento, e a origem vira 'historico'.
                    recorrencia=CampoRecorrencia(recorrencia="unico", confianca=0.5,
                                                 justificativa="Sem indício de recorrência no documento."),
                    descricao=f"Limpeza — mensalidade {nome_mes}/2026",
                ),
            )
        )

    # ---- 9. Foto de boleto ilegível ------------------------------------------------------
    cenarios.append(
        Cenario(
            nome="foto-ilegivel",
            explicacao=(
                "Foto tirada no celular, parcialmente ilegível. O modelo declara "
                "confiança baixa e deixa campos em branco — que é a resposta certa."
            ),
            raw=montar_eml(
                de="joao@marcenariasaopedro.com.br",
                nome="Marcenaria Sao Pedro",
                assunto="segue boleto",
                corpo="boleto do serviço, qualquer coisa me chama",
                quando=proximo(7),
                anexos=[("IMG_20260827_143201.jpg", "image/jpeg", _foto_falsa())],
            ),
            triagem=Triagem(
                e_conta_a_pagar=True,
                confianca=0.88,
                tipo_documento="boleto",
                justificativa="Foto de boleto anexada por fornecedor de marcenaria.",
                anexos_relevantes=["IMG_20260827_143201.jpg"],
            ),
            extracao=DocumentoExtraido(
                tipo_documento="boleto",
                beneficiario=_campo("MARCENARIA SAO PEDRO", 0.61,
                                    "MARCENARIA SAO P... (parcialmente cortado na foto)"),
                cnpj=_nada(),
                valor=CampoValor(valor_reais="3200.00", confianca=0.44,
                                 evidencia="R$ 3.2?0,00 — terceiro dígito ilegível"),
                vencimento=CampoData(data="2026-09-12", confianca=0.58,
                                     evidencia="12/09/2026, com reflexo sobre o campo"),
                data_emissao=CampoData(data=None, confianca=0.0),
                linha_digitavel=_nada(),
                pix_copia_e_cola=_nada(),
                numero_nf=_nada(),
                chave_nfe=_nada(),
                categoria=CampoCategoria(categoria="FORNECEDORES", confianca=0.6,
                                         justificativa="Serviço de marcenaria."),
                recorrencia=CampoRecorrencia(recorrencia="unico", confianca=0.7,
                                             justificativa="Serviço pontual."),
                descricao="Marcenaria — serviço (documento parcialmente ilegível)",
                observacoes=(
                    "Foto com reflexo e corte na borda direita. A linha digitável não está "
                    "legível em nenhum ponto da imagem e o valor tem um dígito ambíguo "
                    "(pode ser R$ 3.200,00 ou R$ 3.230,00). Recomendo pedir o PDF ao fornecedor."
                ),
            ),
        )
    )

    # ---- 10. Software com Pix -------------------------------------------------------------
    from ..validate.pix import montar as montar_pix

    valor10 = Decimal("890.00")
    pix10 = montar_pix("pagamentos@nuvemsoft.com.br", "NUVEMSOFT LTDA", "SAO PAULO", valor10)
    cenarios.append(
        Cenario(
            nome="assinatura-pix",
            explicacao="Cobrança por Pix: o CRC16 do BR Code confirma o valor, sem boleto.",
            raw=montar_eml(
                de="billing@nuvemsoft.com.br",
                nome="NuvemSoft",
                assunto="Fatura mensal NuvemSoft - setembro/2026",
                corpo=(
                    "Sua assinatura foi renovada.\n\n"
                    f"Valor: R$ {brl(valor10)}\nVencimento: 10/09/2026\n\n"
                    f"Pix Copia e Cola:\n{pix10}\n"
                ),
                quando=proximo(8),
            ),
            triagem=Triagem(
                e_conta_a_pagar=True,
                confianca=0.95,
                tipo_documento="fatura",
                justificativa="Fatura de assinatura de software com Pix para pagamento.",
            ),
            extracao=DocumentoExtraido(
                tipo_documento="fatura",
                beneficiario=_campo("NUVEMSOFT LTDA", 0.93, "NUVEMSOFT LTDA"),
                cnpj=_nada(),
                valor=CampoValor(valor_reais="890.00", confianca=0.93, evidencia="Valor: R$ 890,00"),
                vencimento=CampoData(data="2026-09-10", confianca=0.92,
                                     evidencia="Vencimento: 10/09/2026"),
                data_emissao=CampoData(data=None, confianca=0.0),
                linha_digitavel=_nada(),
                pix_copia_e_cola=_campo(pix10, 0.96, pix10[:40] + "..."),
                numero_nf=_nada(),
                chave_nfe=_nada(),
                categoria=CampoCategoria(categoria="SOFTWARE", confianca=0.96,
                                         justificativa="Assinatura de software em nuvem."),
                recorrencia=CampoRecorrencia(recorrencia="recorrente", confianca=0.95,
                                             justificativa='"Sua assinatura foi renovada" — cobrança mensal.'),
                descricao="Assinatura NuvemSoft — setembro/2026",
            ),
        )
    )

    return cenarios


# --------------------------------------------------------------------------------------
# Auxiliares
# --------------------------------------------------------------------------------------


def _chave_nfe(uf: str, ano: int, mes: int, cnpj: str, serie: int, numero: int) -> str:
    from ..validate.nfe import dv_chave

    base = f"{uf}{ano:02d}{mes:02d}{cnpj}55{serie:03d}{numero:09d}1{'12345678'}"
    return base + str(dv_chave(base))


def _linha_arrecadacao(valor: Decimal) -> str:
    """Boleto de arrecadação de 48 dígitos, identificador 8 (valor em reais, mod 11)."""
    from ..validate.boleto import dv_mod11_arrecadacao

    # produto 8, segmento 1 (concessionária), identificador 8 (valor em reais, DV mod 11)
    centavos = int(valor * 100)
    sem_dv = f"818{centavos:011d}" + "7781234000" + "0" * 19
    sem_dv = sem_dv[:43]
    dv = dv_mod11_arrecadacao(sem_dv)
    barcode = sem_dv[:3] + str(dv) + sem_dv[3:]
    blocos = [barcode[i * 11 : (i + 1) * 11] for i in range(4)]
    return "".join(b + str(dv_mod11_arrecadacao(b)) for b in blocos)


def _xml_nfe(
    *, chave: str, emitente: str, cnpj: str, numero: str, emissao: str, valor: str, vencimento: str
) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">
  <NFe>
    <infNFe Id="NFe{chave}" versao="4.00">
      <ide><cUF>35</cUF><nNF>{numero}</nNF><serie>1</serie><mod>55</mod>
        <dhEmi>{emissao}</dhEmi><tpNF>1</tpNF></ide>
      <emit><CNPJ>{cnpj}</CNPJ><xNome>{emitente}</xNome>
        <enderEmit><xMun>Sao Paulo</xMun><UF>SP</UF></enderEmit></emit>
      <dest><CNPJ>11222333000181</CNPJ><xNome>{NOSSA_EMPRESA}</xNome></dest>
      <total><ICMSTot><vProd>{valor}</vProd><vNF>{valor}</vNF></ICMSTot></total>
      <cobr><fat><nFat>{numero}</nFat><vLiq>{valor}</vLiq></fat>
        <dup><nDup>001</nDup><dVenc>{vencimento}</dVenc><vDup>{valor}</vDup></dup></cobr>
    </infNFe>
  </NFe>
</nfeProc>
""".encode()


def _foto_falsa() -> bytes:
    """JPEG mínimo, só para o anexo ter tamanho e tipo plausíveis.

    Não precisa ser uma imagem de verdade: no modo demo o resultado da extração já está
    no cache, e o que se está exercitando é o pipeline, não a visão do modelo.
    """
    return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 80_000 + b"\xff\xd9"


# --------------------------------------------------------------------------------------
# Semeadura
# --------------------------------------------------------------------------------------


def semear(fixtures_dir, cache_dir, modelo_triagem=MODELO_TRIAGEM, modelo_extracao=MODELO_EXTRACAO):
    """Escreve os .eml e o cache de LLM correspondente. Devolve a lista de cenários."""
    from pathlib import Path

    fixtures = Path(fixtures_dir)
    fixtures.mkdir(parents=True, exist_ok=True)
    cache = Cache(cache_dir)

    cenarios = _cenarios()
    for i, cenario in enumerate(cenarios, start=1):
        (fixtures / f"{i:02d}-{cenario.nome}.eml").write_bytes(cenario.raw)

        email = parse_rfc822(cenario.raw, message_id=f"{i:02d}-{cenario.nome}")

        # Mesma chave que `Extrator.triar` calcularia — o caminho de código é idêntico.
        chave = _chave_cache(
            modelo_triagem, "triagem", TRIAGEM, email.resumo_para_triagem()
        )
        cache.gravar(chave, cenario.triagem, Uso.calcular(modelo_triagem, 780, 140, 640))

        if cenario.extracao is None:
            continue

        # Uma entrada por documento que o pipeline for extrair. XML não passa pelo
        # modelo, então não precisa de cache.
        alvos = [a for a in email.anexos if a.e_pdf or a.e_imagem] or [None]
        for anexo in alvos:
            assinatura = anexo.sha256 if anexo is not None else email.content_hash
            chave = _chave_cache(modelo_extracao, "extracao", EXTRACAO, assinatura)
            cache.gravar(
                chave, cenario.extracao, Uso.calcular(modelo_extracao, 3400, 620, 4100)
            )

    return cenarios
