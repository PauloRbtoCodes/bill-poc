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
import { useEffect, useState } from "react";
import { use } from "react";
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

  if (erro) return <p className="text-sm text-red-700">{erro}</p>;
  if (!conta) return <p className="text-sm text-stone-400">Carregando…</p>;

  const bloqueios = conta.verificacoes.filter((v) => !v.passou && v.severidade === "bloqueante");
  const alertas = conta.verificacoes.filter((v) => !v.passou && v.severidade === "alerta");

  return (
    <div className="space-y-5">
      <Cabecalho conta={conta} />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Documento conta={conta} />
        <div className="space-y-5">
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
      <Link href="/" className="text-xs text-stone-500 transition hover:text-stone-800">
        ← Caixa de entrada
      </Link>
      <div className="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <h1 className="text-xl font-semibold tracking-tight">{conta.fornecedor ?? "Fornecedor não identificado"}</h1>
        <span className="text-lg font-medium tnum">{brl(conta.valor_centavos)}</span>
        <span className="text-sm text-stone-500">vence {dataBR(conta.data_vencimento)}</span>
        <Situacao status={conta.status} faixa={conta.faixa} />
      </div>
      <p className="mt-1 text-sm text-stone-500">{conta.descricao}</p>
      <p className="mt-0.5 text-xs text-stone-400">
        {conta.email_assunto} · {conta.email_remetente}
      </p>
    </div>
  );
}

