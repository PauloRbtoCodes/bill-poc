/**
 * Cliente da API e os tipos que a UI consome.
 *
 * Os nomes vêm do backend em português — o mesmo vocabulário do domínio aparece no
 * schema, no pipeline e na tela. Traduzir no meio do caminho só criaria dois nomes
 * para a mesma coisa.
 */

export type Origem =
  | "codigo_barras"
  | "nfe_xml"
  | "chave_nfe"
  | "pix"
  | "regex"
  | "llm"
  | "humano"
  | "historico";

export type Severidade = "bloqueante" | "alerta" | "info";

export interface ItemFila {
  id: string;
  status: string;
  faixa: "auto_ok" | "revisar";
  confianca_geral: number | null;
  fornecedor: string | null;
  cnpj: string | null;
  valor_centavos: number;
  data_vencimento: string | null;
  numero_documento: string | null;
  recorrencia: "unico" | "recorrente";
  email_assunto: string | null;
  email_remetente: string | null;
  recebido_em: string;
  falhas_bloqueantes: number;
  alertas: number;
  urgente: boolean;
}

export interface Campo {
  campo: string;
  valor_texto: string | null;
  valor_normalizado: string | null;
  origem: Origem;
  confianca: number;
  evidencia: string | null;
}

export interface Verificacao {
  check_nome: string;
  passou: boolean;
  severidade: Severidade;
  esperado: string | null;
  encontrado: string | null;
  mensagem: string | null;
}

export interface Instrumento {
  id: string;
  tipo: string;
  linha_digitavel: string | null;
  codigo_barras: string | null;
  pix_copia_e_cola: string | null;
  decodificado: Record<string, unknown>;
}

export interface AcaoHistorico {
  acao: string;
  campo: string | null;
  valor_anterior: string | null;
  valor_novo: string | null;
  observacao: string | null;
  criado_em: string;
}

export interface Detalhe extends ItemFila {
  descricao: string | null;
  tipo_documento: string;
  data_emissao: string | null;
  categoria_codigo: string | null;
  chave_nfe: string | null;
  document_id: string | null;
  nome_arquivo: string | null;
  documento_tipo: string | null;
  email_corpo: string | null;
  campos: Campo[];
  verificacoes: Verificacao[];
  instrumentos: Instrumento[];
  historico: AcaoHistorico[];
}

export interface ItemAgenda {
  id: string;
  fornecedor: string | null;
  cnpj: string | null;
  valor_centavos: number;
  data_vencimento: string | null;
  numero_documento: string | null;
  forma_pagamento: string | null;
  linha_digitavel: string | null;
  pix_copia_e_cola: string | null;
  dias_para_vencer: number | null;
}

async function req<T>(caminho: string, init?: RequestInit): Promise<T> {
  const resposta = await fetch(`/api${caminho}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!resposta.ok) {
    const corpo = await resposta.text();
    throw new Error(corpo || `${resposta.status} ${resposta.statusText}`);
  }
  return resposta.json();
}

export interface ResultadoSync {
  processados: number;
  restantes: number;
  concluido: boolean;
  ultimo: string | null;
  faixa: string | null;
  e_ruido: boolean;
  erro: string | null;
}

export const api = {
  fila: () => req<ItemFila[]>("/fila"),
  sync: (lote = 1) => req<ResultadoSync>(`/sync?lote=${lote}`, { method: "POST" }),
  detalhe: (id: string) => req<Detalhe>(`/payables/${id}`),
  agenda: () => req<ItemAgenda[]>("/agenda"),
  editar: (id: string, campo: string, valor: string) =>
    req<Detalhe>(`/payables/${id}/campos/${campo}`, {
      method: "PATCH",
      body: JSON.stringify({ valor }),
    }),
  aprovar: (id: string, observacao?: string) =>
    req<Detalhe>(`/payables/${id}/aprovar`, {
      method: "POST",
      body: JSON.stringify({ observacao: observacao ?? null }),
    }),
  rejeitar: (id: string, observacao?: string) =>
    req<Detalhe>(`/payables/${id}/rejeitar`, {
      method: "POST",
      body: JSON.stringify({ observacao: observacao ?? null }),
    }),
  reabrir: (id: string) => req<Detalhe>(`/payables/${id}/reabrir`, { method: "POST" }),
  agendar: (id: string, dados: { data_agendada: string; banco: string; codigo_confirmacao?: string }) =>
    req<Detalhe>(`/payables/${id}/agendar`, { method: "POST", body: JSON.stringify(dados) }),
};

// ---------------------------------------------------------------------------------
// Formatação
// ---------------------------------------------------------------------------------

export const brl = (centavos: number | null | undefined) =>
  ((centavos ?? 0) / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

export const dataBR = (iso: string | null | undefined) =>
  iso ? new Date(`${iso.slice(0, 10)}T12:00:00`).toLocaleDateString("pt-BR") : "—";

export const DETERMINISTICAS: Origem[] = ["codigo_barras", "nfe_xml", "chave_nfe", "pix"];

/**
 * O selo que aparece ao lado de cada campo. É a informação mais importante da tela:
 * distingue um valor que foi *conferido* por aritmética de um que foi *lido* por um
 * modelo. O revisor precisa saber, em um relance, no que pode confiar.
 */
export function selo(origem: Origem): { icone: string; rotulo: string; classe: string } {
  if (DETERMINISTICAS.includes(origem)) {
    return {
      icone: "🔒",
      rotulo: { codigo_barras: "código de barras", nfe_xml: "XML da NF-e", chave_nfe: "chave da NF-e", pix: "Pix" }[
        origem as "codigo_barras" | "nfe_xml" | "chave_nfe" | "pix"
      ],
      classe: "bg-emerald-50 text-emerald-800 ring-emerald-200",
    };
  }
  if (origem === "humano")
    return { icone: "✏️", rotulo: "corrigido por humano", classe: "bg-violet-50 text-violet-800 ring-violet-200" };
  if (origem === "historico")
    return { icone: "📊", rotulo: "histórico do fornecedor", classe: "bg-sky-50 text-sky-800 ring-sky-200" };
  return { icone: "🤖", rotulo: "leitura do modelo", classe: "bg-amber-50 text-amber-900 ring-amber-200" };
}

export const ROTULOS_CAMPO: Record<string, string> = {
  valor: "Valor",
  data_vencimento: "Vencimento",
  data_emissao: "Emissão",
  cnpj: "CNPJ",
  beneficiario: "Beneficiário",
  numero_documento: "Nº do documento",
  categoria: "Categoria",
  recorrencia: "Recorrência",
};

/** Campos que se pode corrigir na tela, e como validar o que o revisor digitar. */
export const EDITAVEIS: Record<string, { tipo: "texto" | "data" | "dinheiro"; dica?: string }> = {
  valor: { tipo: "dinheiro", dica: "1234.56" },
  data_vencimento: { tipo: "data" },
  data_emissao: { tipo: "data" },
  numero_documento: { tipo: "texto" },
};
