"use client";

/**
 * Tela 1 — Caixa de entrada.
 *
 * Três faixas, na ordem em que o Finance Partner deve olhar:
 *
 *   Revisar   o que precisa de decisão humana, com o motivo em cada linha
 *   Pronto    passou em todos os checks; ainda assim exige aprovação
 *   Ruído     o que a triagem descartou, com a justificativa — visível de propósito
 *
 * Dentro de "Revisar", a ordenação vem do banco: urgente primeiro (vence em até dois
 * dias), depois por número de bloqueios. Quem vence antes e tem mais problema aparece
 * primeiro, que é a ordem em que o dinheiro é perdido.
 */

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, brl, dataBR, type ItemFila } from "@/lib/api";

interface ItemRuido {
  email_id: string;
  assunto: string;
  remetente: string;
  recebido_em: string;
  confianca: number;
  justificativa: string;
  anexos: number;
}

type Faixa = "revisar" | "auto_ok" | "ruido";

export default function CaixaDeEntrada() {
  const [fila, setFila] = useState<ItemFila[]>([]);
  const [ruido, setRuido] = useState<ItemRuido[]>([]);
  const [faixa, setFaixa] = useState<Faixa>("revisar");
  const [erro, setErro] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(true);

  const carregar = useCallback(async () => {
    try {
      const [f, r] = await Promise.all([
        api.fila(),
        fetch("/api/ruido", { cache: "no-store" }).then((x) => x.json()),
      ]);
      setFila(f);
      setRuido(r);
      setErro(null);
    } catch (e) {
      setErro(e instanceof Error ? e.message : String(e));
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    carregar();
  }, [carregar]);

  const revisar = fila.filter((i) => i.faixa === "revisar");
  const prontos = fila.filter((i) => i.faixa === "auto_ok");
  const total = fila.reduce((s, i) => s + i.valor_centavos, 0);

  if (erro)
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-sm text-red-800">
        <p className="font-medium">Não consegui falar com a API.</p>
        <pre className="mt-2 whitespace-pre-wrap text-xs">{erro}</pre>
        <p className="mt-3 text-red-700">
          Suba o backend com <code className="rounded bg-red-100 px-1">uv run uvicorn billpoc.api:app --port 8000</code>
        </p>
      </div>
    );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Caixa de entrada</h1>
          <p className="mt-1 text-sm text-stone-500">
            {fila.length} cobrança(s) aguardando decisão · {brl(total)} no total
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Sincronizar aoTerminar={carregar} />
          <div className="flex gap-1 rounded-lg bg-stone-100 p-1 text-sm">
          <Aba ativa={faixa === "revisar"} onClick={() => setFaixa("revisar")} contagem={revisar.length}>
            Revisar
          </Aba>
          <Aba ativa={faixa === "auto_ok"} onClick={() => setFaixa("auto_ok")} contagem={prontos.length}>
            Pronto
          </Aba>
          <Aba ativa={faixa === "ruido"} onClick={() => setFaixa("ruido")} contagem={ruido.length}>
            Ruído
          </Aba>
          </div>
        </div>
      </div>

      {carregando ? (
        <p className="text-sm text-stone-400">Carregando…</p>
      ) : faixa === "ruido" ? (
        <ListaRuido itens={ruido} aoReclassificar={carregar} />
      ) : (
        <ListaCobrancas itens={faixa === "revisar" ? revisar : prontos} faixa={faixa} />
      )}
    </div>
  );
}

/**
 * Sincronização com a caixa de e-mail.
 *
 * Chama `/api/sync` em laço, um e-mail por vez, até o backend dizer que acabou. Parece
 * ineficiente, mas é o que cabe no limite de 60 segundos de uma função serverless — e
 * como cada e-mail é uma transação própria e a ingestão é idempotente, interromper no
 * meio (fechar a aba, cair a rede) não corrompe nada: recomeçar continua de onde parou.
 *
 * O progresso aparece na tela porque processar uma caixa leva minutos, e uma barra que
 * não se move é indistinguível de um sistema travado.
 */
