"""Persistência do resultado do pipeline.

Duas coisas que valem notar no design:

**Idempotência real.** Reprocessar a caixa inteira não duplica nada. `email_messages`
tem unique em `gmail_message_id`, `documents` em `sha256` e `payment_instruments` em
`linha_digitavel`. Reprocessamento cria um `processing_run` novo (o histórico dos runs
anteriores fica) mas reaproveita o payable.

**Auditoria escrita na mesma transação do payable.** Não existe um estado em que o
payable foi gravado mas a explicação de como ele nasceu se perdeu. Se a auditoria falha,
o payable não entra.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import psycopg

from ..extract.claude import Uso
from ..extract.schemas import DocumentoExtraido, Triagem
from ..ingest.base import Anexo, EmailCapturado
from ..validate.rules import Conciliacao

PIPELINE_VERSION = "0.1.0"


@dataclass
class Repositorio:
    conexao: psycopg.Connection
    org_id: str

    # ---------------------------------------------------------------------------------
    # Ingestão
    # ---------------------------------------------------------------------------------

    def salvar_email(self, email: EmailCapturado, mailbox: str) -> tuple[str, bool]:
        """Grava o e-mail. Devolve (id, era_novo)."""
        with self.conexao.cursor() as cur:
            cur.execute(
                """
                insert into email_messages (
                    org_id, mailbox, gmail_message_id, thread_id, remetente,
                    remetente_nome, destinatarios, assunto, recebido_em, headers,
                    corpo_texto, corpo_html, content_hash
                ) values (
                    %(org)s, %(mailbox)s, %(mid)s, %(tid)s, %(de)s, %(nome)s,
                    %(para)s, %(assunto)s, %(recebido)s, %(headers)s,
                    %(texto)s, %(html)s, %(hash)s
                )
                on conflict (org_id, gmail_message_id) do nothing
                returning id
                """,
                {
                    "org": self.org_id,
                    "mailbox": mailbox,
                    "mid": email.message_id,
                    "tid": email.thread_id,
                    "de": email.remetente,
                    "nome": email.remetente_nome,
                    "para": list(email.destinatarios),
                    "assunto": email.assunto,
                    "recebido": email.recebido_em,
                    "headers": json.dumps(email.headers, ensure_ascii=False),
                    "texto": email.corpo_texto,
                    "html": email.corpo_html,
                    "hash": email.content_hash,
                },
            )
            if linha := cur.fetchone():
                return str(linha["id"]), True

            cur.execute(
                "select id from email_messages where org_id=%s and gmail_message_id=%s",
                (self.org_id, email.message_id),
            )
            return str(cur.fetchone()["id"]), False

    def salvar_documento(self, email_id: str, anexo: Anexo, paginas: int | None = None) -> str:
        with self.conexao.cursor() as cur:
            cur.execute(
                """
                insert into documents (
                    org_id, email_message_id, nome_arquivo, mime_type,
                    tamanho_bytes, sha256, tipo, paginas
                ) values (%s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (org_id, sha256) do update
                    set nome_arquivo = excluded.nome_arquivo
                returning id
                """,
                (
                    self.org_id,
                    email_id,
                    anexo.nome_arquivo,
                    anexo.mime_type,
                    anexo.tamanho,
                    anexo.sha256,
                    anexo.classificar(),
                    paginas,
                ),
            )
            return str(cur.fetchone()["id"])

    # ---------------------------------------------------------------------------------
    # Execução
    # ---------------------------------------------------------------------------------

    def abrir_run(self, email_id: str) -> str:
        with self.conexao.cursor() as cur:
            cur.execute(
                """
                insert into processing_runs (org_id, email_message_id, pipeline_version)
                values (%s, %s, %s) returning id
                """,
                (self.org_id, email_id, PIPELINE_VERSION),
            )
            return str(cur.fetchone()["id"])

    def fechar_run(self, run_id: str, erro: str | None = None) -> None:
        with self.conexao.cursor() as cur:
            cur.execute(
                """
                update processing_runs
                   set status = %s, erro = %s, finalizado_em = now()
                 where id = %s
                """,
                ("erro" if erro else "concluido", erro, run_id),
            )

    def registrar_passo(
        self,
        run_id: str,
        etapa: str,
        uso: Uso | None = None,
        document_id: str | None = None,
        erro: str | None = None,
    ) -> None:
        with self.conexao.cursor() as cur:
            cur.execute(
                """
                insert into processing_steps (
                    run_id, etapa, document_id, modelo, prompt_version,
                    input_tokens, output_tokens, custo_centavos, latencia_ms,
                    request_id, status, erro
                ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    run_id,
                    etapa,
                    document_id,
                    uso.modelo if uso else None,
                    uso.prompt_version if uso else None,
                    uso.input_tokens if uso else None,
                    uso.output_tokens if uso else None,
                    uso.custo_centavos if uso else None,
                    uso.latencia_ms if uso else None,
                    uso.request_id if uso else None,
                    "erro" if erro else "ok",
                    erro,
                ),
            )

    def registrar_triagem(self, run_id: str, email_id: str, triagem: Triagem) -> None:
        with self.conexao.cursor() as cur:
            cur.execute(
                """
                insert into classifications (
                    run_id, email_message_id, e_conta_a_pagar, confianca,
                    tipo_documento, justificativa
                ) values (%s,%s,%s,%s,%s,%s)
                """,
                (
                    run_id,
                    email_id,
                    triagem.e_conta_a_pagar,
                    triagem.confianca,
                    triagem.tipo_documento,
                    triagem.justificativa,
                ),
            )

    # ---------------------------------------------------------------------------------
    # Fornecedor
    # ---------------------------------------------------------------------------------

    def upsert_vendor(self, cnpj: str | None, razao_social: str, dominio: str) -> str | None:
        """Cria ou atualiza o fornecedor. Sem CNPJ não cria — casaria errado por nome."""
        if not cnpj:
            return None
        with self.conexao.cursor() as cur:
            cur.execute(
                """
                insert into vendors (org_id, cnpj, razao_social, dominios_email)
                values (%s, %s, %s, %s)
                on conflict (org_id, cnpj) do update
                    set razao_social = coalesce(nullif(vendors.razao_social, ''),
                                                excluded.razao_social),
                        dominios_email = (
                            select array_agg(distinct d)
                              from unnest(vendors.dominios_email ||
                                          excluded.dominios_email) d
                        ),
                        atualizado_em = now()
                returning id
                """,
                (self.org_id, cnpj, razao_social or "(sem nome)", [dominio] if dominio else []),
            )
            return str(cur.fetchone()["id"])

    def categoria_id(self, codigo: str) -> str | None:
        with self.conexao.cursor() as cur:
            cur.execute(
                "select id from expense_categories where org_id=%s and codigo=%s",
                (self.org_id, codigo),
            )
            linha = cur.fetchone()
            return str(linha["id"]) if linha else None

    # ---------------------------------------------------------------------------------
    # Duplicata
    # ---------------------------------------------------------------------------------

    def buscar_duplicata(
        self,
        linha_digitavel: str | None,
        cnpj: str | None,
        valor_centavos: int | None,
        vencimento: date | None,
    ) -> str | None:
        """Procura uma cobrança equivalente já registrada.

        Dois critérios, do mais forte para o mais fraco:

        1. **Mesma linha digitável** — é o mesmo boleto, ponto final. Reenvio, lembrete
           ou segunda via.
        2. **Mesmo fornecedor, valor e vencimento** — cobre o caso do fornecedor que
           reemite o boleto com nosso número novo. Mais fraco, então é sinal para
           revisão humana, não para descarte automático.
        """
        with self.conexao.cursor() as cur:
            if linha_digitavel:
                cur.execute(
                    """
                    select p.id from payment_instruments pi
                      join payables p on p.id = pi.payable_id
                     where pi.org_id = %s and pi.linha_digitavel = %s
                       and p.status <> 'duplicado'
                     limit 1
                    """,
                    (self.org_id, linha_digitavel),
                )
                if linha := cur.fetchone():
                    return str(linha["id"])

            if cnpj and valor_centavos and vencimento:
                cur.execute(
                    """
                    select p.id from payables p
                      join vendors v on v.id = p.vendor_id
                     where p.org_id = %s and v.cnpj = %s
                       and p.valor_centavos = %s and p.data_vencimento = %s
                       and p.status <> 'duplicado'
                     limit 1
                    """,
                    (self.org_id, cnpj, valor_centavos, vencimento),
                )
                if linha := cur.fetchone():
                    return str(linha["id"])
        return None

    # ---------------------------------------------------------------------------------
    # Payable + auditoria, na mesma transação
    # ---------------------------------------------------------------------------------

    def salvar_payable(
        self,
        *,
        run_id: str,
        email_id: str,
        document_id: str | None,
        extraido: DocumentoExtraido,
        conciliacao: Conciliacao,
        vendor_id: str | None,
        duplicado_de: str | None,
    ) -> str:
        campos = conciliacao.campos
        valor: Decimal | None = campos["valor"].valor if "valor" in campos else None
        vencimento = campos.get("data_vencimento")
        emissao = campos.get("data_emissao")

        with self.conexao.cursor() as cur:
            cur.execute(
                """
                insert into payables (
                    org_id, vendor_id, tipo_documento, numero_documento, chave_nfe,
                    descricao, valor_centavos, data_emissao, data_vencimento,
                    categoria_id, recorrencia, status, faixa, confianca_geral,
                    email_message_id, document_id, run_id, duplicado_de_id
                ) values (
                    %(org)s, %(vendor)s, %(tipo)s, %(numero)s, %(chave)s,
                    %(descricao)s, %(valor)s, %(emissao)s, %(vencimento)s,
                    %(categoria)s, %(recorrencia)s, %(status)s, %(faixa)s, %(conf)s,
                    %(email)s, %(doc)s, %(run)s, %(dup)s
                ) returning id
                """,
                {
                    "org": self.org_id,
                    "vendor": vendor_id,
                    "tipo": _tipo_payable(extraido.tipo_documento),
                    "numero": campos.get("numero_documento", _vazio()).valor,
                    "chave": conciliacao.chave.chave if conciliacao.chave else None,
                    "descricao": extraido.descricao,
                    "valor": int(valor * 100) if valor is not None else 0,
                    "emissao": _como_data(emissao.valor if emissao else None),
                    "vencimento": _como_data(vencimento.valor if vencimento else None),
                    "categoria": self.categoria_id(extraido.categoria.categoria),
                    "recorrencia": extraido.recorrencia.recorrencia,
                    "status": "duplicado" if duplicado_de else "em_revisao",
                    "faixa": conciliacao.faixa,
                    "conf": conciliacao.confianca_geral,
                    "email": email_id,
                    "doc": document_id,
                    "run": run_id,
                    "dup": duplicado_de,
                },
            )
            payable_id = str(cur.fetchone()["id"])

            self._salvar_instrumentos(cur, payable_id, conciliacao)
            self._salvar_extracoes(cur, run_id, payable_id, document_id, conciliacao)
            self._salvar_validacoes(cur, run_id, payable_id, conciliacao)

        return payable_id

    def _salvar_instrumentos(self, cur, payable_id: str, c: Conciliacao) -> None:
        if c.boleto is not None:
            cur.execute(
                """
                insert into payment_instruments (
                    org_id, payable_id, tipo, linha_digitavel, codigo_barras,
                    decodificado, preferencial
                ) values (%s,%s,%s,%s,%s,%s,true)
                on conflict (org_id, linha_digitavel) where linha_digitavel is not null
                do nothing
                """,
                (
                    self.org_id,
                    payable_id,
                    "boleto_bancario" if c.boleto.tipo == "bancario" else "boleto_arrecadacao",
                    c.boleto.linha_digitavel or None,
                    c.boleto.codigo_barras,
                    json.dumps(
                        {
                            "banco": c.boleto.banco,
                            "fator_vencimento": c.boleto.fator_vencimento,
                            "valor": str(c.boleto.valor) if c.boleto.valor else None,
                            "vencimento": c.boleto.vencimento.isoformat()
                            if c.boleto.vencimento
                            else None,
                            "checks": [
                                {"nome": k.nome, "passou": k.passou, "detalhe": k.detalhe}
                                for k in c.boleto.checks
                            ],
                        },
                        ensure_ascii=False,
                    ),
                ),
            )

        if c.pix is not None:
            cur.execute(
                """
                insert into payment_instruments (
                    org_id, payable_id, tipo, pix_copia_e_cola, decodificado, preferencial
                ) values (%s,%s,'pix',%s,%s,%s)
                """,
                (
                    self.org_id,
                    payable_id,
                    c.pix.payload,
                    json.dumps(
                        {
                            "chave": c.pix.chave,
                            "valor": str(c.pix.valor) if c.pix.valor else None,
                            "beneficiario": c.pix.beneficiario,
                            "crc_valido": c.pix.crc_valido,
                        },
                        ensure_ascii=False,
                    ),
                    c.boleto is None,
                ),
            )

    def _salvar_extracoes(
        self, cur, run_id: str, payable_id: str, document_id: str | None, c: Conciliacao
    ) -> None:
        for campo in c.campos.values():
            cur.execute(
                """
                insert into field_extractions (
                    org_id, run_id, payable_id, document_id, campo, valor_texto,
                    valor_normalizado, origem, confianca, evidencia, vigente
                ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true)
                on conflict (payable_id, campo) where vigente and payable_id is not null
                do nothing
                """,
                (
                    self.org_id,
                    run_id,
                    payable_id,
                    document_id,
                    campo.nome,
                    campo.texto,
                    _texto(campo.valor),
                    campo.origem,
                    campo.confianca,
                    campo.evidencia,
                ),
            )

    def _salvar_validacoes(self, cur, run_id: str, payable_id: str, c: Conciliacao) -> None:
        for v in c.verificacoes:
            cur.execute(
                """
                insert into validation_results (
                    org_id, run_id, payable_id, check_nome, passou,
                    severidade, esperado, encontrado, mensagem
                ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    self.org_id,
                    run_id,
                    payable_id,
                    v.nome,
                    v.passou,
                    v.severidade,
                    v.esperado,
                    v.encontrado,
                    v.mensagem,
                ),
            )

    # ---------------------------------------------------------------------------------
    # Leitura para a UI
    # ---------------------------------------------------------------------------------

    def fila_revisao(self) -> list[dict[str, Any]]:
        with self.conexao.cursor() as cur:
            cur.execute(
                """
                select * from fila_revisao
                 where org_id = %s
                 order by urgente desc, falhas_bloqueantes desc,
                          data_vencimento nulls last
                """,
                (self.org_id,),
            )
            return cur.fetchall()

    def detalhe(self, payable_id: str) -> dict[str, Any] | None:
        with self.conexao.cursor() as cur:
            cur.execute(
                """
                select p.*, v.razao_social as fornecedor, v.cnpj,
                       c.codigo as categoria_codigo,
                       em.assunto as email_assunto, em.remetente as email_remetente,
                       em.recebido_em, em.corpo_texto as email_corpo,
                       d.nome_arquivo, d.tipo as documento_tipo
                  from payables p
                  left join vendors v on v.id = p.vendor_id
                  left join expense_categories c on c.id = p.categoria_id
                  left join email_messages em on em.id = p.email_message_id
                  left join documents d on d.id = p.document_id
                 where p.id = %s and p.org_id = %s
                """,
                (payable_id, self.org_id),
            )
            payable = cur.fetchone()
            if not payable:
                return None

            cur.execute(
                """
                select campo, valor_texto, valor_normalizado, origem, confianca, evidencia
                  from field_extractions
                 where payable_id = %s and vigente
                 order by campo
                """,
                (payable_id,),
            )
            payable["campos"] = cur.fetchall()

            cur.execute(
                """
                select check_nome, passou, severidade, esperado, encontrado, mensagem
                  from validation_results
                 where payable_id = %s
                 order by passou, severidade, check_nome
                """,
                (payable_id,),
            )
            payable["verificacoes"] = cur.fetchall()

            cur.execute(
                "select * from payment_instruments where payable_id = %s "
                "order by preferencial desc",
                (payable_id,),
            )
            payable["instrumentos"] = cur.fetchall()

            cur.execute(
                """
                select acao, campo, valor_anterior, valor_novo, observacao, criado_em
                  from review_actions where payable_id = %s order by criado_em desc
                """,
                (payable_id,),
            )
            payable["historico"] = cur.fetchall()
            return payable

    def agenda(self) -> list[dict[str, Any]]:
        with self.conexao.cursor() as cur:
            cur.execute(
                "select * from agenda_pagamento where org_id = %s "
                "order by data_vencimento nulls last",
                (self.org_id,),
            )
            return cur.fetchall()

    # ---------------------------------------------------------------------------------
    # Ações do Finance Partner
    # ---------------------------------------------------------------------------------

    def registrar_acao(
        self,
        payable_id: str,
        acao: str,
        ator_id: str,
        campo: str | None = None,
        anterior: str | None = None,
        novo: str | None = None,
        observacao: str | None = None,
    ) -> None:
        with self.conexao.cursor() as cur:
            cur.execute(
                """
                insert into review_actions (
                    org_id, payable_id, ator_id, acao, campo,
                    valor_anterior, valor_novo, observacao
                ) values (%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (self.org_id, payable_id, ator_id, acao, campo, anterior, novo, observacao),
            )

    def editar_campo(self, payable_id: str, campo: str, novo_valor: str, ator_id: str) -> None:
        """Correção humana: a linha antiga sai de vigência, uma nova entra como 'humano'.

        Append-only: o valor original continua no banco, com sua origem e sua evidência.
        Dá para reconstruir o que o modelo tinha lido mesmo depois de meia dúzia de
        correções — e é exatamente esse histórico que vira sinal de treino depois.
        """
        with self.conexao.cursor() as cur:
            cur.execute(
                "select valor_normalizado from field_extractions "
                "where payable_id=%s and campo=%s and vigente",
                (payable_id, campo),
            )
            linha = cur.fetchone()
            anterior = linha["valor_normalizado"] if linha else None

            cur.execute(
                "update field_extractions set vigente=false "
                "where payable_id=%s and campo=%s and vigente",
                (payable_id, campo),
            )
            cur.execute(
                """
                insert into field_extractions (
                    org_id, run_id, payable_id, campo, valor_texto, valor_normalizado,
                    origem, confianca, evidencia, vigente
                )
                select %s, pr.id, %s, %s, %s, %s, 'humano', 1.0,
                       'corrigido manualmente na revisão', true
                  from processing_runs pr
                 where pr.email_message_id = (
                           select email_message_id from payables where id = %s)
                 order by pr.iniciado_em desc limit 1
                """,
                (self.org_id, payable_id, campo, novo_valor, novo_valor, payable_id),
            )

            coluna = _COLUNA_PAYABLE.get(campo)
            if coluna:
                cur.execute(
                    f"update payables set {coluna} = %s, atualizado_em = now() "
                    "where id = %s and org_id = %s",
                    (_converter(campo, novo_valor), payable_id, self.org_id),
                )

        self.registrar_acao(
            payable_id, "editar_campo", ator_id, campo=campo, anterior=anterior, novo=novo_valor
        )

    def mudar_status(
        self, payable_id: str, status: str, acao: str, ator_id: str, observacao: str | None = None
    ) -> None:
        with self.conexao.cursor() as cur:
            cur.execute(
                "select status from payables where id=%s and org_id=%s",
                (payable_id, self.org_id),
            )
            atual = (cur.fetchone() or {}).get("status")
            cur.execute(
                "update payables set status=%s, atualizado_em=now() where id=%s and org_id=%s",
                (status, payable_id, self.org_id),
            )
        self.registrar_acao(
            payable_id, acao, ator_id, campo="status", anterior=atual, novo=status,
            observacao=observacao,
        )

    def agendar(
        self,
        payable_id: str,
        data_agendada: date,
        banco: str,
        codigo_confirmacao: str | None,
        ator_id: str,
    ) -> str:
        """Registra que o Finance Partner agendou o pagamento no banco.

        A POC não paga: ela registra que um humano pagou. Esta tabela é a ponte entre o
        sistema e o que aconteceu no internet banking.
        """
        with self.conexao.cursor() as cur:
            cur.execute(
                "select id from payment_instruments where payable_id=%s "
                "order by preferencial desc limit 1",
                (payable_id,),
            )
            linha = cur.fetchone()
            cur.execute(
                """
                insert into payment_schedules (
                    org_id, payable_id, payment_instrument_id, data_agendada,
                    banco, agendado_por, codigo_confirmacao
                ) values (%s,%s,%s,%s,%s,%s,%s) returning id
                """,
                (
                    self.org_id,
                    payable_id,
                    linha["id"] if linha else None,
                    data_agendada,
                    banco,
                    ator_id,
                    codigo_confirmacao,
                ),
            )
            schedule_id = str(cur.fetchone()["id"])
        self.mudar_status(
            payable_id, "agendado", "agendar", ator_id,
            observacao=f"{banco} — {data_agendada.isoformat()}"
            + (f" — protocolo {codigo_confirmacao}" if codigo_confirmacao else ""),
        )
        return schedule_id

    # ---------------------------------------------------------------------------------
    # Relatório
    # ---------------------------------------------------------------------------------

    def relatorio(self) -> dict[str, Any]:
        with self.conexao.cursor() as cur:
            cur.execute(
                """
                select
                    (select count(*) from email_messages where org_id=%(o)s) as emails,
                    (select count(*) from classifications c
                       join processing_runs r on r.id=c.run_id
                      where r.org_id=%(o)s and c.e_conta_a_pagar)              as cobrancas,
                    (select count(*) from classifications c
                       join processing_runs r on r.id=c.run_id
                      where r.org_id=%(o)s and not c.e_conta_a_pagar)          as ruido,
                    (select count(*) from payables where org_id=%(o)s)         as payables,
                    (select count(*) from payables
                      where org_id=%(o)s and faixa='auto_ok')                  as auto_ok,
                    (select count(*) from payables
                      where org_id=%(o)s and status='duplicado')               as duplicados,
                    (select coalesce(sum(valor_centavos),0) from payables
                      where org_id=%(o)s and status <> 'duplicado')            as total_centavos
                """,
                {"o": self.org_id},
            )
            resumo = cur.fetchone()

            cur.execute(
                """
                select ps.etapa, ps.modelo, count(*) as chamadas,
                       coalesce(sum(ps.input_tokens),0)   as input_tokens,
                       coalesce(sum(ps.output_tokens),0)  as output_tokens,
                       coalesce(sum(ps.custo_centavos),0) as custo_centavos,
                       coalesce(round(avg(ps.latencia_ms)),0) as latencia_media_ms
                  from processing_steps ps
                  join processing_runs r on r.id = ps.run_id
                 where r.org_id = %s and ps.modelo is not null
                 group by ps.etapa, ps.modelo
                 order by ps.etapa
                """,
                (self.org_id,),
            )
            resumo["custos"] = cur.fetchall()

            cur.execute(
                """
                select fe.origem, count(*) as campos
                  from field_extractions fe
                 where fe.org_id = %s and fe.vigente
                 group by fe.origem order by count(*) desc
                """,
                (self.org_id,),
            )
            resumo["origens"] = cur.fetchall()

            cur.execute(
                """
                select vr.check_nome, count(*) as falhas
                  from validation_results vr
                 where vr.org_id = %s and not vr.passou and vr.severidade = 'bloqueante'
                 group by vr.check_nome order by count(*) desc limit 10
                """,
                (self.org_id,),
            )
            resumo["bloqueios"] = cur.fetchall()
            return resumo


# --------------------------------------------------------------------------------------

_COLUNA_PAYABLE = {
    "valor": "valor_centavos",
    "data_vencimento": "data_vencimento",
    "data_emissao": "data_emissao",
    "numero_documento": "numero_documento",
    "recorrencia": "recorrencia",
}


def _converter(campo: str, valor: str):
    if campo == "valor":
        return int(Decimal(valor) * 100)
    if campo in ("data_vencimento", "data_emissao"):
        return date.fromisoformat(valor)
    return valor


def _tipo_payable(tipo: str) -> str:
    return {
        "boleto": "boleto",
        "nota_fiscal": "nota_fiscal",
        "fatura": "fatura",
        "recibo": "recibo",
    }.get(tipo, "outro")


def _como_data(valor) -> date | None:
    if isinstance(valor, date):
        return valor
    if isinstance(valor, str):
        try:
            return date.fromisoformat(valor)
        except ValueError:
            return None
    return None


def _texto(valor) -> str | None:
    if valor is None:
        return None
    if isinstance(valor, date):
        return valor.isoformat()
    return str(valor)


class _vazio:
    valor = None
