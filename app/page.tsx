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
      <div className="glass rounded-lg p-6" style={{ borderColor: "rgba(255,180,171,.3)" }}>
        <p className="label-sm text-error">Falha de conexão</p>
        <p className="mt-2 text-sm text-on-surface">Não consegui falar com a API.</p>
        <pre className="mt-3 overflow-auto rounded bg-black/30 p-3 text-xs text-on-surface-variant">
          {erro}
        </pre>
      </div>
    );

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-6">
        <div>
          <p className="label-sm text-outline">Caixa de entrada</p>
          <h1 className="headline-lg mt-1 grad-text">
            {fila.length} cobrança{fila.length === 1 ? "" : "s"} aguardando
          </h1>
          <p className="mt-2 text-on-surface-variant">
            {brl(total)} no total · {ruido.length} e-mail(s) descartados como ruído
          </p>
        </div>
        <Sincronizar aoTerminar={carregar} />
      </header>

      <div className="glass inline-flex gap-1 rounded-full p-1 text-sm">
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

      {carregando ? (
        <p className="text-sm text-outline">Carregando…</p>
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
      setTimeout(() => setProgresso(null), 5000);
    }
  }

  const total = progresso ? progresso.feitos + progresso.faltam : 0;
  const pct = total > 0 ? (progresso!.feitos / total) * 100 : 0;

  return (
    <div className="flex min-w-64 flex-col items-end gap-2">
      <button
        onClick={rodando ? () => (cancelar.current = true) : sincronizar}
        className={`${rodando ? "btn-ghost" : "btn-primary"} px-5 py-2.5 text-sm`}
      >
        {rodando ? "Parar sincronização" : "Buscar novos e-mails"}
      </button>

      {progresso && (
        <div className="w-full max-w-72">
          <div className="bar-track">
            <div
              className="bar-fill bar-glow"
              style={{
                width: `${rodando ? pct : 100}%`,
                background: "linear-gradient(90deg,var(--color-electric-indigo),var(--color-soft-lilac))",
                color: "var(--color-soft-lilac)",
              }}
            />
          </div>
          <p className="mt-1.5 truncate text-right text-xs text-outline">
            {rodando ? (
              <>
                {progresso.feitos} processado(s)
                {progresso.faltam > 0 && ` · ${progresso.faltam} na fila`}
                {progresso.atual && ` · ${progresso.atual.slice(0, 30)}`}
              </>
            ) : (
              <span className="text-primary">{progresso.feitos} e-mail(s) processado(s)</span>
            )}
          </p>
        </div>
      )}

      {erro && (
        <p className="max-w-72 truncate text-right text-xs text-error" title={erro}>
          {erro}
        </p>
      )}
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
      className={`flex items-center gap-2 rounded-full px-4 py-1.5 font-medium transition ${
        ativa ? "text-mist-white" : "text-on-surface-variant hover:text-mist-white"
      }`}
      style={
        ativa
          ? {
              background: "linear-gradient(135deg,var(--color-electric-indigo),var(--color-soft-lilac))",
              boxShadow: "0 0 18px -4px rgba(75,57,239,.6)",
            }
          : undefined
      }
    >
      {children}
      <span className={`text-xs ${ativa ? "text-mist-white/75" : "text-outline"}`}>{contagem}</span>
    </button>
  );
}

function ListaCobrancas({ itens, faixa }: { itens: ItemFila[]; faixa: "revisar" | "auto_ok" }) {
  if (itens.length === 0)
    return (
      <p className="glass rounded-lg p-12 text-center text-sm text-outline">
        {faixa === "revisar" ? "Nada pendente de revisão." : "Nada na faixa rápida."}
      </p>
    );

  return (
    <div className="space-y-2">
      {itens.map((item) => (
        <Link
          key={item.id}
          href={`/conta/${item.id}`}
          className="glass glass-hover block rounded-md px-5 py-4"
        >
          <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-mist-white">{item.fornecedor ?? "—"}</span>
                {item.recorrencia === "recorrente" && (
                  <span className="chip border-soft-lilac/35 bg-soft-lilac/16 text-soft-lilac">
                    recorrente
                  </span>
                )}
                {item.urgente && (
                  <span className="chip border-error/35 bg-error/14 text-error">urgente</span>
                )}
              </div>
              <p className="mt-1 truncate text-xs text-outline">{item.email_assunto}</p>
            </div>

            <div className="text-right">
              <p className="headline-md text-[19px] text-mist-white">{brl(item.valor_centavos)}</p>
              <p className="mt-0.5 text-xs text-outline">vence {dataBR(item.data_vencimento)}</p>
            </div>

            <div className="w-32">
              <Confianca valor={item.confianca_geral} />
            </div>

            <div className="w-52 text-xs">
              {item.falhas_bloqueantes > 0 ? (
                <span className="text-tertiary">
                  {item.falhas_bloqueantes} conferência(s) não fecharam
                </span>
              ) : item.alertas > 0 ? (
                <span className="text-on-surface-variant">{item.alertas} alerta(s)</span>
              ) : (
                <span className="text-primary">tudo conferido</span>
              )}
            </div>
          </div>
        </Link>
      ))}
    </div>
  );
}

/** Barra de confiança. Cor por faixa porque número solto ninguém interpreta rápido. */
function Confianca({ valor }: { valor: number | null }) {
  if (valor === null) return <span className="text-xs text-outline">—</span>;
  const pct = Math.round(valor * 100);
  const cor =
    pct >= 90 ? "var(--color-primary)" : pct >= 70 ? "var(--color-tertiary)" : "var(--color-error)";
  return (
    <div className="flex items-center gap-2">
      <div className="bar-track flex-1">
        <div className="bar-fill" style={{ width: `${pct}%`, background: cor }} />
      </div>
      <span className="text-xs text-outline">{pct}%</span>
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
      <p className="glass rounded-lg p-12 text-center text-sm text-outline">
        Nenhum e-mail descartado.
      </p>
    );

  return (
    <div className="space-y-4">
      <p className="max-w-3xl text-sm text-on-surface-variant">
        O que a triagem descartou fica visível com o motivo. Um falso negativo aqui é uma
        conta perdida, e conta perdida vira multa — então nada é descartado em silêncio.
      </p>
      <div className="space-y-2">
        {itens.map((item) => (
          <div key={item.email_id} className="glass flex items-start gap-4 rounded-md px-5 py-4">
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-on-surface">{item.assunto}</p>
              <p className="mt-0.5 text-xs text-outline">
                {item.remetente} · {dataBR(item.recebido_em)}
                {item.anexos > 0 && ` · ${item.anexos} anexo(s)`}
              </p>
              <p className="mt-2 text-sm text-on-surface-variant">{item.justificativa}</p>
            </div>
            <div className="flex shrink-0 items-center gap-3">
              <span className="text-xs text-outline">{Math.round(item.confianca * 100)}%</span>
              <button
                onClick={() => reclassificar(item.email_id)}
                disabled={ocupado === item.email_id}
                className="btn-ghost px-3 py-1.5 text-xs"
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
