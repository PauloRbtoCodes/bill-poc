"""CLI do billpoc.

    billpoc doctor              o que está configurado e o que falta
    billpoc auth                autoriza a caixa via OAuth (abre o navegador)
    billpoc ingest              baixa os e-mails do Gmail para fixtures/
    billpoc initdb              aplica schema e seed no banco
    billpoc run                 roda o pipeline sobre os e-mails
    billpoc report              acurácia por origem, custo e motivos de bloqueio
    billpoc inspecionar <id>    a trilha completa de um payable
"""

from __future__ import annotations

import logging
from decimal import Decimal

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import config as config_mod
from .extract.claude import Extrator, SemCredencial
from .ingest.eml import EmlSource
from .ingest.gmail import GmailSource
from .pipeline import Pipeline, ResultadoEmail
from .store.db import BancoIndisponivel, conectar, schema_aplicado
from .store.repositories import Repositorio
from .validate.rules import formatar_brl

app = typer.Typer(add_completion=False, help="POC de contas a pagar a partir de e-mails.")
console = Console()


def _cfg():
    return config_mod.carregar()


# ======================================================================================
# Diagnóstico
# ======================================================================================


@app.command()
def doctor() -> None:
    """Mostra o que está configurado. Não imprime valor de credencial nenhuma."""
    cfg = _cfg()
    tabela = Table("Item", "Status", "Detalhe", title="Configuração", title_justify="left")

    def linha(item: str, ok: bool, detalhe: str, opcional: bool = False) -> None:
        marca = "[green]ok[/]" if ok else ("[yellow]falta[/]" if opcional else "[red]falta[/]")
        tabela.add_row(item, marca, detalhe)

    linha(
        "Anthropic API key",
        cfg.tem_llm,
        "definida em .env" if cfg.tem_llm else "sem chave — só roda com --somente-cache",
        opcional=True,
    )
    linha(
        "Gmail credentials",
        cfg.gmail_credentials.exists(),
        str(cfg.gmail_credentials) if cfg.gmail_credentials.exists() else "ver docs/setup.md",
        opcional=True,
    )
    linha(
        "Gmail token",
        cfg.tem_gmail,
        "autorizado" if cfg.tem_gmail else "rode `billpoc auth`",
        opcional=True,
    )

    try:
        with conectar(cfg.database_url) as conexao:
            aplicado = schema_aplicado(conexao)
        linha("Banco", True, "conectado" + ("" if aplicado else " — schema não aplicado"))
        linha("Schema", aplicado, "16 tabelas" if aplicado else "rode `billpoc initdb`")
    except BancoIndisponivel as exc:
        linha("Banco", False, str(exc).splitlines()[0])

    n_fixtures = len(list(cfg.fixtures_dir.glob("*.eml"))) if cfg.fixtures_dir.is_dir() else 0
    linha("Fixtures", n_fixtures > 0, f"{n_fixtures} arquivo(s) .eml", opcional=True)

    n_cache = len(list(cfg.cache_dir.glob("*.json"))) if cfg.cache_dir.is_dir() else 0
    linha("Cache de LLM", n_cache > 0, f"{n_cache} resposta(s) gravada(s)", opcional=True)

    console.print(tabela)

    if not cfg.tem_llm and n_cache == 0:
        console.print(
            "\n[yellow]Sem chave da Anthropic e sem cache.[/] O pipeline não tem como "
            "extrair nada.\nVeja [bold]docs/setup.md[/] — leva 2 minutos."
        )


# ======================================================================================
# Credenciais e captura
# ======================================================================================


@app.command()
def auth() -> None:
    """Autoriza o acesso de leitura à caixa via OAuth. Abre o navegador."""
    cfg = _cfg()
    fonte = GmailSource(cfg.gmail_credentials, cfg.gmail_token)
    console.print(
        Panel(
            "Vai abrir o navegador.\n\n"
            f"1. Logue em [bold]{cfg.mailbox}[/]\n"
            "2. Na tela 'app não verificado': [bold]Avançado → Acessar[/]\n"
            "3. Conceda o acesso de [bold]leitura[/] ao Gmail",
            title="Autorização Gmail",
        )
    )
    try:
        fonte.autorizar()
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    console.print(f"[green]Autorizado.[/] Token em {cfg.gmail_token}")


