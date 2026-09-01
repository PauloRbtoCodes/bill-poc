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
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Agenda de pagamento</h1>
          <p className="mt-1 text-sm text-stone-500">
            {visiveis.length} conta(s) aprovada(s) · {brl(total)} a agendar
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Exportar janela={janela} habilitado={visiveis.length > 0} />
          <div className="flex gap-1 rounded-lg bg-stone-100 p-1 text-sm">
            {([7, 30, 0] as const).map((d) => (
              <button
                key={d}
                onClick={() => setJanela(d)}
                className={`rounded-md px-3 py-1.5 font-medium transition ${
                  janela === d ? "bg-white text-stone-900 shadow-sm" : "text-stone-500 hover:text-stone-800"
                }`}
              >
                {d === 0 ? "Todas" : `${d} dias`}
              </button>
            ))}
          </div>
        </div>
      </div>

      {carregando ? (
        <p className="text-sm text-stone-400">Carregando…</p>
      ) : visiveis.length === 0 ? (
        <div className="rounded-lg border border-dashed border-stone-300 p-10 text-center">
          {itens.length > 0 ? (
            // Distinguir "não há nada" de "o filtro escondeu tudo" — sem isso a tela
            // parece quebrada quando na verdade só não há vencimento próximo.
            <>
              <p className="text-sm text-stone-500">
                Nenhuma conta vence nos próximos {janela} dias.
              </p>
              <button
                onClick={() => setJanela(0)}
                className="mt-2 text-sm text-stone-700 underline underline-offset-2"
              >
                Ver as {itens.length} conta(s) aprovada(s)
              </button>
            </>
          ) : (
            <>
              <p className="text-sm text-stone-500">Nada aprovado aguardando agendamento.</p>
              <Link href="/" className="mt-2 inline-block text-sm text-stone-700 underline underline-offset-2">
                Ver a caixa de entrada
              </Link>
            </>
          )}
        </div>
      ) : (
        <div className="space-y-6">
          {Object.entries(porData)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([data, contas]) => (
              <div key={data}>
                <div className="mb-2 flex items-baseline gap-3">
                  <h2 className="text-sm font-semibold text-stone-700">
                    {data === "sem-data" ? "Sem vencimento" : dataBR(data)}
                  </h2>
                  <span className="text-xs text-stone-400">
                    {contas.length} conta(s) ·{" "}
                    {brl(contas.reduce((s, c) => s + c.valor_centavos, 0))}
                  </span>
                  {contas[0]?.dias_para_vencer !== null && contas[0].dias_para_vencer <= 2 && (
                    <span className="rounded bg-red-50 px-1.5 py-0.5 text-[11px] font-medium text-red-700 ring-1 ring-red-200">
                      {contas[0].dias_para_vencer < 0
                        ? "vencida"
                        : contas[0].dias_para_vencer === 0
                          ? "vence hoje"
                          : `${contas[0].dias_para_vencer} dia(s)`}
                    </span>
                  )}
                </div>
                <div className="divide-y divide-stone-100 overflow-hidden rounded-lg border border-stone-200 bg-white">
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
        className="rounded-md border border-stone-300 px-3 py-1.5 text-sm font-medium text-stone-700 transition hover:bg-stone-50 disabled:opacity-40"
      >
        Exportar ▾
      </button>
      {aberto && habilitado && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setAberto(false)} />
          <div className="absolute right-0 z-20 mt-1 w-64 overflow-hidden rounded-lg border border-stone-200 bg-white shadow-lg">
            {opcoes.map((o) => (
              <a
                key={o.formato}
                href={`/api/agenda/exportar?formato=${o.formato}${query}`}
                onClick={() => setAberto(false)}
                className="block border-b border-stone-100 px-3 py-2.5 text-left transition last:border-0 hover:bg-stone-50"
              >
                <span className="block text-sm font-medium text-stone-800">{o.titulo}</span>
                <span className="block text-xs text-stone-400">{o.descricao}</span>
              </a>
            ))}
            <p className="bg-stone-50 px-3 py-2 text-[11px] leading-snug text-stone-400">
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
    <div className="p-4">
      <div className="flex flex-wrap items-start gap-4">
        <div className="min-w-0 flex-1">
          <Link href={`/conta/${item.id}`} className="text-sm font-medium text-stone-900 hover:underline">
            {item.fornecedor ?? "—"}
          </Link>
          <p className="mt-0.5 text-xs text-stone-400">
            {item.cnpj ?? "sem CNPJ"}
            {item.numero_documento && ` · doc ${item.numero_documento}`}
            {item.forma_pagamento && ` · ${item.forma_pagamento.replace(/_/g, " ")}`}
          </p>
        </div>
        <span className="text-sm font-medium tnum">{brl(item.valor_centavos)}</span>
        <button
          onClick={() => setAberto((a) => !a)}
          className="rounded-md bg-stone-900 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-stone-800"
        >
          {aberto ? "Fechar" : "Agendar"}
        </button>
      </div>

      {codigo && (
        <div className="mt-2">
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
      <code className="min-w-0 flex-1 break-all rounded bg-stone-50 px-2 py-1.5 text-xs text-stone-600 tnum">
        {texto.length > 120 ? `${texto.slice(0, 120)}…` : texto}
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
    <div className="mt-3 rounded-lg bg-stone-50 p-3">
      <p className="mb-2.5 text-xs text-stone-500">
        Agende no banco e registre aqui o que aconteceu. O protocolo é o que permite
        reconciliar depois.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-xs text-stone-500">
          Data agendada
          <input
            type="date"
            value={data}
            onChange={(e) => setData(e.target.value)}
            className="mt-1 block rounded border border-stone-300 px-2 py-1 text-sm focus:border-stone-500 focus:outline-none"
          />
        </label>
        <label className="text-xs text-stone-500">
          Banco
          <select
            value={banco}
            onChange={(e) => setBanco(e.target.value)}
            className="mt-1 block rounded border border-stone-300 px-2 py-1 text-sm focus:border-stone-500 focus:outline-none"
          >
            {BANCOS.map((b) => (
              <option key={b}>{b}</option>
            ))}
          </select>
        </label>
        <label className="text-xs text-stone-500">
          Protocolo do banco
          <input
            value={protocolo}
            onChange={(e) => setProtocolo(e.target.value)}
            placeholder="opcional"
            className="mt-1 block rounded border border-stone-300 px-2 py-1 text-sm focus:border-stone-500 focus:outline-none"
          />
        </label>
        <button
          onClick={confirmar}
          disabled={salvando || !data}
          className="rounded-md bg-stone-900 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-stone-800 disabled:opacity-50"
        >
          Marcar como agendado
        </button>
      </div>
      {erro && <p className="mt-2 text-xs text-red-600">{erro}</p>}
    </div>
  );
}
