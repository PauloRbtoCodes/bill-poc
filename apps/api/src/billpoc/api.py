"""API HTTP que serve a UI do Finance Partner.

Fina de propósito: toda a lógica está no `Repositorio`, e cada rota é um verbo do fluxo
de trabalho real — triar, revisar, corrigir, aprovar, agendar. Nenhuma rota faz `update`
genérico em payable: as transições são nomeadas porque cada uma precisa gerar sua linha
em `review_actions`.

    uvicorn billpoc.api:app --reload --port 8000
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .config import USUARIO_FP, carregar
from .store.db import BancoIndisponivel, conectar
from .store.repositories import Repositorio
from .validate.tempo import hoje as hoje_brasil

cfg = carregar()

app = FastAPI(title="billpoc", description="Contas a pagar a partir de e-mails")
# Em produção o front e a API estão no mesmo domínio da Vercel, então CORS não se
# aplica. A liberação é só para o desenvolvimento local, onde são portas diferentes.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _repo():
    """Uma conexão por requisição. Suficiente para a POC; em produção seria um pool."""
    try:
        with conectar(cfg.database_url) as conexao:
            yield Repositorio(conexao, cfg.org_id)
    except BancoIndisponivel as exc:
        raise HTTPException(503, str(exc)) from exc


Repo = Depends(_repo)


# ======================================================================================
# Leitura
# ======================================================================================


@app.get("/api/fila")
def fila(repo: Repositorio = Repo) -> list[dict[str, Any]]:
    """A fila de revisão, já ordenada por urgência e número de bloqueios."""
    return repo.fila_revisao()


@app.get("/api/payables/{payable_id}")
def detalhe(payable_id: str, repo: Repositorio = Repo) -> dict[str, Any]:
    """Tudo sobre uma conta: campos com proveniência, verificações e histórico."""
    if (p := repo.detalhe(payable_id)) is None:
        raise HTTPException(404, "conta não encontrada")
    return p


@app.get("/api/documentos/{document_id}/arquivo")
def arquivo(document_id: str, repo: Repositorio = Repo) -> Response:
    """Serve o PDF original para a revisão lado a lado.

    O revisor precisa ver o documento, não só a evidência textual que o modelo alegou
    ter lido — é o documento que decide um conflito.
    """
    doc = repo.documento(document_id)
    if not doc:
        raise HTTPException(404, "documento não encontrado")

    # inline para renderizar no visualizador, não baixar
    cabecalhos = {"Content-Disposition": f'inline; filename="{doc["nome_arquivo"]}"'}

    if doc["conteudo"]:
        return Response(bytes(doc["conteudo"]), media_type=doc["mime_type"], headers=cabecalhos)

    # Anexos gravados antes de o conteúdo passar a ir para o banco.
    if doc["storage_uri"] and Path(doc["storage_uri"]).exists():
        return FileResponse(doc["storage_uri"], media_type=doc["mime_type"], headers=cabecalhos)

    raise HTTPException(404, "arquivo não disponível")


@app.get("/api/ruido")
def ruido(repo: Repositorio = Repo) -> list[dict[str, Any]]:
    """O que a triagem descartou, com o motivo. Visível para poder ser contestado."""
    return repo.ruido()


@app.post("/api/emails/{email_id}/reclassificar")
def reclassificar(email_id: str, repo: Repositorio = Repo) -> dict[str, Any]:
    """O Finance Partner discorda da triagem: isto era uma cobrança.

    O rótulo corrigido é o que mede falso negativo — o erro caro desta etapa, porque
    uma conta perdida vira multa e ninguém descobre por conta própria.
    """
    repo.reclassificar(email_id, USUARIO_FP)
    return {"ok": True}


@app.get("/api/agenda")
def agenda(repo: Repositorio = Repo) -> list[dict[str, Any]]:
    """Aprovados e ainda não agendados, com a forma de pagamento junto."""
    return repo.agenda()


@app.get("/api/agenda/exportar")
def exportar_agenda(
    formato: str = "csv",
    dias: int | None = None,
    repo: Repositorio = Repo,
) -> Response:
    """Exporta a agenda aprovada para planilha, ERP ou remessa bancária.

    Copiar-e-colar a linha digitável resolve três contas; não resolve trinta. O CNAB é o
    que substitui o agendamento manual conta a conta — sobe no banco e o lote inteiro é
    agendado de uma vez.
    """
    from .exportar import Pagamento, para_cnab240, para_csv, para_erp, sem_linha_digitavel

    linhas = repo.agenda()
    if dias is not None:
        linhas = [x for x in linhas if (x.get("dias_para_vencer") or 999) <= dias]
    pagamentos = [Pagamento.da_agenda(x) for x in linhas]

    hoje = hoje_brasil().isoformat()
    if formato == "csv":
        corpo, nome, tipo = para_csv(pagamentos), f"agenda-{hoje}.csv", "text/csv"
    elif formato == "erp":
        corpo, nome, tipo = para_erp(pagamentos), f"contas-a-pagar-{hoje}.csv", "text/csv"
    elif formato == "cnab":
        corpo = para_cnab240(
            pagamentos, empresa="CLIENTE DEMO LTDA", cnpj_empresa="11222333000181"
        )
        nome, tipo = f"remessa-{hoje}.rem", "text/plain"
    else:
        raise HTTPException(422, f"formato desconhecido: {formato!r} (use csv, erp ou cnab)")

    cabecalhos = {"Content-Disposition": f'attachment; filename="{nome}"'}
    if formato == "cnab" and (fora := sem_linha_digitavel(pagamentos)):
        # Quem não cabe no CNAB não pode sumir em silêncio: a UI avisa quantas contas
        # continuam no fluxo manual.
        cabecalhos["X-Pagamentos-Fora"] = str(len(fora))

    # Latin-1 no CNAB: é o encoding que os bancos esperam no arquivo de remessa.
    dados = corpo.encode("latin-1", errors="replace") if formato == "cnab" else corpo.encode("utf-8-sig")
    return Response(content=dados, media_type=tipo, headers=cabecalhos)


# ======================================================================================
# Sincronização com a caixa
# ======================================================================================


class ResultadoSync(BaseModel):
    processados: int
    restantes: int
    concluido: bool
    ultimo: str | None = None
    faixa: str | None = None
    e_ruido: bool = False
    erro: str | None = None


@app.post("/api/sync")
def sync(lote: int = 1, repo: Repositorio = Repo) -> ResultadoSync:
    """Processa os próximos e-mails ainda não vistos da caixa.

    **Incremental de propósito.** Uma função serverless tem 60 segundos; processar 48
    e-mails com chamadas de LLM leva minutos. Em vez de um endpoint que estoura o
    timeout no meio e deixa estado pela metade, cada chamada processa um lote pequeno e
    devolve quantos faltam — a UI chama de novo até acabar, mostrando progresso.

    O efeito colateral é bom: como cada e-mail é uma transação própria e a ingestão é
    idempotente por `gmail_message_id`, interromper no meio não corrompe nada. Recomeçar
    continua de onde parou.
    """
    from .extract.claude import Extrator
    from .ingest.gmail import GmailSource
    from .pipeline import Pipeline

    if not cfg.tem_gmail:
        raise HTTPException(400, "Gmail não autorizado — defina GMAIL_TOKEN_JSON")
    if not cfg.tem_llm:
        raise HTTPException(400, "sem chave da Anthropic — defina ANTHROPIC_API_KEY")

    origem = GmailSource(cfg.gmail_credentials, cfg.gmail_token, cfg.gmail_query)
    pipeline = Pipeline(
        cfg,
        repo,
        Extrator(
            modelo_triagem=cfg.modelo_triagem,
            modelo_extracao=cfg.modelo_extracao,
            cache_dir=None,  # serverless não tem disco; o banco é a memória
        ),
    )

    # Lista só os ids (uma chamada para cada 100 e-mails) e baixa apenas os que faltam.
    # Baixar a caixa inteira a cada passo para descobrir o que falta transformaria uma
    # sincronização de 50 e-mails em milhares de chamadas à API do Gmail.
    ja_vistos = repo.message_ids_conhecidos()
    faltando = [i for i in origem.listar_ids(limite=cfg.sync_janela) if i not in ja_vistos]

    processados: list[Any] = []
    for message_id in faltando[: max(1, lote)]:
        processados.append(pipeline.processar(origem.buscar(message_id)))

    pendentes = max(0, len(faltando) - len(processados))

    ultimo = processados[-1] if processados else None
    return ResultadoSync(
        processados=len(processados),
        restantes=pendentes,
        concluido=pendentes == 0,
        ultimo=ultimo.assunto if ultimo else None,
        faixa=ultimo.faixa if ultimo else None,
        e_ruido=bool(ultimo and ultimo.e_ruido),
        erro=ultimo.erro if ultimo else None,
    )


@app.get("/api/relatorio")
def relatorio(repo: Repositorio = Repo) -> dict[str, Any]:
    return repo.relatorio()


# ======================================================================================
# Ações do Finance Partner
# ======================================================================================


class EdicaoCampo(BaseModel):
    valor: str = Field(description="Novo valor. Data em ISO, dinheiro como '1234.56'.")


@app.patch("/api/payables/{payable_id}/campos/{campo}")
def editar(
    payable_id: str, campo: str, corpo: EdicaoCampo, repo: Repositorio = Repo
) -> dict[str, Any]:
    """Corrige um campo.

    Não sobrescreve: a extração original sai de vigência e uma linha nova entra com
    origem `humano`. O que o modelo tinha lido continua auditável — e é esse par
    (o que o modelo leu, o que o humano corrigiu) que vira sinal de treino depois.
    """
    if repo.detalhe(payable_id) is None:
        raise HTTPException(404, "conta não encontrada")
    try:
        repo.editar_campo(payable_id, campo, corpo.valor, USUARIO_FP)
    except (ValueError, ArithmeticError) as exc:
        raise HTTPException(422, f"valor inválido para {campo}: {exc}") from exc
    return repo.detalhe(payable_id)


class Observacao(BaseModel):
    observacao: str | None = None


@app.post("/api/payables/{payable_id}/aprovar")
def aprovar(
    payable_id: str, corpo: Observacao | None = None, repo: Repositorio = Repo
) -> dict[str, Any]:
    """Libera a conta para a agenda de pagamento.

    Um humano sempre aprova, inclusive o que está na faixa rápida. `auto_ok` decide
    posição na fila, não autorização.
    """
    p = repo.detalhe(payable_id)
    if p is None:
        raise HTTPException(404, "conta não encontrada")
    if p["status"] not in ("em_revisao", "rejeitado"):
        raise HTTPException(409, f"conta em status {p['status']}, não é aprovável")
    repo.mudar_status(
        payable_id, "aprovado", "aprovar", USUARIO_FP, corpo.observacao if corpo else None
    )
    return repo.detalhe(payable_id)


@app.post("/api/payables/{payable_id}/rejeitar")
def rejeitar(
    payable_id: str, corpo: Observacao | None = None, repo: Repositorio = Repo
) -> dict[str, Any]:
    if repo.detalhe(payable_id) is None:
        raise HTTPException(404, "conta não encontrada")
    repo.mudar_status(
        payable_id, "rejeitado", "rejeitar", USUARIO_FP, corpo.observacao if corpo else None
    )
    return repo.detalhe(payable_id)


@app.post("/api/payables/{payable_id}/reabrir")
def reabrir(payable_id: str, repo: Repositorio = Repo) -> dict[str, Any]:
    """Traz de volta para revisão — inclusive algo marcado como duplicata por engano."""
    if repo.detalhe(payable_id) is None:
        raise HTTPException(404, "conta não encontrada")
    repo.mudar_status(payable_id, "em_revisao", "reabrir", USUARIO_FP)
    return repo.detalhe(payable_id)


class Agendamento(BaseModel):
    data_agendada: date
    banco: str
    codigo_confirmacao: str | None = Field(
        default=None, description="Protocolo devolvido pelo banco no agendamento."
    )


@app.post("/api/payables/{payable_id}/agendar")
def agendar(payable_id: str, corpo: Agendamento, repo: Repositorio = Repo) -> dict[str, Any]:
    """Registra que o pagamento foi agendado no banco.

    A POC não paga nada. O Finance Partner agenda no internet banking e registra aqui o
    banco, a data e o protocolo — é a ponte entre o sistema e o que aconteceu de fato.
    Guardar o protocolo é o que permite reconciliar depois.
    """
    p = repo.detalhe(payable_id)
    if p is None:
        raise HTTPException(404, "conta não encontrada")
    if p["status"] != "aprovado":
        raise HTTPException(
            409, f"só se agenda conta aprovada; esta está em {p['status']}"
        )
    repo.agendar(
        payable_id, corpo.data_agendada, corpo.banco, corpo.codigo_confirmacao, USUARIO_FP
    )
    return repo.detalhe(payable_id)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "org": cfg.org_id, "llm": cfg.tem_llm, "gmail": cfg.tem_gmail}