function Sincronizar({ aoTerminar }: { aoTerminar: () => Promise<void> }) {
  const [rodando, setRodando] = useState(false);
  const [progresso, setProgresso] = useState<{ feitos: number; faltam: number; atual: string } | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const cancelar = useRef(false);

  async function sincronizar() {
    setRodando(true);
    setErro(null);
    cancelar.current = false;
    let feitos = 0;

    try {
      for (;;) {
        const r = await api.sync(1);
        feitos += r.processados;
        setProgresso({ feitos, faltam: r.restantes, atual: r.ultimo ?? "" });
        await aoTerminar();
        if (r.concluido || cancelar.current || r.processados === 0) break;
      }
    } catch (e) {
      setErro(e instanceof Error ? e.message : String(e));
    } finally {
      setRodando(false);
      setTimeout(() => setProgresso(null), 4000);
    }
  }

  return (
    <div className="flex items-center gap-2">
      {progresso && (
        <span className="text-xs text-stone-500">
          {rodando ? (
            <>
              {progresso.feitos} processado(s)
              {progresso.faltam > 0 && `, ${progresso.faltam} na fila`}
              {progresso.atual && (
                <span className="ml-1 text-stone-400">— {progresso.atual.slice(0, 34)}</span>
              )}
            </>
          ) : (
            <span className="text-emerald-700">{progresso.feitos} e-mail(s) processado(s)</span>
          )}
        </span>
      )}
      {erro && <span className="max-w-64 truncate text-xs text-red-600" title={erro}>{erro}</span>}
      <button
        onClick={rodando ? () => (cancelar.current = true) : sincronizar}
        className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
          rodando
            ? "border border-stone-300 text-stone-600 hover:bg-stone-50"
            : "bg-stone-900 text-white hover:bg-stone-800"
        }`}
      >
        {rodando ? "Parar" : "Buscar novos e-mails"}
      </button>
    </div>
  );
}

function Aba({
  ativa,
  onClick,
  contagem,
  children,
}: {
  ativa: boolean;
  onClick: () => void;
  contagem: number;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-2 rounded-md px-3 py-1.5 font-medium transition ${
        ativa ? "bg-white text-stone-900 shadow-sm" : "text-stone-500 hover:text-stone-800"
      }`}
    >
      {children}
      <span
        className={`rounded-full px-1.5 text-xs tabular-nums ${
          ativa ? "bg-stone-100 text-stone-600" : "text-stone-400"
        }`}
      >
        {contagem}
      </span>
    </button>
  );
}

