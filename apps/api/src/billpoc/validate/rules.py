"""Conciliação entre o que o LLM leu e o que a aritmética prova.

Esta é a política de decisão da POC, e ela mora **em código**, não no prompt. Prompt é
instrução; política de dinheiro é regra. Um modelo pode ser convencido a ignorar uma
instrução — uma função não.

A regra de ouro, para cada campo:

- **Existe fonte determinística e ela concorda com o LLM** → o valor determinístico
  vence, confiança 1.0, segue para a faixa rápida.
- **Existe fonte determinística e ela discorda** → conflito explícito. O valor
  determinístico ainda vence (aritmética > leitura), mas o registro vai para revisão
  humana com os dois valores lado a lado. Nunca se resolve divergência em silêncio.
- **Não existe fonte determinística** → o valor do LLM é aceito, mas marcado como
  não corroborado. Se o documento *deveria* ter código de barras e a linha digitável não
  fechou, isso é bloqueante: significa leitura ruim, não ausência de dado.

`faixa = "auto_ok"` significa apenas "não precisa de atenção especial na fila". **Nada
nesta POC paga sozinho** — todo payable passa por aprovação humana antes de virar
agendamento bancário.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal

from ..extract.schemas import DocumentoExtraido, Triagem
from . import cnpj as cnpj_mod
from . import nfe as nfe_mod
from . import pix as pix_mod
from .boleto import Boleto, BoletoError
from .boleto import decodificar as decodificar_boleto
from .tempo import hoje as hoje_brasil

Origem = Literal[
    "codigo_barras", "nfe_xml", "chave_nfe", "pix", "regex", "llm", "humano", "historico"
]
Severidade = Literal["bloqueante", "alerta", "info"]

# Limiares da política. Ficam aqui, nomeados, para serem discutidos e ajustados —
# e não escondidos como número mágico no meio de um `if`.
LIMIAR_TRIAGEM = 0.85  # abaixo disso, "é uma cobrança?" não está decidido
LIMIAR_CAMPO = 0.70  # abaixo disso, o campo não é confiável nem como palpite
JANELA_VENCIMENTO_PASSADO = timedelta(days=365)
JANELA_VENCIMENTO_FUTURO = timedelta(days=730)


def formatar_brl(valor: Decimal) -> str:
    """R$ 1.234,56 — o conflito aparece na tela do Finance Partner, então formata direito."""
    inteiro, _, centavos = f"{valor:.2f}".partition(".")
    negativo, inteiro = (inteiro[0] == "-", inteiro.lstrip("-"))
    milhares = f"{int(inteiro):,}".replace(",", ".")
    return f"{'-' if negativo else ''}R$ {milhares},{centavos}"


@dataclass(frozen=True)
class Conflito:
    """Divergência entre a leitura do modelo e a decodificação aritmética."""

    valor_llm: str
    valor_deterministico: str
    fonte: Origem

    def __str__(self) -> str:
        return f"modelo leu {self.valor_llm!r}, {self.fonte} diz {self.valor_deterministico!r}"


@dataclass(frozen=True)
class Campo:
    """Um campo conciliado, pronto para virar linha em `field_extractions`."""

    nome: str
    valor: Any
    texto: str | None
    origem: Origem
    confianca: float
    evidencia: str | None = None
    conflito: Conflito | None = None

    @property
    def determinístico(self) -> bool:
        return self.origem in ("codigo_barras", "nfe_xml", "chave_nfe", "pix")


@dataclass(frozen=True)
class Verificacao:
    """Uma linha de `validation_results`."""

    nome: str
    passou: bool
    severidade: Severidade = "bloqueante"
    esperado: str | None = None
    encontrado: str | None = None
    mensagem: str = ""


@dataclass
class Conciliacao:
    campos: dict[str, Campo] = field(default_factory=dict)
    verificacoes: list[Verificacao] = field(default_factory=list)
    boleto: Boleto | None = None
    pix: pix_mod.Pix | None = None
    chave: nfe_mod.ChaveNFe | None = None

    @property
    def bloqueios(self) -> list[Verificacao]:
        return [v for v in self.verificacoes if not v.passou and v.severidade == "bloqueante"]

    @property
    def alertas(self) -> list[Verificacao]:
        return [v for v in self.verificacoes if not v.passou and v.severidade == "alerta"]

    @property
    def conflitos(self) -> list[Campo]:
        return [c for c in self.campos.values() if c.conflito is not None]

    @property
    def faixa(self) -> Literal["auto_ok", "revisar"]:
        return "revisar" if self.bloqueios else "auto_ok"

    @property
    def confianca_geral(self) -> float:
        """O elo mais fraco entre os campos que importam para pagar corretamente.

        Média esconde problema: um CNPJ com confiança 0.2 no meio de nove campos
        perfeitos ainda dá média alta. O mínimo é a leitura honesta.
        """
        criticos = ("valor", "data_vencimento", "cnpj", "beneficiario")
        presentes = [self.campos[n].confianca for n in criticos if n in self.campos]
        return round(min(presentes), 3) if presentes else 0.0

    def motivos(self) -> list[str]:
        """Explicação legível de por que o registro caiu em revisão."""
        return [v.mensagem or v.nome for v in self.bloqueios]


# --------------------------------------------------------------------------------------
# Conciliação de um campo
# --------------------------------------------------------------------------------------


def _conciliar(
    nome: str,
    *,
    llm_valor: Any,
    llm_texto: str | None,
    llm_confianca: float,
    llm_evidencia: str | None,
    det_valor: Any = None,
    det_origem: Origem | None = None,
    origem_llm: Origem = "llm",
    formatar=str,
) -> tuple[Campo, Verificacao | None]:
    """Resolve um campo entre a leitura do modelo e a fonte determinística.

    Devolve o campo resolvido e, quando há fonte determinística, a verificação de
    concordância entre as duas.
    """
    if det_valor is None:
        return (
            Campo(
                nome=nome,
                valor=llm_valor,
                texto=llm_texto,
                origem=origem_llm,
                confianca=llm_confianca,
                evidencia=llm_evidencia,
            ),
            None,
        )

    concorda = llm_valor is not None and llm_valor == det_valor
    conflito = (
        None
        if concorda or llm_valor is None
        else Conflito(
            valor_llm=formatar(llm_valor),
            valor_deterministico=formatar(det_valor),
            fonte=det_origem,
        )
    )

    campo = Campo(
        nome=nome,
        valor=det_valor,  # aritmética vence leitura, sempre
        texto=llm_texto,
        origem=det_origem,
        confianca=1.0,
        evidencia=llm_evidencia,
        conflito=conflito,
    )

    if llm_valor is None:
        verificacao = Verificacao(
            nome=f"{nome}_confere",
            passou=True,
            severidade="info",
            encontrado=formatar(det_valor),
            mensagem=f"{nome} veio de {det_origem}; o modelo não leu este campo",
        )
    else:
        verificacao = Verificacao(
            nome=f"{nome}_confere",
            passou=concorda,
            severidade="bloqueante",
            esperado=formatar(det_valor),
            encontrado=formatar(llm_valor),
            mensagem=(
                f"{nome} conferido contra {det_origem}"
                if concorda
                else f"divergência em {nome}: {conflito}"
            ),
        )
    return campo, verificacao


# --------------------------------------------------------------------------------------
# Decodificação das fontes determinísticas
# --------------------------------------------------------------------------------------


def _decodificar_fontes(
    extraido: DocumentoExtraido, referencia: date | None
) -> tuple[Boleto | None, pix_mod.Pix | None, nfe_mod.ChaveNFe | None, list[Verificacao]]:
    verificacoes: list[Verificacao] = []
    boleto = pix_obj = chave = None

    texto_ld = extraido.linha_digitavel.valor
    if texto_ld:
        try:
            boleto = decodificar_boleto(texto_ld, referencia)
        except BoletoError as exc:
            # O modelo transcreveu algo que não tem forma de boleto: quase sempre dígito
            # faltando. Bloqueia, porque o campo mais importante ficou sem conferência.
            verificacoes.append(
                Verificacao(
                    nome="linha_digitavel_formato",
                    passou=False,
                    severidade="bloqueante",
                    encontrado=texto_ld,
                    mensagem=f"linha digitável ilegível: {exc}",
                )
            )
        else:
            for c in boleto.checks:
                verificacoes.append(
                    Verificacao(
                        nome=f"boleto_{c.nome}",
                        passou=c.passou,
                        severidade="bloqueante" if c.bloqueante else "alerta",
                        esperado=c.esperado,
                        encontrado=c.encontrado,
                        mensagem=c.detalhe,
                    )
                )
            if not boleto.valido:
                # DV não fechou: o dado decodificado não é confiável. Descarta a fonte.
                boleto = None

    if payload := extraido.pix_copia_e_cola.valor:
        try:
            pix_obj = pix_mod.decodificar(payload)
        except pix_mod.PixError as exc:
            verificacoes.append(
                Verificacao(
                    nome="pix_formato",
                    passou=False,
                    severidade="alerta",
                    mensagem=f"Pix Copia e Cola ilegível: {exc}",
                )
            )
        else:
            verificacoes.append(
                Verificacao(
                    nome="pix_crc",
                    passou=pix_obj.crc_valido,
                    severidade="bloqueante",
                    mensagem="CRC16 do Pix Copia e Cola",
                )
            )
            if not pix_obj.crc_valido:
                pix_obj = None

    if texto_chave := extraido.chave_nfe.valor:
        try:
            chave = nfe_mod.decodificar(texto_chave)
        except nfe_mod.ChaveError as exc:
            verificacoes.append(
                Verificacao(
                    nome="chave_nfe_formato",
                    passou=False,
                    severidade="alerta",
                    mensagem=f"chave de acesso ilegível: {exc}",
                )
            )
        else:
            verificacoes.append(
                Verificacao(
                    nome="chave_nfe_dv",
                    passou=chave.valida,
                    severidade="bloqueante",
                    mensagem="DV e sanidade da chave de acesso da NF-e",
                )
            )
            if not chave.valida:
                chave = None

    return boleto, pix_obj, chave, verificacoes


# --------------------------------------------------------------------------------------
# Ponto de entrada
# --------------------------------------------------------------------------------------


def conciliar(
    extraido: DocumentoExtraido,
    triagem: Triagem,
    *,
    referencia: date | None = None,
    duplicado_de: str | None = None,
    origem_extracao: Origem = "llm",
) -> Conciliacao:
    """Concilia a extração com as fontes determinísticas e decide a faixa.

    `origem_extracao` diz de onde vieram os campos antes de qualquer conferência. O
    padrão é `llm` — leitura, que precisa de corroboração. Quando a extração veio do XML
    da NF-e, os campos já nascem determinísticos: são dado fiscal estruturado e assinado,
    não interpretação. Tratá-los como leitura seria jogar fora uma certeza que se tem.
    """
    hoje = referencia or hoje_brasil()
    resultado = Conciliacao()

    boleto, pix_obj, chave, verificacoes = _decodificar_fontes(extraido, hoje)
    resultado.boleto, resultado.pix, resultado.chave = boleto, pix_obj, chave
    resultado.verificacoes.extend(verificacoes)

    def registrar(campo: Campo, verificacao: Verificacao | None) -> None:
        resultado.campos[campo.nome] = campo
        if verificacao is not None:
            resultado.verificacoes.append(verificacao)

    # --- valor -------------------------------------------------------------------------
    det_valor: Decimal | None = None
    origem_valor: Origem | None = None
    if boleto is not None and boleto.valor is not None:
        det_valor, origem_valor = boleto.valor, "codigo_barras"
    elif pix_obj is not None and pix_obj.valor is not None:
        det_valor, origem_valor = pix_obj.valor, "pix"

    registrar(
        *_conciliar(
            "valor",
            llm_valor=extraido.valor.decimal,
            llm_texto=extraido.valor.valor_reais,
            llm_confianca=extraido.valor.confianca,
            llm_evidencia=extraido.valor.evidencia,
            origem_llm=origem_extracao,
            det_valor=det_valor,
            det_origem=origem_valor,
            formatar=formatar_brl,
        )
    )

    # --- vencimento --------------------------------------------------------------------
    det_venc = boleto.vencimento if boleto is not None else None
    registrar(
        *_conciliar(
            "data_vencimento",
            llm_valor=extraido.vencimento.valor,
            llm_texto=extraido.vencimento.data,
            llm_confianca=extraido.vencimento.confianca,
            llm_evidencia=extraido.vencimento.evidencia,
            origem_llm=origem_extracao,
            det_valor=det_venc,
            det_origem="codigo_barras" if det_venc else None,
            formatar=lambda d: d.isoformat(),
        )
    )

    # --- CNPJ --------------------------------------------------------------------------
    # A chave da NF-e contém o CNPJ do emitente. Quando existe, é fonte melhor que a
    # leitura — e ainda cruza com o que o modelo leu.
    det_cnpj = chave.cnpj_emitente if chave is not None else None
    llm_cnpj = cnpj_mod.normalizar(extraido.cnpj.valor) if extraido.cnpj.valor else None
    registrar(
        *_conciliar(
            "cnpj",
            llm_valor=llm_cnpj,
            llm_texto=extraido.cnpj.valor,
            llm_confianca=extraido.cnpj.confianca,
            llm_evidencia=extraido.cnpj.evidencia,
            origem_llm=origem_extracao,
            det_valor=det_cnpj,
            det_origem="chave_nfe" if det_cnpj else None,
            formatar=cnpj_mod.formatar,
        )
    )

    # --- número da NF ------------------------------------------------------------------
    det_numero = str(chave.numero) if chave is not None else None
    llm_numero = extraido.numero_nf.valor.strip().lstrip("0") or None if extraido.numero_nf.valor else None
    registrar(
        *_conciliar(
            "numero_documento",
            llm_valor=llm_numero,
            llm_texto=extraido.numero_nf.valor,
            llm_confianca=extraido.numero_nf.confianca,
            llm_evidencia=extraido.numero_nf.evidencia,
            origem_llm=origem_extracao,
            det_valor=det_numero,
            det_origem="chave_nfe" if det_numero else None,
        )
    )

    # --- campos sem fonte determinística possível ---------------------------------------
    for nome, campo_llm in (
        ("beneficiario", extraido.beneficiario),
        ("data_emissao", extraido.data_emissao),
    ):
        valor = campo_llm.valor if hasattr(campo_llm, "valor") else None
        resultado.campos[nome] = Campo(
            nome=nome,
            valor=valor,
            texto=getattr(campo_llm, "data", None) or (valor if isinstance(valor, str) else None),
            origem=origem_extracao,
            confianca=campo_llm.confianca,
            evidencia=campo_llm.evidencia,
        )

    resultado.campos["categoria"] = Campo(
        nome="categoria",
        valor=extraido.categoria.categoria,
        texto=extraido.categoria.categoria,
        origem="llm",
        confianca=extraido.categoria.confianca,
        evidencia=extraido.categoria.justificativa,
    )
    resultado.campos["recorrencia"] = Campo(
        nome="recorrencia",
        valor=extraido.recorrencia.recorrencia,
        texto=extraido.recorrencia.recorrencia,
        origem="llm",
        confianca=extraido.recorrencia.confianca,
        evidencia=extraido.recorrencia.justificativa,
    )

    resultado.verificacoes.extend(
        _politica(extraido, triagem, resultado, hoje, duplicado_de)
    )
    return resultado


def _politica(
    extraido: DocumentoExtraido,
    triagem: Triagem,
    r: Conciliacao,
    hoje: date,
    duplicado_de: str | None,
) -> list[Verificacao]:
    """As regras que decidem a faixa, separadas da conciliação campo a campo."""
    vs: list[Verificacao] = []

    vs.append(
        Verificacao(
            nome="triagem_confiante",
            passou=triagem.confianca >= LIMIAR_TRIAGEM,
            severidade="bloqueante",
            esperado=f">= {LIMIAR_TRIAGEM}",
            encontrado=f"{triagem.confianca:.2f}",
            mensagem=(
                "a classificação 'é conta a pagar' não está decidida: "
                f"{triagem.justificativa}"
            ),
        )
    )

    vs.append(
        Verificacao(
            nome="nao_duplicado",
            passou=duplicado_de is None,
            severidade="bloqueante",
            encontrado=duplicado_de,
            mensagem=(
                "cobrança idêntica já registrada — provável reenvio, lembrete ou "
                "segunda via do mesmo boleto"
                if duplicado_de
                else "nenhuma cobrança equivalente no histórico"
            ),
        )
    )

    valor = r.campos.get("valor")
    vs.append(
        Verificacao(
            nome="valor_presente",
            passou=valor is not None and valor.valor is not None and valor.valor > 0,
            severidade="bloqueante",
            encontrado=str(valor.valor) if valor else None,
            mensagem="sem valor não há o que pagar",
        )
    )

    venc = r.campos.get("data_vencimento")
    if venc is not None and venc.valor is not None:
        d: date = venc.valor
        vs.append(
            Verificacao(
                nome="vencimento_plausivel",
                passou=(hoje - JANELA_VENCIMENTO_PASSADO) <= d <= (hoje + JANELA_VENCIMENTO_FUTURO),
                severidade="alerta",
                encontrado=d.isoformat(),
                mensagem="vencimento muito fora da janela esperada — confira o ano",
            )
        )
        vs.append(
            Verificacao(
                nome="vencimento_futuro",
                passou=d >= hoje,
                severidade="alerta",
                encontrado=d.isoformat(),
                mensagem="cobrança já vencida: pode haver multa e juros sobre o valor",
            )
        )
    else:
        vs.append(
            Verificacao(
                nome="vencimento_presente",
                passou=False,
                severidade="bloqueante",
                mensagem="sem data de vencimento não dá para agendar",
            )
        )

    cnpj_campo = r.campos.get("cnpj")
    if cnpj_campo is not None and cnpj_campo.valor:
        vs.append(
            Verificacao(
                nome="cnpj_dv",
                passou=cnpj_mod.valido(cnpj_campo.valor),
                severidade="bloqueante",
                encontrado=cnpj_mod.formatar(cnpj_campo.valor),
                mensagem="dígito verificador do CNPJ — falha indica erro de leitura",
            )
        )
    else:
        vs.append(
            Verificacao(
                nome="cnpj_presente",
                passou=False,
                severidade="alerta",
                mensagem="sem CNPJ não dá para conciliar o fornecedor com o histórico",
            )
        )

    # A regra que sustenta a tese: campo de dinheiro sem corroboração aritmética não
    # entra na faixa rápida. Quão bloqueante isso é depende de o documento *dever* ter
    # código de barras — boleto sem linha digitável legível é leitura ruim, não ausência.
    tinha_linha = bool(extraido.linha_digitavel.valor)
    for nome in ("valor", "data_vencimento"):
        campo = r.campos.get(nome)
        if campo is None or campo.determinístico:
            continue
        e_boleto = extraido.tipo_documento == "boleto" or tinha_linha
        vs.append(
            Verificacao(
                nome=f"{nome}_sem_corroboracao",
                passou=False,
                severidade="bloqueante" if e_boleto else "alerta",
                encontrado=str(campo.valor),
                mensagem=(
                    f"{nome} não pôde ser conferido contra código de barras"
                    + (
                        " — o documento é um boleto, então a linha digitável deveria "
                        "estar legível"
                        if e_boleto
                        else " (documento sem instrumento de pagamento codificado)"
                    )
                ),
            )
        )
        vs.append(
            Verificacao(
                nome=f"{nome}_confianca_minima",
                passou=campo.confianca >= LIMIAR_CAMPO,
                severidade="bloqueante",
                esperado=f">= {LIMIAR_CAMPO}",
                encontrado=f"{campo.confianca:.2f}",
                mensagem=f"o próprio modelo não está confiante em {nome}",
            )
        )

    if extraido.observacoes:
        vs.append(
            Verificacao(
                nome="observacoes_do_modelo",
                passou=False,
                severidade="alerta",
                encontrado=extraido.observacoes,
                mensagem="o modelo apontou algo que merece olho humano",
            )
        )

    return vs
