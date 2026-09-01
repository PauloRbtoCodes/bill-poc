"use client";

/**
 * Tela 3 — Agenda de pagamento.
 *
 * Aqui o Finance Partner sai do sistema. O fluxo real é: copiar a linha digitável, ir ao
 * internet banking, agendar, voltar e registrar o protocolo. A tela é desenhada para
 * essa ida e volta — um botão de copiar por linha, e um formulário curto para trazer de
 * volta o que o banco devolveu.
 *
 * O sistema não paga nada. Ele registra que um humano pagou, com banco, data e
 * protocolo — que é o que permite reconciliar depois.
 */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, brl, dataBR, type ItemAgenda } from "@/lib/api";

const BANCOS = ["Itaú", "Bradesco", "Banco do Brasil", "Santander", "Nubank", "Inter", "BTG", "Outro"];

export default function Agenda() {
  const [itens, setItens] = useState<ItemAgenda[]>([]);
  // 30 dias por padrão: cobre o ciclo mensal de contas a pagar. Sete dias é útil no dia
  // de fechar pagamentos, mas como padrão esconde quase tudo e a tela parece vazia.
  const [janela, setJanela] = useState<7 | 30 | 0>(30);
  const [carregando, setCarregando] = useState(true);

  const carregar = useCallback(async () => {
    setItens(await api.agenda());
    setCarregando(false);
  }, []);

  useEffect(() => {
    carregar();
  }, [carregar]);

  const visiveis = janela === 0 ? itens : itens.filter((i) => (i.dias_para_vencer ?? 999) <= janela);
  const total = visiveis.reduce((s, i) => s + i.valor_centavos, 0);

  // Agrupa por data de vencimento: é assim que se agenda no banco, um dia por vez.
  const porData = visiveis.reduce<Record<string, ItemAgenda[]>>((acc, item) => {
    const chave = item.data_vencimento ?? "sem-data";
    (acc[chave] ??= []).push(item);
    return acc;
  }, {});

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-6">
        <div>
          <p className="label-sm text-outline">Agenda de pagamento</p>
          <h1 className="headline-lg mt-1 grad-text">{brl(total)} a agendar</h1>
          <p className="mt-2 text-on-surface-variant">
            {visiveis.length} conta(s) aprovada(s)
          </p>
        </div>

        <div className="flex items-center gap-3">
          <Exportar janela={janela} habilitado={visiveis.length > 0} />
          <div className="glass inline-flex gap-1 rounded-full p-1 text-sm">
            {([7, 30, 0] as const).map((d) => (
              <button
                key={d}
                onClick={() => setJanela(d)}
                className={`rounded-full px-4 py-1.5 font-medium transition ${
                  janela === d ? "text-mist-white" : "text-on-surface-variant hover:text-mist-white"
                }`}
                style={
                  janela === d
                    ? {
                        background:
                          "linear-gradient(135deg,var(--color-electric-indigo),var(--color-soft-lilac))",
                        boxShadow: "0 0 18px -4px rgba(75,57,239,.6)",
                      }
                    : undefined
                }
              >
                {d === 0 ? "Todas" : `${d} dias`}
              </button>
            ))}
          </div>
        </div>
      </header>

      {carregando ? (
        <p className="text-sm text-outline">Carregando…</p>
      ) : visiveis.length === 0 ? (
        <div className="glass rounded-lg p-12 text-center">
          {itens.length > 0 ? (
            // Distinguir "não há nada" de "o filtro escondeu tudo" — sem isso a tela
            // parece quebrada quando na verdade só não há vencimento próximo.
            <>
              <p className="text-sm text-on-surface-variant">
                Nenhuma conta vence nos próximos {janela} dias.
              </p>
              <button
                onClick={() => setJanela(0)}
                className="mt-3 text-sm text-primary underline underline-offset-4"
              >
                Ver as {itens.length} conta(s) aprovada(s)
              </button>
            </>
          ) : (
            <>
              <p className="text-sm text-on-surface-variant">
                Nada aprovado aguardando agendamento.
              </p>
              <Link
                href="/"
                className="mt-3 inline-block text-sm text-primary underline underline-offset-4"
              >
                Ver a caixa de entrada
              </Link>
            </>
          )}
        </div>
      ) : (
        <div className="space-y-8">
          {Object.entries(porData)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([data, contas]) => (
              <div key={data}>
                <div className="mb-3 flex flex-wrap items-baseline gap-3">
                  <h2 className="headline-md text-[18px] text-mist-white">
                    {data === "sem-data" ? "Sem vencimento" : dataBR(data)}
                  </h2>
                  <span className="text-xs text-outline">
                    {contas.length} conta(s) ·{" "}
                    {brl(contas.reduce((s, c) => s + c.valor_centavos, 0))}
                  </span>
                  {contas[0]?.dias_para_vencer !== null && contas[0].dias_para_vencer <= 2 && (
                    <span className="chip border-error/35 bg-error/14 text-error">
                      {contas[0].dias_para_vencer < 0
                        ? "vencida"
                        : contas[0].dias_para_vencer === 0
                          ? "vence hoje"
                          : `${contas[0].dias_para_vencer} dia(s)`}
                    </span>
                  )}
                </div>
                <div className="space-y-2">
                  {contas.map((item) => (
                    <LinhaPagamento key={item.id} item={item} aoAgendar={carregar} />
                  ))}
                </div>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}

/**
 * Exportação em lote.
 *
 * O copiar-e-colar por linha resolve três contas. Trinta é o volume de um cliente
 * pequeno de verdade, e aí o caminho é o arquivo: CNAB sobe no banco e agenda o lote
 * inteiro, o CSV vai para o contador, o layout de ERP entra no Conta Azul/Omie.
 */
function Exportar({ janela, habilitado }: { janela: number; habilitado: boolean }) {
  const [aberto, setAberto] = useState(false);
  const query = janela === 0 ? "" : `&dias=${janela}`;

  const opcoes = [
    { formato: "cnab", titulo: "Remessa CNAB 240", descricao: "para subir no internet banking" },
    { formato: "csv", titulo: "Planilha (CSV)", descricao: "Excel e Google Sheets" },
    { formato: "erp", titulo: "Layout de ERP", descricao: "Conta Azul / Omie" },
  ];

  return (
    <div className="relative">
      <button
        onClick={() => setAberto((a) => !a)}
        disabled={!habilitado}
        className="btn-ghost px-4 py-2 text-sm"
      >
        Exportar ▾
      </button>
      {aberto && habilitado && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setAberto(false)} />
          <div className="glass-strong absolute right-0 z-20 mt-2 w-72 overflow-hidden rounded-md">
            {opcoes.map((o) => (
              <a
                key={o.formato}
                href={`/api/agenda/exportar?formato=${o.formato}${query}`}
                onClick={() => setAberto(false)}
                className="block border-b border-white/6 px-4 py-3 text-left transition last:border-0 hover:bg-white/8"
              >
                <span className="block text-sm font-medium text-mist-white">{o.titulo}</span>
                <span className="block text-xs text-outline">{o.descricao}</span>
              </a>
            ))}
            <p className="bg-black/25 px-4 py-2.5 text-[11px] leading-snug text-outline">
              O CNAB inclui só contas com boleto. Pix e transferência continuam no fluxo
              manual, e seguem listados aqui.
            </p>
          </div>
        </>
      )}
    </div>
  );
}

function LinhaPagamento({ item, aoAgendar }: { item: ItemAgenda; aoAgendar: () => void }) {
  const [aberto, setAberto] = useState(false);
  const codigo = item.linha_digitavel ?? item.pix_copia_e_cola ?? "";

  return (
    <div className="glass glass-hover rounded-md px-5 py-4">
      <div className="flex flex-wrap items-start gap-4">
        <div className="min-w-0 flex-1">
          <Link
            href={`/conta/${item.id}`}
            className="font-medium text-mist-white transition hover:text-primary"
          >
            {item.fornecedor ?? "—"}
          </Link>
          <p className="mt-0.5 text-xs text-outline">
            {item.cnpj ?? "sem CNPJ"}
            {item.numero_documento && ` · doc ${item.numero_documento}`}
            {item.forma_pagamento && ` · ${item.forma_pagamento.replace(/_/g, " ")}`}
          </p>
        </div>
        <span className="headline-md text-[18px] text-mist-white">{brl(item.valor_centavos)}</span>
        <button
          onClick={() => setAberto((a) => !a)}
          className={`${aberto ? "btn-ghost" : "btn-primary"} px-4 py-2 text-xs`}
        >
          {aberto ? "Fechar" : "Agendar"}
        </button>
      </div>

      {codigo && (
        <div className="mt-3">
          <Copiavel texto={codigo} />
        </div>
      )}

      {aberto && <FormAgendamento item={item} aoAgendar={aoAgendar} />}
    </div>
  );
}

function Copiavel({ texto }: { texto: string }) {
  const [copiado, setCopiado] = useState(false);
  return (
    <div className="flex items-start gap-2">
      <code className="min-w-0 flex-1 break-all rounded bg-black/30 px-3 py-2 text-xs text-on-surface-variant">
        {texto.length > 120 ? `${texto.slice(0, 120)}…` : texto}
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

function FormAgendamento({ item, aoAgendar }: { item: ItemAgenda; aoAgendar: () => void }) {
  const [data, setData] = useState(item.data_vencimento ?? "");
  const [banco, setBanco] = useState(BANCOS[0]);
  const [protocolo, setProtocolo] = useState("");
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  async function confirmar() {
    setSalvando(true);
    setErro(null);
    try {
      await api.agendar(item.id, {
        data_agendada: data,
        banco,
        codigo_confirmacao: protocolo || undefined,
      });
      aoAgendar();
    } catch (e) {
      setErro(e instanceof Error ? e.message : String(e));
      setSalvando(false);
    }
  }

  return (
    <div className="mt-4 rounded-md bg-black/25 p-4">
      <p className="mb-3 text-xs text-outline">
        Agende no banco e registre aqui o que aconteceu. O protocolo é o que permite
        reconciliar depois.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-xs text-outline">
          Data agendada
          <input
            type="date"
            value={data}
            onChange={(e) => setData(e.target.value)}
            className="field mt-1.5 block"
          />
        </label>
        <label className="text-xs text-outline">
          Banco
          <select
            value={banco}
            onChange={(e) => setBanco(e.target.value)}
            className="field mt-1.5 block"
          >
            {BANCOS.map((b) => (
              <option key={b}>{b}</option>
            ))}
          </select>
        </label>
        <label className="text-xs text-outline">
          Protocolo do banco
          <input
            value={protocolo}
            onChange={(e) => setProtocolo(e.target.value)}
            placeholder="opcional"
            className="field mt-1.5 block"
          />
        </label>
        <button
          onClick={confirmar}
          disabled={salvando || !data}
          className="btn-primary px-4 py-2 text-sm"
        >
          Marcar como agendado
        </button>
      </div>
      {erro && <p className="mt-2 text-xs text-error">{erro}</p>}
    </div>
  );
}
