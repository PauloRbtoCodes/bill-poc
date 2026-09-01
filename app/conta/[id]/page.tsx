"use client";

/**
 * Tela 2 — Revisão de uma conta.
 *
 * Split view: o documento original à esquerda, os campos extraídos à direita. O revisor
 * precisa poder olhar o documento — é ele que decide um conflito, não a evidência
 * textual que o modelo alegou ter lido.
 *
 * Cada campo mostra de onde veio. Essa é a informação que faz a tela funcionar: um valor
 * com 🔒 foi conferido por aritmética e não precisa de atenção; um com 🤖 foi lido por um
 * modelo e é onde o olho humano rende. Sem essa distinção, o revisor confere tudo com o
 * mesmo cuidado — que é o mesmo que não conferir nada.
 */

import Link from "next/link";
import { use, useEffect, useState } from "react";
import {
  api,
  brl,
  dataBR,
  EDITAVEIS,
  ROTULOS_CAMPO,
  selo,
  type Campo,
  type Detalhe,
  type Verificacao,
} from "@/lib/api";

export default function Revisao({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [conta, setConta] = useState<Detalhe | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    api.detalhe(id).then(setConta).catch((e) => setErro(String(e)));
  }, [id]);

  if (erro) return <p className="text-sm text-error">{erro}</p>;
  if (!conta) return <p className="text-sm text-outline">Carregando…</p>;

  const bloqueios = conta.verificacoes.filter((v) => !v.passou && v.severidade === "bloqueante");
  const alertas = conta.verificacoes.filter((v) => !v.passou && v.severidade === "alerta");

  return (
    <div className="space-y-6">
      <Cabecalho conta={conta} />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Documento conta={conta} />
        <div className="space-y-6">
          {bloqueios.length > 0 && <Bloqueios itens={bloqueios} />}
          {alertas.length > 0 && <Alertas itens={alertas} />}
          <Campos conta={conta} aoAtualizar={setConta} />
          <Instrumentos conta={conta} />
          <Acoes conta={conta} aoAtualizar={setConta} />
          {conta.historico.length > 0 && <Historico conta={conta} />}
        </div>
      </div>
    </div>
  );
}

function Cabecalho({ conta }: { conta: Detalhe }) {
  return (
    <div>
      <Link href="/" className="label-sm text-outline transition hover:text-primary">
        ← Caixa de entrada
      </Link>
      <div className="mt-3 flex flex-wrap items-baseline gap-x-5 gap-y-2">
        <h1 className="headline-lg grad-text">{conta.fornecedor ?? "Fornecedor não identificado"}</h1>
        <span className="headline-md text-mist-white">{brl(conta.valor_centavos)}</span>
        <span className="text-on-surface-variant">vence {dataBR(conta.data_vencimento)}</span>
        <Situacao status={conta.status} faixa={conta.faixa} />
      </div>
      <p className="mt-2 text-on-surface-variant">{conta.descricao}</p>
      <p className="mt-1 text-xs text-outline">
        {conta.email_assunto} · {conta.email_remetente}
      </p>
    </div>
  );
}

function Situacao({ status, faixa }: { status: string; faixa: string }) {
  const estilos: Record<string, string> = {
    em_revisao: "border-tertiary/35 bg-tertiary/14 text-tertiary",
    aprovado: "border-primary/35 bg-primary/14 text-primary",
    agendado: "border-soft-lilac/40 bg-soft-lilac/16 text-soft-lilac",
    pago: "border-white/15 bg-white/8 text-on-surface-variant",
    rejeitado: "border-white/15 bg-white/8 text-outline",
    duplicado: "border-error/35 bg-error/14 text-error",
  };
  const rotulos: Record<string, string> = {
    em_revisao: faixa === "auto_ok" ? "pronto para aprovar" : "em revisão",
    aprovado: "aprovado",
    agendado: "agendado no banco",
    pago: "pago",
    rejeitado: "rejeitado",
    duplicado: "duplicata",
  };
  return <span className={`chip ${estilos[status] ?? ""}`}>{rotulos[status] ?? status}</span>;
}