@app.command()
def ingest(
    limite: int = typer.Option(50, help="Máximo de e-mails a baixar."),
    query: str = typer.Option("", help="Filtro no dialeto de busca do Gmail."),
) -> None:
    """Baixa os e-mails da caixa e salva como .eml em fixtures/.

    Separar a captura do processamento é de propósito: com os .eml em disco dá para
    reprocessar quantas vezes for preciso sem tocar na rede nem no Gmail.
    """
    cfg = _cfg()
    if not cfg.tem_gmail:
        console.print("[red]Não autorizado.[/] Rode `billpoc auth` primeiro.")
        raise typer.Exit(1)

    origem = GmailSource(cfg.gmail_credentials, cfg.gmail_token, query or cfg.gmail_query)
    destino = EmlSource(cfg.fixtures_dir)

    baixados = 0
    with console.status("Baixando..."):
        for email in origem.listar(limite=limite):
            destino.salvar(email)
            baixados += 1
            console.print(
                f"  [dim]{email.recebido_em:%d/%m}[/] {email.assunto[:60]:<60} "
                f"[dim]{len(email.anexos)} anexo(s)[/]"
            )

    console.print(f"\n[green]{baixados} e-mail(s)[/] salvos em {cfg.fixtures_dir}")


@app.command()
def semear() -> None:
    """Gera a caixa de demonstração: fixtures .eml + cache de LLM pré-populado.

    Deixa o projeto executável sem nenhuma credencial, e dá à demo cenários escolhidos
    em vez de sorteados — um conflito de valor, um comprovante que parece cobrança, um
    boleto reenviado, um documento ilegível.
    """
    from .demo.seed import semear as gerar

    cfg = _cfg()
    cenarios = gerar(cfg.fixtures_dir, cfg.cache_dir, cfg.modelo_triagem, cfg.modelo_extracao)

    tabela = Table("#", "Cenário", "O que demonstra", title="Caixa de demonstração",
                   title_justify="left")
    for i, c in enumerate(cenarios, start=1):
        tabela.add_row(str(i), c.nome, c.explicacao or "—")
    console.print(tabela)
    console.print(
        f"\n[green]{len(cenarios)} e-mail(s)[/] em {cfg.fixtures_dir}\n"
        "Agora: [bold]billpoc run --somente-cache[/]"
    )


@app.command()
def initdb() -> None:
    """Aplica db/schema.sql e db/seed.sql no banco configurado."""
    cfg = _cfg()
    raiz = config_mod.RAIZ
    try:
        with conectar(cfg.database_url) as conexao:
            for arquivo in ("db/schema.sql", "db/seed.sql"):
                sql = (raiz / arquivo).read_text()
                with conexao.cursor() as cur:
                    cur.execute(sql)
                console.print(f"  [green]ok[/] {arquivo}")
    except BancoIndisponivel as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    console.print("[green]Banco pronto.[/]")


# ======================================================================================
# Processamento
# ======================================================================================


@app.command()
def run(
    fonte: str = typer.Option("eml", help="'eml' (fixtures) ou 'gmail' (ao vivo)."),
    limite: int | None = typer.Option(None, help="Máximo de e-mails a processar."),
    somente_cache: bool = typer.Option(
        False, "--somente-cache", help="Não chama a API; usa só respostas já gravadas."
    ),
    verboso: bool = typer.Option(False, "-v", help="Mostra o log do pipeline."),
) -> None:
    """Roda o pipeline: triagem, extração, validação e gravação."""
    logging.basicConfig(level=logging.INFO if verboso else logging.WARNING, format="%(message)s")
    cfg = _cfg()

    origem = (
        EmlSource(cfg.fixtures_dir)
        if fonte == "eml"
        else GmailSource(cfg.gmail_credentials, cfg.gmail_token, cfg.gmail_query)
    )
    extrator = Extrator(
        modelo_triagem=cfg.modelo_triagem,
        modelo_extracao=cfg.modelo_extracao,
        cache_dir=cfg.cache_dir,
        somente_cache=somente_cache or not cfg.tem_llm,
    )

    resultados: list[ResultadoEmail] = []
    try:
        with conectar(cfg.database_url) as conexao:
            repo = Repositorio(conexao, cfg.org_id)
            pipeline = Pipeline(cfg, repo, extrator)

            for email in origem.listar(limite=limite):
                try:
                    resultado = pipeline.processar(email)
                except SemCredencial as exc:
                    console.print(f"[yellow]pulado[/] {email.assunto[:50]} — {exc}")
                    continue
                resultados.append(resultado)
                _imprimir(resultado)
    except BancoIndisponivel as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc

    _resumo(resultados)