function ListaCobrancas({ itens, faixa }: { itens: ItemFila[]; faixa: "revisar" | "auto_ok" }) {
  if (itens.length === 0)
    return (
      <p className="rounded-lg border border-dashed border-stone-300 p-10 text-center text-sm text-stone-400">
        {faixa === "revisar" ? "Nada pendente de revisão." : "Nada na faixa rápida."}
      </p>
    );

  return (
    <div className="overflow-hidden rounded-lg border border-stone-200 bg-white">
      <table className="w-full text-sm">
        <thead className="border-b border-stone-200 bg-stone-50 text-left text-xs uppercase tracking-wide text-stone-500">
          <tr>
            <th className="px-4 py-2.5 font-medium">Fornecedor</th>
            <th className="px-4 py-2.5 text-right font-medium">Valor</th>
            <th className="px-4 py-2.5 font-medium">Vencimento</th>
            <th className="px-4 py-2.5 font-medium">Confiança</th>
            <th className="px-4 py-2.5 font-medium">Situação</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-stone-100">
          {itens.map((item) => (
            <tr key={item.id} className="transition hover:bg-stone-50">
              <td className="px-4 py-3">
                <Link href={`/conta/${item.id}`} className="block">
                  <span className="font-medium text-stone-900">{item.fornecedor ?? "—"}</span>
                  {item.recorrencia === "recorrente" && (
                    <span className="ml-2 rounded bg-sky-50 px-1.5 py-0.5 text-[11px] font-medium text-sky-700 ring-1 ring-sky-200">
                      recorrente
                    </span>
                  )}
                  <span className="mt-0.5 block truncate text-xs text-stone-400">
                    {item.email_assunto}
                  </span>
                </Link>
              </td>
              <td className="px-4 py-3 text-right font-medium tnum">{brl(item.valor_centavos)}</td>
              <td className="px-4 py-3 tnum">
                <span className={item.urgente ? "font-medium text-red-700" : ""}>
                  {dataBR(item.data_vencimento)}
                </span>
                {item.urgente && (
                  <span className="ml-1.5 rounded bg-red-50 px-1.5 py-0.5 text-[11px] font-medium text-red-700 ring-1 ring-red-200">
                    urgente
                  </span>
                )}
              </td>
              <td className="px-4 py-3">
                <Confianca valor={item.confianca_geral} />
              </td>
              <td className="px-4 py-3">
                {item.falhas_bloqueantes > 0 ? (
                  <span className="text-amber-800">
                    {item.falhas_bloqueantes} conferência(s) não fecharam
                  </span>
                ) : item.alertas > 0 ? (
                  <span className="text-stone-500">{item.alertas} alerta(s)</span>
                ) : (
                  <span className="text-emerald-700">tudo conferido</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Barra de confiança. Cor por faixa porque número solto ninguém interpreta rápido. */
function Confianca({ valor }: { valor: number | null }) {
  if (valor === null) return <span className="text-stone-400">—</span>;
  const pct = Math.round(valor * 100);
  const cor = pct >= 90 ? "bg-emerald-500" : pct >= 70 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-stone-200">
        <div className={`h-full ${cor}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs tabular-nums text-stone-500">{pct}%</span>
    </div>
  );
}

function ListaRuido({ itens, aoReclassificar }: { itens: ItemRuido[]; aoReclassificar: () => void }) {
  const [ocupado, setOcupado] = useState<string | null>(null);

  async function reclassificar(id: string) {
    setOcupado(id);
    await fetch(`/api/emails/${id}/reclassificar`, { method: "POST" });
    await aoReclassificar();
    setOcupado(null);
  }

  if (itens.length === 0)
    return (
      <p className="rounded-lg border border-dashed border-stone-300 p-10 text-center text-sm text-stone-400">
        Nenhum e-mail descartado.
      </p>
    );

  return (
    <div className="space-y-3">
      <p className="text-sm text-stone-500">
        O que a triagem descartou fica visível com o motivo. Um falso negativo aqui é uma
        conta perdida, e conta perdida vira multa — então nada é descartado em silêncio.
      </p>
      <div className="divide-y divide-stone-100 overflow-hidden rounded-lg border border-stone-200 bg-white">
        {itens.map((item) => (
          <div key={item.email_id} className="flex items-start gap-4 p-4">
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-stone-800">{item.assunto}</p>
              <p className="mt-0.5 text-xs text-stone-400">
                {item.remetente} · {dataBR(item.recebido_em)}
                {item.anexos > 0 && ` · ${item.anexos} anexo(s)`}
              </p>
              <p className="mt-1.5 text-sm text-stone-600">{item.justificativa}</p>
            </div>
            <div className="flex shrink-0 items-center gap-3">
              <span className="text-xs tabular-nums text-stone-400">
                {Math.round(item.confianca * 100)}%
              </span>
              <button
                onClick={() => reclassificar(item.email_id)}
                disabled={ocupado === item.email_id}
                className="rounded-md border border-stone-300 px-2.5 py-1 text-xs font-medium text-stone-700 transition hover:border-stone-400 hover:bg-stone-50 disabled:opacity-50"
              >
                É uma conta
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
