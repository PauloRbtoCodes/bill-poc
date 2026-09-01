"""Orquestração: e-mail cru → conta a pagar estruturada + trilha de auditoria.

Seis etapas, todas registradas em `processing_steps`:

    ingest → triage → extract → validate → enrich → persist

A ordem não é arbitrária. `triage` vem antes de `extract` porque abrir PDF no modelo caro
é o item mais caro do fluxo e a maior parte de uma caixa real é ruído. `validate` vem
depois de `extract` porque só faz sentido conferir o que foi lido. E `persist` vem por
último, numa transação só, porque não pode existir estado em que a conta foi gravada mas
a explicação de como ela nasceu se perdeu.
"""

from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from . import enrich
from .config import Config
from .extract.claude import Extrator, Uso
from .extract.nfe_xml import extrair_de_xml
from .extract.pdf import contar_paginas, protegido_por_senha, texto_de_pdf
from .extract.schemas import (
    CampoCategoria,
    CampoData,
    CampoRecorrencia,
    CampoTexto,
    CampoValor,
    DocumentoExtraido,
    Triagem,
)
from .ingest.base import Anexo, EmailCapturado
from .store.repositories import Repositorio
from .validate.boleto import encontrar_linhas_digitaveis
from .validate.rules import Campo, Conciliacao, Verificacao, conciliar
from .validate.tempo import hoje as hoje_brasil

logger = logging.getLogger(__name__)


@dataclass
class ResultadoEmail:
    """O que aconteceu com um e-mail. É o que a CLI imprime e o que os testes checam."""

    message_id: str
    assunto: str
    remetente: str
    triagem: Triagem | None = None
    payables: list[str] = field(default_factory=list)
    conciliacoes: list[Conciliacao] = field(default_factory=list)
    usos: list[Uso] = field(default_factory=list)
    duplicado: bool = False
    ja_processado: bool = False
    erro: str | None = None

    @property
    def e_ruido(self) -> bool:
        return self.triagem is not None and not self.triagem.e_conta_a_pagar

    @property
    def custo_centavos(self) -> Decimal:
        return sum((u.custo_centavos for u in self.usos), Decimal(0))

    @property
    def faixa(self) -> str | None:
        if not self.conciliacoes:
            return None
        return "revisar" if any(c.faixa == "revisar" for c in self.conciliacoes) else "auto_ok"