def _imprimir(r: ResultadoEmail) -> None:
    if r.erro:
        console.print(f"[red]erro[/]    {r.assunto[:55]:<55} {r.erro}")
        return
    if r.e_ruido:
        console.print(
            f"[dim]ruído[/]   {r.assunto[:55]:<55} "
            f"[dim]{r.triagem.justificativa[:60]}[/]"
        )
        return

    for conciliacao in r.conciliacoes:
        valor = conciliacao.campos.get("valor")
        venc = conciliacao.campos.get("data_vencimento")
        benef = conciliacao.campos.get("beneficiario")

        marca = "[green]auto[/]   " if conciliacao.faixa == "auto_ok" else "[yellow]revisar[/]"
        origem = conciliacao.campos["valor"].origem if "valor" in conciliacao.campos else "?"
        selo = "🔒" if origem in ("codigo_barras", "nfe_xml", "chave_nfe", "pix") else "🤖"

        console.print(
            f"{marca} {(benef.valor if benef else '?') or '?':<28.28} "
            f"{formatar_brl(valor.valor) if valor and valor.valor else '—':>14} "
            f"{venc.valor.isoformat() if venc and venc.valor else '—':>10} "
            f"{selo} [dim]{origem}[/]"
        )
        for v in conciliacao.bloqueios:
            console.print(f"          [yellow]↳[/] {v.mensagem}")


def _resumo(resultados: list[ResultadoEmail]) -> None:
    if not resultados:
        console.print("[yellow]Nenhum e-mail processado.[/]")
        return

    cobrancas = [r for r in resultados if not r.e_ruido and not r.erro]
    payables = sum(len(r.payables) for r in cobrancas)
    auto = sum(1 for r in cobrancas if r.faixa == "auto_ok")
    custo = sum((r.custo_centavos for r in resultados), Decimal(0))
    cache_hits = sum(1 for r in resultados for u in r.usos if u.cache_hit)
    chamadas = sum(len(r.usos) for r in resultados)

    tabela = Table.grid(padding=(0, 2))
    tabela.add_row("E-mails processados", str(len(resultados)))
    tabela.add_row("Classificados como cobrança", str(len(cobrancas)))
    tabela.add_row("Ruído descartado", str(sum(1 for r in resultados if r.e_ruido)))
    tabela.add_row("Contas a pagar geradas", str(payables))
    tabela.add_row("Na faixa rápida", f"{auto} de {len(cobrancas)}")
    tabela.add_row("Erros", str(sum(1 for r in resultados if r.erro)))
    tabela.add_row(
        "Custo de LLM",
        f"US$ {custo / 100:.4f}" + (f"  [dim]({cache_hits}/{chamadas} do cache)[/]" if chamadas else ""),
    )
    console.print(Panel(tabela, title="Resumo", title_align="left"))


# ======================================================================================
# Relatórios
# ======================================================================================