function Situacao({ status, faixa }: { status: string; faixa: string }) {
  const estilos: Record<string, string> = {
    em_revisao: "bg-amber-50 text-amber-900 ring-amber-200",
    aprovado: "bg-emerald-50 text-emerald-800 ring-emerald-200",
    agendado: "bg-sky-50 text-sky-800 ring-sky-200",
    pago: "bg-stone-100 text-stone-600 ring-stone-200",
    rejeitado: "bg-stone-100 text-stone-500 ring-stone-200",
    duplicado: "bg-red-50 text-red-800 ring-red-200",
  };
  const rotulos: Record<string, string> = {
    em_revisao: faixa === "auto_ok" ? "pronto para aprovar" : "em revisão",
    aprovado: "aprovado",
    agendado: "agendado no banco",
    pago: "pago",
    rejeitado: "rejeitado",
    duplicado: "duplicata",
  };
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${estilos[status] ?? ""}`}>
      {rotulos[status] ?? status}
    </span>
  );
}

/** O documento original. É o que resolve uma divergência. */
function Documento({ conta }: { conta: Detalhe }) {
  const [aba, setAba] = useState<"documento" | "email">(conta.document_id ? "documento" : "email");

  return (
    <div className="overflow-hidden rounded-lg border border-stone-200 bg-white lg:sticky lg:top-4 lg:self-start">
      <div className="flex items-center gap-1 border-b border-stone-200 bg-stone-50 px-2 py-1.5 text-xs">
        {conta.document_id && (
          <button
            onClick={() => setAba("documento")}
            className={`rounded px-2 py-1 font-medium transition ${
              aba === "documento" ? "bg-white text-stone-900 shadow-sm" : "text-stone-500"
            }`}
          >
            {conta.nome_arquivo ?? "Documento"}
          </button>
        )}
        <button
          onClick={() => setAba("email")}
          className={`rounded px-2 py-1 font-medium transition ${
            aba === "email" ? "bg-white text-stone-900 shadow-sm" : "text-stone-500"
          }`}
        >
          E-mail
        </button>
      </div>

      {aba === "documento" && conta.document_id ? (
        conta.documento_tipo === "nfe_xml" ? (
          <div className="p-6 text-sm text-stone-500">
            <p className="font-medium text-stone-700">XML da NF-e</p>
            <p className="mt-2">
              Este documento não passou por modelo nenhum: os campos foram lidos direto do
              XML fiscal, que é estruturado e assinado digitalmente.
            </p>
            <a
              href={`/api/documentos/${conta.document_id}/arquivo`}
              target="_blank"
              rel="noreferrer"
              className="mt-3 inline-block text-stone-700 underline underline-offset-2"
            >
              Abrir o XML
            </a>
          </div>
        ) : (
          <iframe
            src={`/api/documentos/${conta.document_id}/arquivo`}
            className="h-[700px] w-full bg-stone-100"
            title="Documento original"
          />
        )
      ) : (
        <pre className="h-[700px] overflow-auto whitespace-pre-wrap p-4 text-xs leading-relaxed text-stone-700">
          {conta.email_corpo ?? "(sem corpo)"}
        </pre>
      )}
    </div>
  );
}

function Bloqueios({ itens }: { itens: Verificacao[] }) {
  return (
    <section className="rounded-lg border border-amber-200 bg-amber-50 p-4">
      <h2 className="text-sm font-semibold text-amber-900">
        {itens.length} conferência(s) não fecharam
      </h2>
      <ul className="mt-2 space-y-2.5">
        {itens.map((v) => (
          <li key={v.check_nome} className="text-sm text-amber-900">
            <p>{v.mensagem}</p>
            {v.esperado && v.encontrado && v.esperado !== v.encontrado && (
              <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs">
                <span className="rounded bg-white px-2 py-1 font-medium text-emerald-800 ring-1 ring-emerald-200 tnum">
                  🔒 {v.esperado}
                </span>
                <span className="text-amber-600">vs</span>
                <span className="rounded bg-white px-2 py-1 text-stone-600 ring-1 ring-stone-200 line-through tnum">
                  🤖 {v.encontrado}
                </span>
                <span className="text-amber-700">— o valor conferido foi o que ficou gravado</span>
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
    <section className="rounded-lg border border-stone-200 bg-white p-4">
      <h2 className="text-sm font-semibold text-stone-700">Vale saber</h2>
      <ul className="mt-2 space-y-1.5 text-sm text-stone-600">
        {itens.map((v) => (
          <li key={v.check_nome}>
            {v.mensagem}
            {v.encontrado && v.check_nome === "observacoes_do_modelo" && (
              <span className="mt-1 block rounded bg-stone-50 p-2 text-xs italic text-stone-600">
                {v.encontrado}
              </span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

const ORDEM = ["beneficiario", "cnpj", "valor", "data_vencimento", "data_emissao", "numero_documento", "categoria", "recorrencia"];

function Campos({ conta, aoAtualizar }: { conta: Detalhe; aoAtualizar: (d: Detalhe) => void }) {
  // Ordem de leitura de quem confere uma conta: quem, quanto, quando, e só então o resto.
  const posicao = (c: string) => (ORDEM.indexOf(c) === -1 ? ORDEM.length : ORDEM.indexOf(c));
  const ordenados = [...conta.campos].sort((a, b) => posicao(a.campo) - posicao(b.campo));
  return (
    <section className="overflow-hidden rounded-lg border border-stone-200 bg-white">
      <div className="flex items-baseline justify-between border-b border-stone-200 bg-stone-50 px-4 py-2.5">
        <h2 className="text-sm font-semibold text-stone-700">Dados extraídos</h2>
        <span className="text-xs text-stone-400">🔒 conferido por aritmética · 🤖 lido pelo modelo</span>
      </div>
      <div className="divide-y divide-stone-100">
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
      ? Number(campo.valor_normalizado).toLocaleString("pt-BR", { style: "currency", currency: "BRL" })
      : campo.campo.startsWith("data_")
        ? dataBR(campo.valor_normalizado)
        : (campo.valor_normalizado ?? "—");

  return (
    <div className="px-4 py-3">
      <div className="flex items-start gap-3">
        <span className="w-32 shrink-0 pt-0.5 text-xs text-stone-500">
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
                className="rounded border border-stone-300 px-2 py-1 text-sm focus:border-stone-500 focus:outline-none"
              />
              <button
                onClick={salvar}
                disabled={salvando}
                className="rounded bg-stone-900 px-2.5 py-1 text-xs font-medium text-white disabled:opacity-50"
              >
                Salvar
              </button>
              <button
                onClick={() => setEditando(false)}
                className="text-xs text-stone-500 hover:text-stone-800"
              >
                Cancelar
              </button>
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium text-stone-900 tnum">{exibicao}</span>
              <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ring-1 ${s.classe}`}>
                {s.icone} {s.rotulo}
              </span>
              {campo.origem === "llm" && (
                <span className="text-[11px] tabular-nums text-stone-400">
                  {Math.round(campo.confianca * 100)}%
                </span>
              )}
              {editavel && (
                <button
                  onClick={() => setEditando(true)}
                  className="text-[11px] text-stone-400 underline underline-offset-2 hover:text-stone-700"
                >
                  corrigir
                </button>
              )}
            </div>
          )}
          {campo.evidencia && !editando && (
            <p className="mt-1 truncate text-xs italic text-stone-400" title={campo.evidencia}>
              “{campo.evidencia}”
            </p>
          )}
          {erro && <p className="mt-1 text-xs text-red-600">{erro}</p>}
        </div>
      </div>
    </div>
  );
}

