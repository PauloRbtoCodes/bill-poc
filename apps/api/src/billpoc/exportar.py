"""Exportação da agenda de pagamento.

O copiar-e-colar da linha digitável resolve três contas. Não resolve trinta — e "trinta
contas por semana" é o volume de um cliente pequeno de verdade. Estes três formatos são
o próximo passo natural do fluxo, e cada um serve a um destino diferente:

- **CSV** — o denominador comum. Toda planilha e todo ERP importam, e é o que o Finance
  Partner manda para o contador.
- **CNAB 240** — remessa de pagamento para o banco, formato FEBRABAN. É o que substitui
  o agendamento manual conta a conta: sobe um arquivo e o banco agenda o lote inteiro.
- **Conta Azul / Omie** — o layout de lançamentos a pagar dos ERPs citados no desafio.

Nota honesta sobre o CNAB: o layout tem variações por banco (cada um publica seu manual
de campos do segmento livre), e o arquivo aqui é gerado no layout FEBRABAN genérico. Para
produção, cada banco atendido precisa de validação contra o manual dele e um teste de
homologação. O que está aqui é a estrutura correta, não um arquivo homologado.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from .validate.tempo import hoje as hoje_brasil


@dataclass(frozen=True)
class Pagamento:
    """O que a agenda precisa expor para virar arquivo."""

    fornecedor: str
    cnpj: str | None
    valor_centavos: int
    vencimento: date | None
    documento: str | None
    linha_digitavel: str | None
    pix: str | None

    @classmethod
    def da_agenda(cls, linha: dict[str, Any]) -> Pagamento:
        return cls(
            fornecedor=linha.get("fornecedor") or "(sem fornecedor)",
            cnpj=linha.get("cnpj"),
            valor_centavos=int(linha.get("valor_centavos") or 0),
            vencimento=linha.get("data_vencimento"),
            documento=linha.get("numero_documento"),
            linha_digitavel=linha.get("linha_digitavel"),
            pix=linha.get("pix_copia_e_cola"),
        )


# --------------------------------------------------------------------------------------
# CSV
# --------------------------------------------------------------------------------------


def para_csv(pagamentos: list[Pagamento]) -> str:
    """CSV em português, separado por ponto e vírgula e com vírgula decimal.

    É o dialeto que o Excel brasileiro abre sem perguntar nada — abrir um CSV e ver
    `1234.56` virar data é um jeito clássico de perder confiança na ferramenta.
    """
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=";", lineterminator="\r\n")
    escritor.writerow(
        ["Fornecedor", "CNPJ", "Documento", "Vencimento", "Valor", "Linha digitável", "Pix"]
    )
    for p in pagamentos:
        escritor.writerow([
            p.fornecedor,
            p.cnpj or "",
            p.documento or "",
            p.vencimento.strftime("%d/%m/%Y") if p.vencimento else "",
            f"{Decimal(p.valor_centavos) / 100:.2f}".replace(".", ","),
            p.linha_digitavel or "",
            p.pix or "",
        ])
    return saida.getvalue()


def para_erp(pagamentos: list[Pagamento]) -> str:
    """Layout de contas a pagar no formato que Conta Azul e Omie importam."""
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=";", lineterminator="\r\n")
    escritor.writerow([
        "Descrição", "Valor", "Data de vencimento", "Cliente/Fornecedor",
        "CPF/CNPJ", "Categoria", "Observações",
    ])
    for p in pagamentos:
        escritor.writerow([
            f"{p.fornecedor}{f' — doc {p.documento}' if p.documento else ''}",
            f"{Decimal(p.valor_centavos) / 100:.2f}".replace(".", ","),
            p.vencimento.strftime("%d/%m/%Y") if p.vencimento else "",
            p.fornecedor,
            p.cnpj or "",
            "",  # a categoria do plano de contas do cliente é mapeada no ERP
            f"Linha digitável: {p.linha_digitavel}" if p.linha_digitavel else "",
        ])
    return saida.getvalue()


# --------------------------------------------------------------------------------------
# CNAB 240
# --------------------------------------------------------------------------------------


def _campo(valor: str | int | None, tamanho: int, numerico: bool = False) -> str:
    """Campo de tamanho fixo: numérico à direita com zeros, alfa à esquerda com espaços."""
    if valor is None:
        valor = 0 if numerico else ""
    texto = str(valor)
    if numerico:
        texto = "".join(c for c in texto if c.isdigit())
        return texto[-tamanho:].rjust(tamanho, "0")
    return texto[:tamanho].ljust(tamanho)


# Cada registro é declarado como uma lista de (nome, tamanho, numérico?). Escrever o
# layout assim, e não como uma sequência de chamadas, é o que torna possível conferir
# contra o manual da FEBRABAN linha a linha — e faz o total de 240 ser verificável por
# construção em vez de por contagem manual, que foi exatamente onde eu errei primeiro.
_HEADER_ARQUIVO = [
    ("banco", 3, True), ("lote", 4, True), ("registro", 1, True), ("cnab", 9, False),
    ("tipo_inscricao", 1, True), ("cnpj", 14, True), ("convenio", 20, False),
    ("agencia", 5, True), ("dv_agencia", 1, False), ("conta", 12, True),
    ("dv_conta", 1, False), ("dv_ag_conta", 1, False), ("empresa", 30, False),
    ("nome_banco", 30, False), ("cnab2", 10, False), ("codigo_remessa", 1, True),
    ("data_geracao", 8, True), ("hora_geracao", 6, True), ("sequencial", 6, True),
    ("layout", 3, True), ("densidade", 5, True), ("reservado_banco", 20, False),
    ("reservado_empresa", 20, False), ("cnab3", 29, False),
]

_HEADER_LOTE = [
    ("banco", 3, True), ("lote", 4, True), ("registro", 1, True), ("operacao", 1, False),
    ("servico", 2, True), ("forma_lancamento", 2, True), ("layout_lote", 3, True),
    ("cnab", 1, False), ("tipo_inscricao", 1, True), ("cnpj", 14, True),
    ("convenio", 20, False), ("agencia", 5, True), ("dv_agencia", 1, False),
    ("conta", 12, True), ("dv_conta", 1, False), ("dv_ag_conta", 1, False),
    ("empresa", 30, False), ("mensagem", 40, False), ("endereco", 30, False),
    ("numero", 5, True), ("complemento", 15, False), ("cidade", 20, False),
    ("cep", 8, True), ("uf", 2, False), ("cnab2", 8, False), ("ocorrencias", 10, False),
]

_SEGMENTO_J = [
    ("banco", 3, True), ("lote", 4, True), ("registro", 1, True),
    ("sequencial", 5, True), ("segmento", 1, False), ("cnab", 1, False),
    ("movimento", 2, True), ("codigo_barras", 44, True), ("beneficiario", 30, False),
    ("vencimento", 8, True), ("valor_titulo", 15, True), ("desconto", 15, True),
    ("acrescimo", 15, True), ("data_pagamento", 8, True), ("valor_pagamento", 15, True),
    ("quitacao", 15, True), ("seu_numero", 20, False), ("nosso_numero", 20, False),
    ("moeda", 2, True), ("cnab2", 6, False), ("ocorrencias", 10, False),
]

_TRAILER_LOTE = [
    ("banco", 3, True), ("lote", 4, True), ("registro", 1, True), ("cnab", 9, False),
    ("qtd_registros", 6, True), ("soma_valores", 18, True), ("soma_moeda", 18, True),
    ("aviso", 6, True), ("cnab2", 165, False), ("ocorrencias", 10, False),
]

_TRAILER_ARQUIVO = [
    ("banco", 3, True), ("lote", 4, True), ("registro", 1, True), ("cnab", 9, False),
    ("qtd_lotes", 6, True), ("qtd_registros", 6, True), ("qtd_contas", 6, True),
    ("cnab2", 205, False),
]


def _montar(layout: list[tuple[str, int, bool]], valores: dict[str, object]) -> str:
    """Monta um registro a partir do layout, e garante os 240 caracteres.

    Um CNAB com registro de tamanho errado é rejeitado inteiro pelo banco. Falhar aqui,
    com o nome do layout, é muito melhor que descobrir na importação.
    """
    linha = "".join(
        _campo(valores.get(nome), tamanho, numerico) for nome, tamanho, numerico in layout
    )
    if len(linha) != 240:
        soma = sum(t for _, t, _ in layout)
        raise ValueError(
            f"registro CNAB com {len(linha)} caracteres (layout declara {soma}), esperado 240"
        )
    return linha


def para_cnab240(
    pagamentos: list[Pagamento],
    *,
    empresa: str,
    cnpj_empresa: str,
    banco: str = "341",
    agencia: str = "0000",
    conta: str = "000000",
    data_pagamento: date | None = None,
) -> str:
    """Arquivo de remessa CNAB 240 com um lote de pagamento de títulos.

    Estrutura: header de arquivo, header de lote, um segmento J por boleto, trailer de
    lote e trailer de arquivo. Cada linha tem exatamente 240 caracteres.

    Só entram pagamentos com linha digitável — Pix e transferência usam outros segmentos
    (B e A), que não estão implementados. Quem ficar de fora é devolvido pelo chamador
    para continuar no fluxo manual, em vez de sumir do arquivo em silêncio.
    """
    from .validate.boleto import BoletoError
    from .validate.boleto import decodificar as _decodificar

    data = data_pagamento or hoje_brasil()
    agora = hoje_brasil()
    conta_bancaria = {
        "banco": banco,
        "tipo_inscricao": 2,  # 2 = CNPJ
        "cnpj": cnpj_empresa,
        "agencia": agencia,
        "conta": conta,
        "empresa": empresa,
    }
    linhas = [
        _montar(_HEADER_ARQUIVO, {
            **conta_bancaria,
            "lote": 0, "registro": 0, "nome_banco": "BANCO",
            "codigo_remessa": 1,
            "data_geracao": agora.strftime("%d%m%Y"),
            "hora_geracao": "000000",
            "sequencial": 1, "layout": 103,
        }),
        _montar(_HEADER_LOTE, {
            **conta_bancaria,
            "lote": 1, "registro": 1, "operacao": "C",
            "servico": 20,           # 20 = pagamento a fornecedor
            "forma_lancamento": 30,  # 30 = liquidação de títulos do próprio banco
            "layout_lote": 46,
        }),
    ]

    total_centavos = 0
    sequencial = 0
    for p in pagamentos:
        if not p.linha_digitavel:
            continue
        # O CNAB carrega o código de barras (44), não a linha digitável (47). Enviar a
        # linha digitável truncada em 44 seria um pagamento para outro título.
        try:
            barras = _decodificar(p.linha_digitavel).codigo_barras
        except (BoletoError, ValueError):
            continue

        sequencial += 1
        total_centavos += p.valor_centavos
        linhas.append(_montar(_SEGMENTO_J, {
            "banco": banco, "lote": 1, "registro": 3,
            "sequencial": sequencial, "segmento": "J", "movimento": 0,
            "codigo_barras": barras,
            "beneficiario": p.fornecedor,
            "vencimento": (p.vencimento or data).strftime("%d%m%Y"),
            "valor_titulo": p.valor_centavos,
            "desconto": 0, "acrescimo": 0,
            "data_pagamento": data.strftime("%d%m%Y"),
            "valor_pagamento": p.valor_centavos,
            "quitacao": 0,
            "seu_numero": p.documento,
            "moeda": 9,  # 9 = real
        }))

    linhas.append(_montar(_TRAILER_LOTE, {
        "banco": banco, "lote": 1, "registro": 5,
        "qtd_registros": sequencial + 2,  # os detalhes mais os dois registros do lote
        "soma_valores": total_centavos, "soma_moeda": 0, "aviso": 0,
    }))
    linhas.append(_montar(_TRAILER_ARQUIVO, {
        "banco": banco, "lote": 9999, "registro": 9,
        "qtd_lotes": 1,
        "qtd_registros": sequencial + 4,  # tudo, incluindo headers e trailers
        "qtd_contas": 0,
    }))

    return "\r\n".join(linhas) + "\r\n"


def sem_linha_digitavel(pagamentos: list[Pagamento]) -> list[Pagamento]:
    """Os que não cabem no CNAB e continuam no fluxo manual — Pix, transferência, link."""
    return [p for p in pagamentos if not p.linha_digitavel]