@app.command()
def report() -> None:
    """Origem dos dados, custo por etapa e os motivos que mais mandam para revisão."""
    cfg = _cfg()
    with conectar(cfg.database_url) as conexao:
        dados = Repositorio(conexao, cfg.org_id).relatorio()

    resumo = Table.grid(padding=(0, 2))
    resumo.add_row("E-mails capturados", str(dados["emails"]))
    resumo.add_row("Cobranças", str(dados["cobrancas"]))
    resumo.add_row("Ruído", str(dados["ruido"]))
    resumo.add_row("Contas a pagar", str(dados["payables"]))
    resumo.add_row("Na faixa rápida", str(dados["auto_ok"]))
    resumo.add_row("Duplicatas barradas", str(dados["duplicados"]))
    resumo.add_row("Total a pagar", formatar_brl(Decimal(dados["total_centavos"]) / 100))
    console.print(Panel(resumo, title="Processamento", title_align="left"))

    if dados["origens"]:
        # A métrica que importa: quanto do dado veio de aritmética e quanto de leitura.
        t = Table("Origem", "Campos", title="De onde vêm os dados", title_justify="left")
        total = sum(o["campos"] for o in dados["origens"])
        for o in dados["origens"]:
            determinística = o["origem"] in ("codigo_barras", "nfe_xml", "chave_nfe", "pix")
            marca = "🔒" if determinística else ("✏️" if o["origem"] == "humano" else "🤖")
            t.add_row(f"{marca} {o['origem']}", f"{o['campos']} ({o['campos'] / total:.0%})")
        console.print(t)

    if dados["custos"]:
        t = Table(
            "Etapa", "Modelo", "Chamadas", "Entrada", "Saída", "Custo", "Latência",
            title="Custo por etapa", title_justify="left",
        )
        for c in dados["custos"]:
            t.add_row(
                c["etapa"],
                c["modelo"],
                str(c["chamadas"]),
                f"{c['input_tokens']:,}".replace(",", "."),
                f"{c['output_tokens']:,}".replace(",", "."),
                f"US$ {Decimal(c['custo_centavos']) / 100:.4f}",
                f"{c['latencia_media_ms']} ms",
            )
        console.print(t)

    if dados["bloqueios"]:
        t = Table("Verificação", "Vezes", title="Por que caiu em revisão", title_justify="left")
        for b in dados["bloqueios"]:
            t.add_row(b["check_nome"], str(b["falhas"]))
        console.print(t)


@app.command()
def inspecionar(payable_id: str) -> None:
    """Mostra a trilha completa de uma conta: campo, origem, evidência e verificações."""
    cfg = _cfg()
    with conectar(cfg.database_url) as conexao:
        p = Repositorio(conexao, cfg.org_id).detalhe(payable_id)

    if not p:
        console.print("[red]não encontrado[/]")
        raise typer.Exit(1)

    console.print(
        Panel(
            f"[bold]{p['fornecedor'] or '(sem fornecedor)'}[/]\n"
            f"{formatar_brl(Decimal(p['valor_centavos']) / 100)} — "
            f"vence {p['data_vencimento']}\n"
            f"status [bold]{p['status']}[/] · faixa [bold]{p['faixa']}[/] · "
            f"confiança {p['confianca_geral']}\n\n"
            f"[dim]e-mail: {p['email_assunto']}\nde: {p['email_remetente']}[/]",
            title=f"payable {payable_id[:8]}",
            title_align="left",
        )
    )

    t = Table("Campo", "Valor", "Origem", "Conf.", "Evidência", title="Proveniência", title_justify="left")
    for c in p["campos"]:
        determinística = c["origem"] in ("codigo_barras", "nfe_xml", "chave_nfe", "pix")
        marca = "🔒" if determinística else ("✏️" if c["origem"] == "humano" else "🤖")
        t.add_row(
            c["campo"],
            str(c["valor_normalizado"] or "—"),
            f"{marca} {c['origem']}",
            f"{c['confianca']:.2f}",
            (c["evidencia"] or "")[:50],
        )
    console.print(t)

    falhas = [v for v in p["verificacoes"] if not v["passou"]]
    if falhas:
        t = Table("Verificação", "Severidade", "Esperado", "Encontrado", "Mensagem",
                  title="Falhas", title_justify="left")
        for v in falhas:
            cor = "red" if v["severidade"] == "bloqueante" else "yellow"
            t.add_row(
                v["check_nome"], f"[{cor}]{v['severidade']}[/]",
                v["esperado"] or "—", (v["encontrado"] or "—")[:30], (v["mensagem"] or "")[:60],
            )
        console.print(t)
    else:
        console.print("[green]Todas as verificações passaram.[/]")


if __name__ == "__main__":
    app()