/** O documento original. É o que resolve uma divergência. */
function Documento({ conta }: { conta: Detalhe }) {
  const [aba, setAba] = useState<"documento" | "email">(conta.document_id ? "documento" : "email");

  return (
    <div className="glass overflow-hidden rounded-lg lg:sticky lg:top-24 lg:self-start">
      <div className="flex items-center gap-1 border-b border-white/8 px-3 py-2 text-xs">
        {conta.document_id && (
          <button
            onClick={() => setAba("documento")}
            className={`rounded-full px-3 py-1 font-medium transition ${
              aba === "documento" ? "bg-white/10 text-mist-white" : "text-outline hover:text-on-surface"
            }`}
          >
            {conta.nome_arquivo ?? "Documento"}
          </button>
        )}
        <button
          onClick={() => setAba("email")}
          className={`rounded-full px-3 py-1 font-medium transition ${
            aba === "email" ? "bg-white/10 text-mist-white" : "text-outline hover:text-on-surface"
          }`}
        >
          E-mail
        </button>
      </div>

      {aba === "documento" && conta.document_id ? (
        conta.documento_tipo === "nfe_xml" ? (
          <div className="p-6 text-sm text-on-surface-variant">
            <p className="label-sm text-primary">XML da NF-e</p>
            <p className="mt-3">
              Este documento não passou por modelo nenhum: os campos foram lidos direto do
              XML fiscal, que é estruturado e assinado digitalmente.
            </p>
            <a
              href={`/api/documentos/${conta.document_id}/arquivo`}
              target="_blank"
              rel="noreferrer"
              className="mt-4 inline-block text-primary underline underline-offset-4"
            >
              Abrir o XML
            </a>
          </div>
        ) : (
          <iframe
            src={`/api/documentos/${conta.document_id}/arquivo`}
            className="h-[700px] w-full bg-black/40"
            title="Documento original"
          />
        )
      ) : (
        <pre className="h-[700px] overflow-auto whitespace-pre-wrap p-5 text-xs leading-relaxed text-on-surface-variant">
          {conta.email_corpo ?? "(sem corpo)"}
        </pre>
      )}
    </div>
  );
}