class Pipeline:
    def __init__(self, config: Config, repositorio: Repositorio, extrator: Extrator):
        self.config = config
        self.repo = repositorio
        self.extrator = extrator

    # ---------------------------------------------------------------------------------

    def processar(self, email: EmailCapturado, referencia: date | None = None) -> ResultadoEmail:
        hoje = referencia or hoje_brasil()
        resultado = ResultadoEmail(
            message_id=email.message_id, assunto=email.assunto, remetente=email.remetente
        )

        email_id, novo = self.repo.salvar_email(email, self.config.mailbox)
        resultado.ja_processado = not novo
        run_id = self.repo.abrir_run(email_id)
        self.repo.registrar_passo(run_id, "ingest")

        try:
            triagem, uso = self.extrator.triar(email)
            resultado.triagem = triagem
            resultado.usos.append(uso)
            self.repo.registrar_passo(run_id, "triage", uso)
            self.repo.registrar_triagem(run_id, email_id, triagem)

            if not triagem.e_conta_a_pagar:
                # Ruído também é resultado: fica gravado com o motivo, e é reversível
                # em um clique na UI. Sem isso não dá para medir falso negativo.
                self.repo.fechar_run(run_id)
                return resultado

            for anexo in self._documentos(email):
                self._processar_documento(
                    email, anexo, email_id, run_id, resultado, hoje
                )

            self.repo.fechar_run(run_id)

        except Exception as exc:  # noqa: BLE001 — um e-mail ruim não derruba o lote
            resultado.erro = f"{type(exc).__name__}: {exc}"
            logger.error("falha processando %s: %s", email.message_id, traceback.format_exc())
            self.repo.registrar_passo(run_id, "persist", erro=resultado.erro)
            self.repo.fechar_run(run_id, erro=resultado.erro)

        return resultado

    # ---------------------------------------------------------------------------------

    def _documentos(self, email: EmailCapturado) -> list[Anexo | None]:
        """Quais documentos extrair.

        `None` significa "extraia do corpo do e-mail". Fornecedor pequeno manda a linha
        digitável direto no corpo, sem anexo nenhum — ignorar esse caso perderia contas
        reais.

        **Quando há XML da NF-e, os PDFs são ignorados.** O DANFE é a representação
        impressa daquele mesmo XML, não um segundo documento: processar os dois geraria
        duas contas para uma nota só, e a segunda cairia como duplicata — ruído na fila
        do Finance Partner. O XML é a fonte melhor, então ele manda. Imagens continuam
        valendo, porque um e-mail pode trazer a NF-e e a foto de um boleto avulso.
        """
        relevantes = [a for a in email.anexos if a.e_pdf or a.e_xml or a.e_imagem]
        if xmls := [a for a in relevantes if a.e_xml]:
            return xmls + [a for a in relevantes if a.e_imagem]
        return relevantes or [None]

    def _guardar(self, anexo: Anexo) -> str:
        """Grava o anexo em disco, nomeado pelo sha256.

        A UI de revisão mostra o PDF ao lado dos campos extraídos — sem o arquivo, o
        revisor teria que confiar na evidência textual em vez de olhar o documento, que
        é justamente o que se quer evitar. Nomear pelo hash dá dedup de graça: o mesmo
        boleto em três e-mails ocupa espaço uma vez.

        Em produção isso seria um bucket privado com URL assinada, não o disco local.
        """
        destino = self.config.storage_dir / f"{anexo.sha256}{_sufixo(anexo.nome_arquivo)}"
        if not destino.exists():
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(anexo.conteudo)
        return str(destino)

    def _processar_documento(
        self,
        email: EmailCapturado,
        anexo: Anexo | None,
        email_id: str,
        run_id: str,
        resultado: ResultadoEmail,
        hoje: date,
    ) -> None:
        document_id = None
        if anexo is not None:
            document_id = self.repo.salvar_documento(
                email_id,
                anexo,
                contar_paginas(anexo.conteudo) if anexo.e_pdf else None,
                storage_uri=self._guardar(anexo),
            )

        # --- extração -----------------------------------------------------------------
        origem_extracao = "llm"
        if anexo is not None and anexo.e_pdf and protegido_por_senha(anexo.conteudo):
            # Boleto protegido por senha (a senha costuma ser o CPF/CNPJ do pagador).
            # Não dá para ler, mas não pode quebrar o lote nem virar erro no log:
            # registra o que se sabe e manda para revisão com o motivo.
            extraido = _documento_ilegivel(
                f"o PDF {anexo.nome_arquivo!r} está protegido por senha e não pôde "
                "ser lido automaticamente — abra manualmente (a senha costuma ser o "
                "CPF/CNPJ do pagador) e preencha os campos",
                email,
            )
            self.repo.registrar_passo(run_id, "extract", document_id=document_id)
        elif anexo is not None and anexo.e_xml:
            # XML da NF-e é dado estruturado assinado digitalmente. Passar isso por um
            # modelo seria trocar certeza por probabilidade — o parser lê direto, e os
            # campos nascem determinísticos.
            extraido = extrair_de_xml(anexo.conteudo)
            if extraido is None:
                return
            origem_extracao = "nfe_xml"
            self.repo.registrar_passo(run_id, "extract", document_id=document_id)
        else:
            extraido, uso = self.extrator.extrair(email, anexo)
            resultado.usos.append(uso)
            self.repo.registrar_passo(run_id, "extract", uso, document_id=document_id)

        extraido = self._completar_por_varredura(extraido, email, anexo)

        # --- validação ----------------------------------------------------------------
        cnpj_lido = extraido.cnpj.valor
        duplicado_de = self.repo.buscar_duplicata(
            linha_digitavel=_apenas_digitos(extraido.linha_digitavel.valor),
            cnpj=cnpj_lido,
            valor_centavos=extraido.valor.centavos,
            vencimento=extraido.vencimento.valor,
        )

        conciliacao = conciliar(
            extraido,
            resultado.triagem,
            referencia=hoje,
            duplicado_de=duplicado_de,
            origem_extracao=origem_extracao,
        )
        resultado.conciliacoes.append(conciliacao)
        self.repo.registrar_passo(run_id, "validate", document_id=document_id)

        # --- enriquecimento -----------------------------------------------------------
        campo_cnpj = conciliacao.campos.get("cnpj")
        campo_benef = conciliacao.campos.get("beneficiario")
        vendor_id = self.repo.upsert_vendor(
            cnpj=campo_cnpj.valor if campo_cnpj else None,
            razao_social=(campo_benef.valor if campo_benef else None) or "",
            dominio=email.dominio_remetente,
        )
        grupo_id = self._enriquecer(vendor_id, extraido, conciliacao)
        self.repo.registrar_passo(run_id, "enrich", document_id=document_id)

        # --- persistência -------------------------------------------------------------
        payable_id = self.repo.salvar_payable(
            run_id=run_id,
            email_id=email_id,
            document_id=document_id,
            extraido=extraido,
            conciliacao=conciliacao,
            vendor_id=vendor_id,
            duplicado_de=duplicado_de,
            recurrence_group_id=grupo_id,
        )
        self.repo.registrar_passo(run_id, "persist", document_id=document_id)
        resultado.payables.append(payable_id)
        resultado.duplicado = resultado.duplicado or duplicado_de is not None

    # ---------------------------------------------------------------------------------

    def _enriquecer(
        self, vendor_id: str | None, extraido: DocumentoExtraido, conciliacao: Conciliacao
    ) -> str | None:
        """Deixa o histórico do fornecedor sobrepor o palpite do modelo.

        O segundo boleto de um fornecedor deveria ser mais fácil que o primeiro. O modelo
        lê um documento isolado e não tem como saber que esta empresa sempre classificou
        este fornecedor como SOFTWARE, ou que o aluguel vem todo dia 10 — o histórico
        sabe, é determinístico e não custa nada.

        Devolve o id do grupo de recorrência, quando houver.
        """
        if vendor_id is None:
            return None

        valor = conciliacao.campos.get("valor")
        valor_centavos = int(valor.valor * 100) if valor and valor.valor else None
        valores, datas, categoria_confirmada = self.repo.historico_do_fornecedor(vendor_id)

        avaliacao = enrich.avaliar(
            valor_centavos=valor_centavos,
            historico_valores=valores,
            historico_datas=datas,
            categoria_do_fornecedor=categoria_confirmada,
        )

        # Categoria confirmada por humano vence a sugestão do modelo. Ele viu um PDF;
        # quem confirmou conhece o plano de contas do cliente.
        if avaliacao.categoria:
            conciliacao.campos["categoria"] = Campo(
                nome="categoria",
                valor=avaliacao.categoria,
                texto=avaliacao.categoria,
                origem="historico",
                confianca=1.0,
                evidencia=f"categoria já definida para este fornecedor "
                f"({avaliacao.ocorrencias} cobrança(s) no histórico)",
            )

        grupo_id = None
        if avaliacao.recorrencia == "recorrente":
            conciliacao.campos["recorrencia"] = Campo(
                nome="recorrencia",
                valor="recorrente",
                texto="recorrente",
                origem="historico",
                confianca=1.0,
                evidencia=f"{avaliacao.ocorrencias} cobranças anteriores deste fornecedor "
                f"em cadência {avaliacao.cadencia}",
            )
            grupo_id = self.repo.registrar_recorrencia(
                vendor_id,
                descricao=extraido.descricao,
                cadencia=avaliacao.cadencia or "mensal",
                valor_esperado=avaliacao.valor_medio_centavos,
            )

        # Valor fora do padrão não bloqueia — só avisa. "Esse aluguel veio R$ 400 mais
        # caro" é a pergunta que um analista humano faria, e é dele a decisão.
        if avaliacao.valor_fora_do_padrao:
            conciliacao.verificacoes.append(
                Verificacao(
                    nome="valor_fora_do_padrao",
                    passou=False,
                    severidade="alerta",
                    esperado=f"~R$ {Decimal(avaliacao.valor_medio_centavos) / 100:.2f}",
                    encontrado=f"R$ {Decimal(valor_centavos) / 100:.2f}",
                    mensagem=avaliacao.descricao_variacao(),
                )
            )

        return grupo_id

    def _completar_por_varredura(
        self, extraido: DocumentoExtraido, email: EmailCapturado, anexo: Anexo | None
    ) -> DocumentoExtraido:
        """Procura a linha digitável no texto, quando o modelo não a devolveu.

        Este é o melhor caminho possível para um boleto: a linha vem do texto do PDF por
        regex, validada pelos dígitos verificadores, sem ninguém ter transcrito nada.
        Valor e vencimento passam a sair de aritmética sobre um dado que o modelo nem
        precisou ler.

        Só aceita quando a varredura encontra **exatamente uma** linha válida. Duas
        significam boleto parcelado ou segunda via no mesmo documento, e escolher uma
        seria chutar — nesse caso o campo fica em branco e o humano decide.
        """
        if extraido.linha_digitavel.valor:
            return extraido

        texto = email.corpo_texto
        origem = "corpo do e-mail"
        if anexo is not None and anexo.e_pdf and (pdf_texto := texto_de_pdf(anexo.conteudo)):
            texto = pdf_texto
            origem = f"texto do PDF {anexo.nome_arquivo}"

        achados = encontrar_linhas_digitaveis(texto)
        if len(achados) != 1:
            return extraido

        return extraido.model_copy(
            update={
                "linha_digitavel": CampoTexto(
                    valor=achados[0].linha_digitavel,
                    confianca=1.0,
                    evidencia=f"encontrada por varredura no {origem}, "
                    "com dígitos verificadores conferidos",
                )
            }
        )


