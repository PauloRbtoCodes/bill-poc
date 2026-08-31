"""Schemas de saída estruturada do LLM.

Três decisões de design aqui, todas sobre lidar com incerteza:

1. **Todo campo carrega sua própria confiança e sua própria evidência.** Um número de
   confiança sem lastro não vale nada — "0.92" não é auditável. Exigir o trecho verbatim
   que sustenta a leitura faz duas coisas: reduz alucinação (o modelo tem que apontar
   onde leu) e dá ao revisor humano algo conferível em dois segundos.

2. **`None` é uma resposta correta.** O prompt instrui explicitamente que deixar em
   branco é melhor que chutar. Um campo vazio cai em revisão; um campo chutado vira um
   pagamento errado.

3. **Valores monetários trafegam como string.** `"1234.56"`, não `1234.56`. Float em
   dinheiro é uma classe inteira de bug que não vale a pena convidar, e a string
   preserva exatamente o que o modelo leu antes de qualquer conversão nossa.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, Field, field_validator

TipoDocumento = Literal[
    "boleto", "nota_fiscal", "fatura", "recibo", "contrato", "cobranca_email", "outro"
]

# Restringe a categorização aos códigos do plano de contas (db/seed.sql).
# O modelo escolhe de uma lista fechada; não inventa categoria.
CategoriaDespesa = Literal[
    "ALUGUEL",
    "UTILIDADES",
    "SOFTWARE",
    "SERVICOS_PJ",
    "FORNECEDORES",
    "IMPOSTOS",
    "FOLHA",
    "MARKETING",
    "VIAGENS",
    "FINANCEIRO",
    "OUTROS",
]


class CampoTexto(BaseModel):
    """Campo textual com proveniência."""

    valor: str | None = Field(
        description="O valor lido, ou null se não estiver legível no documento."
    )
    confianca: float = Field(
        ge=0, le=1, description="0 a 1. Use abaixo de 0.7 quando houver qualquer dúvida."
    )
    evidencia: str | None = Field(
        default=None,
        description="Trecho verbatim do documento onde este valor aparece. Não parafraseie.",
    )


class CampoValor(BaseModel):
    """Valor monetário. String para não passar dinheiro por float."""

    valor_reais: str | None = Field(
        description='Valor em reais como string, ex: "1234.56". Ponto decimal, sem "R$" '
        "e sem separador de milhar. null se não estiver legível."
    )
    confianca: float = Field(ge=0, le=1)
    evidencia: str | None = Field(
        default=None, description="Trecho verbatim onde o valor aparece."
    )

    @field_validator("valor_reais")
    @classmethod
    def _limpar(cls, v: str | None) -> str | None:
        """Aceita o que o modelo eventualmente devolver em formato brasileiro."""
        if v is None:
            return None
        v = v.strip().replace("R$", "").replace(" ", "")
        if not v:
            return None
        # "1.234,56" -> "1234.56"
        if "," in v:
            v = v.replace(".", "").replace(",", ".")
        return v

    @property
    def decimal(self) -> Decimal | None:
        if self.valor_reais is None:
            return None
        try:
            return Decimal(self.valor_reais)
        except InvalidOperation:
            return None

    @property
    def centavos(self) -> int | None:
        d = self.decimal
        return int(d * 100) if d is not None else None


class CampoData(BaseModel):
    """Data em ISO. Formato explícito porque dd/mm x mm/dd é erro caro num vencimento."""

    data: str | None = Field(
        description='Data no formato ISO "AAAA-MM-DD". null se não estiver legível.'
    )
    confianca: float = Field(ge=0, le=1)
    evidencia: str | None = Field(
        default=None, description="Trecho verbatim onde a data aparece."
    )

    @property
    def valor(self) -> date | None:
        if not self.data:
            return None
        try:
            return date.fromisoformat(self.data.strip())
        except ValueError:
            return None


class CampoCategoria(BaseModel):
    categoria: CategoriaDespesa
    confianca: float = Field(ge=0, le=1)
    justificativa: str = Field(description="Uma frase sobre por que esta categoria.")


class CampoRecorrencia(BaseModel):
    recorrencia: Literal["unico", "recorrente"]
    confianca: float = Field(ge=0, le=1)
    justificativa: str = Field(
        description="Indícios de recorrência: menção a mensalidade, competência, "
        "número de parcela, assinatura, contrato contínuo."
    )


# --------------------------------------------------------------------------------------
# Triagem
# --------------------------------------------------------------------------------------


class Triagem(BaseModel):
    """Primeira etapa: isto é uma conta a pagar, ou é ruído?

    Roda num modelo barato sobre remetente, assunto, corpo e nomes de anexo — sem abrir
    os PDFs. Serve para não gastar o modelo caro em newsletter e confirmação de cadastro.
    """

    e_conta_a_pagar: bool = Field(
        description="true somente se o e-mail representa uma obrigação de pagamento "
        "desta empresa. Cobrança recebida de fornecedor: true. Nota fiscal emitida "
        "por nós para um cliente, extrato, newsletter, marketing, confirmação de "
        "pagamento já feito, aviso de recebimento: false."
    )
    confianca: float = Field(ge=0, le=1)
    tipo_documento: TipoDocumento
    justificativa: str = Field(
        description="Uma ou duas frases. Em caso de false, diga o que é o e-mail."
    )
    anexos_relevantes: list[str] = Field(
        default_factory=list,
        description="Nomes dos anexos que provavelmente contêm a cobrança.",
    )


# --------------------------------------------------------------------------------------
# Extração
# --------------------------------------------------------------------------------------


class DocumentoExtraido(BaseModel):
    """Os campos que o desafio pede, cada um com proveniência.

    Campos que também aparecem codificados no código de barras ou na chave da NF-e
    (valor, vencimento, CNPJ, nº da NF) serão conferidos contra a aritmética depois.
    Divergência não é descartada em silêncio: vira conflito explícito na fila de revisão.
    """

    tipo_documento: TipoDocumento

    beneficiario: CampoTexto = Field(
        description="Razão social de quem recebe o pagamento — o cedente/beneficiário "
        "do boleto ou o emitente da nota. Não confunda com o sacado/pagador, que "
        "somos nós."
    )
    cnpj: CampoTexto = Field(
        description="CNPJ do beneficiário, só os dígitos. Pode ser alfanumérico "
        "(formato novo desde jul/2026). Não use o CNPJ do pagador."
    )
    valor: CampoValor = Field(
        description="Valor total a pagar. Se houver desconto, multa e juros listados, "
        "use o valor do documento na data de vencimento."
    )
    vencimento: CampoData = Field(description="Data de vencimento do pagamento.")
    data_emissao: CampoData = Field(description="Data de emissão do documento.")

    linha_digitavel: CampoTexto = Field(
        description="Linha digitável do boleto, 47 dígitos (bancário) ou 48 "
        "(arrecadação/concessionária). Transcreva todos os dígitos, sem omitir nenhum. "
        "Pode manter pontos e espaços."
    )
    pix_copia_e_cola: CampoTexto = Field(
        description="Payload Pix Copia e Cola completo, se houver. Começa com 0002."
    )
    numero_nf: CampoTexto = Field(description="Número da nota fiscal.")
    chave_nfe: CampoTexto = Field(description="Chave de acesso da NF-e, 44 dígitos.")

    categoria: CampoCategoria
    recorrencia: CampoRecorrencia

    descricao: str = Field(
        description="Uma linha descrevendo a despesa, como apareceria num extrato. "
        'Ex: "Aluguel sala comercial — competência 08/2026".'
    )
    observacoes: str | None = Field(
        default=None,
        description="Qualquer coisa que um analista financeiro humano precisaria saber: "
        "valor rasurado, duas datas conflitantes no documento, boleto parcelado, "
        "multa já embutida, documento ilegível em parte. Seja específico.",
    )