function Instrumentos({ conta }: { conta: Detalhe }) {
  if (conta.instrumentos.length === 0) return null;
  return (
    <section className="overflow-hidden rounded-lg border border-stone-200 bg-white">
      <h2 className="border-b border-stone-200 bg-stone-50 px-4 py-2.5 text-sm font-semibold text-stone-700">
        Como pagar
      </h2>
      <div className="divide-y divide-stone-100">
        {conta.instrumentos.map((i) => (
          <div key={i.id} className="px-4 py-3">
            <p className="text-xs text-stone-500">{i.tipo.replace(/_/g, " ")}</p>
            <Copiavel texto={i.linha_digitavel ?? i.pix_copia_e_cola ?? ""} />
            {i.decodificado && Object.keys(i.decodificado).length > 0 && (
              <details className="mt-2">
                <summary className="cursor-pointer text-xs text-stone-400 hover:text-stone-600">
                  o que a aritmética extraiu deste código
                </summary>
                <pre className="mt-1.5 overflow-auto rounded bg-stone-50 p-2 text-[11px] text-stone-600">
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
    <div className="mt-1 flex items-start gap-2">
      <code className="min-w-0 flex-1 break-all rounded bg-stone-50 px-2 py-1.5 text-xs text-stone-700 tnum">
        {texto}
      </code>
      <button
        onClick={() => {
          navigator.clipboard.writeText(texto);
          setCopiado(true);
          setTimeout(() => setCopiado(false), 1500);
        }}
        className="shrink-0 rounded border border-stone-300 px-2 py-1 text-xs font-medium text-stone-700 transition hover:bg-stone-50"
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
    <section className="rounded-lg border border-stone-200 bg-white p-4">
      <div className="flex flex-wrap items-center gap-2">
        {conta.status === "em_revisao" && (
          <>
            <button
              onClick={() => executar(() => api.aprovar(conta.id))}
              disabled={ocupado}
              className="rounded-md bg-stone-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-stone-800 disabled:opacity-50"
            >
              Aprovar para pagamento
            </button>
            <button
              onClick={() => executar(() => api.rejeitar(conta.id))}
              disabled={ocupado}
              className="rounded-md border border-stone-300 px-3.5 py-2 text-sm font-medium text-stone-700 transition hover:bg-stone-50 disabled:opacity-50"
            >
              Rejeitar
            </button>
          </>
        )}
        {(conta.status === "duplicado" || conta.status === "rejeitado") && (
          <button
            onClick={() => executar(() => api.reabrir(conta.id))}
            disabled={ocupado}
            className="rounded-md border border-stone-300 px-3.5 py-2 text-sm font-medium text-stone-700 transition hover:bg-stone-50 disabled:opacity-50"
          >
            Reabrir para revisão
          </button>
        )}
        {conta.status === "aprovado" && (
          <Link
            href="/agenda"
            className="rounded-md bg-stone-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-stone-800"
          >
            Ir para a agenda de pagamento →
          </Link>
        )}
      </div>
      <p className="mt-3 text-xs text-stone-400">
        Nada é pago automaticamente. Aprovar move a conta para a agenda; o agendamento
        acontece no banco, e volta para cá como registro.
      </p>
      {erro && <p className="mt-2 text-xs text-red-600">{erro}</p>}
    </section>
  );
}

function Historico({ conta }: { conta: Detalhe }) {
  return (
    <section className="rounded-lg border border-stone-200 bg-white p-4">
      <h2 className="text-sm font-semibold text-stone-700">Histórico</h2>
      <ul className="mt-2 space-y-1.5 text-xs text-stone-500">
        {conta.historico.map((h, i) => (
          <li key={i} className="flex gap-2">
            <span className="tabular-nums text-stone-400">
              {new Date(h.criado_em).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })}
            </span>
            <span className="text-stone-700">
              {h.acao.replace(/_/g, " ")}
              {h.campo && ` · ${ROTULOS_CAMPO[h.campo] ?? h.campo}`}
              {h.valor_anterior && h.valor_novo && (
                <>
                  : <span className="line-through">{h.valor_anterior}</span> → {h.valor_novo}
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