function Bloqueios({ itens }: { itens: Verificacao[] }) {
  return (
    <section className="glass rounded-lg p-5" style={{ borderColor: "rgba(255,181,155,.28)" }}>
      <h2 className="label-sm text-tertiary">
        {itens.length} conferência{itens.length === 1 ? "" : "s"} não fecharam
      </h2>
      <ul className="mt-3 space-y-3">
        {itens.map((v) => (
          <li key={v.check_nome} className="text-sm text-on-surface">
            <p>{v.mensagem}</p>
            {v.esperado && v.encontrado && v.esperado !== v.encontrado && (
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                <span className="chip border-primary/40 bg-primary/14 text-primary">
                  🔒 {v.esperado}
                </span>
                <span className="text-outline">vs</span>
                <span className="chip border-white/12 bg-white/6 text-outline line-through">
                  🤖 {v.encontrado}
                </span>
                <span className="text-outline">— o valor conferido foi o que ficou gravado</span>
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function Alertas({ itens }: { itens: Verificacao[] }) {
  return (
    <section className="glass rounded-lg p-5">
      <h2 className="label-sm text-outline">Vale saber</h2>
      <ul className="mt-3 space-y-2 text-sm text-on-surface-variant">
        {itens.map((v) => (
          <li key={v.check_nome}>
            {v.mensagem}
            {v.encontrado && v.check_nome === "observacoes_do_modelo" && (
              <span className="mt-2 block rounded bg-black/25 p-3 text-xs italic">
                {v.encontrado}
              </span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

// Ordem de leitura de quem confere uma conta: quem, quanto, quando, e só então o resto.
const ORDEM = [
  "beneficiario",
  "cnpj",
  "valor",
  "data_vencimento",
  "data_emissao",
  "numero_documento",
  "categoria",
  "recorrencia",
];

function Campos({ conta, aoAtualizar }: { conta: Detalhe; aoAtualizar: (d: Detalhe) => void }) {
  const posicao = (c: string) => (ORDEM.indexOf(c) === -1 ? ORDEM.length : ORDEM.indexOf(c));
  const ordenados = [...conta.campos].sort((a, b) => posicao(a.campo) - posicao(b.campo));

  return (
    <section className="glass overflow-hidden rounded-lg">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-white/8 px-5 py-3">
        <h2 className="label-sm text-on-surface">Dados extraídos</h2>
        <span className="text-xs text-outline">🔒 conferido por aritmética · 🤖 lido pelo modelo</span>
      </div>
      <div className="divide-y divide-white/6">
        {ordenados.map((campo) => (
          <LinhaCampo key={campo.campo} campo={campo} contaId={conta.id} aoAtualizar={aoAtualizar} />
        ))}
      </div>
    </section>
  );
}

function LinhaCampo({
  campo,
  contaId,
  aoAtualizar,
}: {
  campo: Campo;
  contaId: string;
  aoAtualizar: (d: Detalhe) => void;
}) {
  const [editando, setEditando] = useState(false);
  const [valor, setValor] = useState(campo.valor_normalizado ?? "");
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const s = selo(campo.origem);
  const editavel = campo.campo in EDITAVEIS;

  async function salvar() {
    setSalvando(true);
    setErro(null);
    try {
      aoAtualizar(await api.editar(contaId, campo.campo, valor));
      setEditando(false);
    } catch (e) {
      setErro(e instanceof Error ? e.message : String(e));
    } finally {
      setSalvando(false);
    }
  }

  const exibicao =
    campo.campo === "valor" && campo.valor_normalizado
      ? Number(campo.valor_normalizado).toLocaleString("pt-BR", {
          style: "currency",
          currency: "BRL",
        })
      : campo.campo.startsWith("data_")
        ? dataBR(campo.valor_normalizado)
        : (campo.valor_normalizado ?? "—");

  return (
    <div className="px-5 py-3.5">
      <div className="flex items-start gap-4">
        <span className="w-32 shrink-0 pt-1 text-xs text-outline">
          {ROTULOS_CAMPO[campo.campo] ?? campo.campo}
        </span>
        <div className="min-w-0 flex-1">
          {editando ? (
            <div className="flex flex-wrap items-center gap-2">
              <input
                autoFocus
                value={valor}
                onChange={(e) => setValor(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && salvar()}
                type={EDITAVEIS[campo.campo]?.tipo === "data" ? "date" : "text"}
                placeholder={EDITAVEIS[campo.campo]?.dica}
                className="field"
              />
              <button onClick={salvar} disabled={salvando} className="btn-primary px-3 py-1.5 text-xs">
                Salvar
              </button>
              <button
                onClick={() => setEditando(false)}
                className="text-xs text-outline transition hover:text-on-surface"
              >
                Cancelar
              </button>
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium text-mist-white">{exibicao}</span>
              <span className={`chip ${s.classe}`}>
                {s.icone} {s.rotulo}
              </span>
              {campo.origem === "llm" && (
                <span className="text-xs text-outline">{Math.round(campo.confianca * 100)}%</span>
              )}
              {editavel && (
                <button
                  onClick={() => setEditando(true)}
                  className="text-xs text-outline underline underline-offset-4 transition hover:text-primary"
                >
                  corrigir
                </button>
              )}
            </div>
          )}
          {campo.evidencia && !editando && (
            <p className="mt-1.5 truncate text-xs italic text-outline" title={campo.evidencia}>
              “{campo.evidencia}”
            </p>
          )}
          {erro && <p className="mt-1 text-xs text-error">{erro}</p>}
        </div>
      </div>
    </div>
  );
}

function Instrumentos({ conta }: { conta: Detalhe }) {
  if (conta.instrumentos.length === 0) return null;
  return (
    <section className="glass overflow-hidden rounded-lg">
      <h2 className="label-sm border-b border-white/8 px-5 py-3 text-on-surface">Como pagar</h2>
      <div className="divide-y divide-white/6">
        {conta.instrumentos.map((i) => (
          <div key={i.id} className="px-5 py-4">
            <p className="label-sm text-outline">{i.tipo.replace(/_/g, " ")}</p>
            <Copiavel texto={i.linha_digitavel ?? i.pix_copia_e_cola ?? ""} />
            {i.decodificado && Object.keys(i.decodificado).length > 0 && (
              <details className="mt-3">
                <summary className="cursor-pointer text-xs text-outline transition hover:text-primary">
                  o que a aritmética extraiu deste código
                </summary>
                <pre className="mt-2 overflow-auto rounded bg-black/30 p-3 text-[11px] text-on-surface-variant">
                  {JSON.stringify(i.decodificado, null, 2)}
                </pre>
              </details>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

function Copiavel({ texto }: { texto: string }) {
  const [copiado, setCopiado] = useState(false);
  if (!texto) return null;
  return (
    <div className="mt-2 flex items-start gap-2">
      <code className="min-w-0 flex-1 break-all rounded bg-black/30 px-3 py-2 text-xs text-on-surface">
        {texto}
      </code>
      <button
        onClick={() => {
          navigator.clipboard.writeText(texto);
          setCopiado(true);
          setTimeout(() => setCopiado(false), 1500);
        }}
        className="btn-ghost shrink-0 px-3 py-1.5 text-xs"
      >
        {copiado ? "copiado" : "copiar"}
      </button>
    </div>
  );
}

function Acoes({ conta, aoAtualizar }: { conta: Detalhe; aoAtualizar: (d: Detalhe) => void }) {
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  async function executar(fn: () => Promise<Detalhe>) {
    setOcupado(true);
    setErro(null);
    try {
      aoAtualizar(await fn());
    } catch (e) {
      setErro(e instanceof Error ? e.message : String(e));
    } finally {
      setOcupado(false);
    }
  }

  return (
    <section className="glass-strong rounded-lg p-5">
      <div className="flex flex-wrap items-center gap-3">
        {conta.status === "em_revisao" && (
          <>
            <button
              onClick={() => executar(() => api.aprovar(conta.id))}
              disabled={ocupado}
              className="btn-primary px-5 py-2.5 text-sm"
            >
              Aprovar para pagamento
            </button>
            <button
              onClick={() => executar(() => api.rejeitar(conta.id))}
              disabled={ocupado}
              className="btn-ghost px-5 py-2.5 text-sm"
            >
              Rejeitar
            </button>
          </>
        )}
        {(conta.status === "duplicado" || conta.status === "rejeitado") && (
          <button
            onClick={() => executar(() => api.reabrir(conta.id))}
            disabled={ocupado}
            className="btn-ghost px-5 py-2.5 text-sm"
          >
            Reabrir para revisão
          </button>
        )}
        {conta.status === "aprovado" && (
          <Link href="/agenda" className="btn-primary px-5 py-2.5 text-sm">
            Ir para a agenda de pagamento →
          </Link>
        )}
      </div>
      <p className="mt-4 text-xs text-outline">
        Nada é pago automaticamente. Aprovar move a conta para a agenda; o agendamento
        acontece no banco, e volta para cá como registro.
      </p>
      {erro && <p className="mt-2 text-xs text-error">{erro}</p>}
    </section>
  );
}

function Historico({ conta }: { conta: Detalhe }) {
  return (
    <section className="glass rounded-lg p-5">
      <h2 className="label-sm text-on-surface">Histórico</h2>
      <ul className="mt-3 space-y-2 text-xs text-on-surface-variant">
        {conta.historico.map((h, i) => (
          <li key={i} className="flex gap-3">
            <span className="shrink-0 text-outline">
              {new Date(h.criado_em).toLocaleString("pt-BR", {
                dateStyle: "short",
                timeStyle: "short",
              })}
            </span>
            <span>
              {h.acao.replace(/_/g, " ")}
              {h.campo && ` · ${ROTULOS_CAMPO[h.campo] ?? h.campo}`}
              {h.valor_anterior && h.valor_novo && (
                <>
                  : <span className="line-through text-outline">{h.valor_anterior}</span> →{" "}
                  <span className="text-primary">{h.valor_novo}</span>
                </>
              )}
              {h.observacao && ` — ${h.observacao}`}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