def _documento_ilegivel(motivo: str, email: EmailCapturado | None = None) -> DocumentoExtraido:
    """Um DocumentoExtraido vazio, com o motivo em `observacoes`.

    Quase todo campo fica em branco com confiança 0 — a política então manda para revisão
    por falta de valor e de vencimento, que é o correto quando não há como ler o documento.

    A exceção é o beneficiário: o nome de quem enviou o e-mail é evidência de quem está
    cobrando. Fraca, e marcada como tal (confiança 0.3), mas melhor que deixar a linha da
    fila sem nome nenhum — o revisor precisa saber de quem é a conta que ele vai abrir.
    """
    vazio = CampoTexto(valor=None, confianca=0.0)
    remetente = (
        (email.encaminhado.remetente_nome if email.encaminhado else email.remetente_nome)
        if email
        else None
    )
    beneficiario = (
        CampoTexto(
            valor=remetente,
            confianca=0.3,
            evidencia=f"nome do remetente do e-mail ({email.remetente_efetivo})" if email else None,
        )
        if remetente
        else vazio
    )
    return DocumentoExtraido(
        tipo_documento="boleto",
        beneficiario=beneficiario,
        cnpj=vazio,
        valor=CampoValor(valor_reais=None, confianca=0.0),
        vencimento=CampoData(data=None, confianca=0.0),
        data_emissao=CampoData(data=None, confianca=0.0),
        linha_digitavel=vazio,
        pix_copia_e_cola=vazio,
        numero_nf=vazio,
        chave_nfe=vazio,
        categoria=CampoCategoria(
            categoria="OUTROS", confianca=0.0, justificativa="documento ilegível"
        ),
        recorrencia=CampoRecorrencia(
            recorrencia="unico", confianca=0.0, justificativa="documento ilegível"
        ),
        descricao="Documento não pôde ser lido automaticamente",
        observacoes=motivo,
    )


def _sufixo(nome_arquivo: str) -> str:
    _, ponto, ext = nome_arquivo.rpartition(".")
    return f".{ext.lower()}" if ponto and len(ext) <= 5 else ""


def _apenas_digitos(texto: str | None) -> str | None:
    if not texto:
        return None
    digitos = "".join(c for c in texto if c.isdigit())
    return digitos or None
