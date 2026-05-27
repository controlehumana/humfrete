# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Como executar

```bash
py processar_frete.py
```

Isso lê os dados, processa tudo e gera `dashboard_frete.html` na raiz da pasta. Abrir o HTML diretamente no navegador — não requer servidor.

## Estrutura do projeto

```
Frete/
  processar_frete.py       # Script único de ETL + geração do dashboard
  dashboard_frete.html     # Saída gerada (não editar manualmente)
  CTe/
    LISTAGEM_FATURAMENTO*.xls   # Exportação do ERP (HTML disfarçado de .xls)
    Geral/
      Tomador/             # ~4.300 XMLs de CTe (CT-e versão 4.0)
      Eventos de cancelamento/  # XMLs de cancelamento de CTe
```

## Arquitetura do processar_frete.py

O script tem quatro etapas em sequência:

1. **`parse_faturamento()`** — lê o arquivo `.xls` (HTML com tabela) da pasta `CTe/`. O ERP exporta com `<th>` nos primeiros 40 cabeçalhos e `<td>` nos 10 restantes; `TableParser` trata isso unificando ambos como cabeçalho quando está dentro de `<thead>`. Valores numéricos usam formato brasileiro (`1.234,56`). A coluna `Chave` vem com wrapper `="..."` do Excel. Agrupa por chave de NF-e (44 dígitos), somando itens da mesma nota. Detecta linha de produto por "LINHAHUM" na coluna `DESCRICAO Item`.

2. **`parse_ctes()`** — lê todos os XMLs em `CTe/Geral/Tomador/`. Namespace: `http://www.portalfiscal.inf.br/cte`. Cada CTe pode referenciar NF-e via `infDoc/infNFe/chave` ou DCe via `infDoc/infDCe/chave` (~4% dos casos). O valor do frete está em `vPrest/vTPrest`. Retorna `cte_list` e `nfe_to_cte` (dict: chave_nfe → lista de CTe que a transportam).

3. **`cruzar()`** — join entre `nfe_map` e `nfe_to_cte` pela chave de 44 dígitos da NF-e. Para cada NF-e vinculada, calcula:
   - Frete Linhahum e Humana Alimentar proporcionalmente ao valor de cada linha na NF-e
   - `frete_cobrado` = `vlr_frete_nf` (campo "Vlr Frete" da NF-e, o que foi cobrado do cliente)
   - `diferenca_frete` = cobrado - pago à transportadora
   - Identifica CTe sem nenhuma NF-e no faturamento (`ctes_nao_vinculados`)
   - Agrega por estado, transportadora, canal, empresa, linha de produto e natureza de operação

4. **Template HTML** — string raw Python com placeholder `__DATA__`. O JSON é injetado via `replace("__DATA__", json_str)`. O `</` no JSON é escapado para `<\/` para evitar encerramento prematuro da tag `<script>`. O HTML resultante é completamente autocontido (dados + JS + CSS em um único arquivo).

## Join key

`CTe infDoc/infNFe/chave` = coluna `Chave` do faturamento (chave NF-e de 44 dígitos, formato SEFAZ)

## Empresas / filiais

```python
CNPJ_MAP = {
    "02786436000183": "BRU1",
    "02786436000264": "BRU2",
    "02786436000698": "RBP",
    "02786436000930": "CGR",
    "02786436000345": "CMP",
    "02786436000507": "PPE",
}
```

A empresa é extraída da coluna `Empresa` do faturamento; o CNPJ (posições 6–20 da chave NF-e) é usado como fallback.

## Dashboard (JavaScript)

Todo o estado de filtro é mantido no objeto `state` e tudo passa por `renderAll()`:
- Filtra `DATA.detalhes` (array de NF-e vinculadas) com os filtros ativos
- Chama `aggregate(rows)` para recomputar KPIs e dados de gráficos
- Destrói e recria cada Chart.js via `chartRefs[id].destroy()` antes de recriar
- Atualiza tabela com `renderTable()`

Os dados pré-computados no JSON (`por_estado`, `por_transp`, etc.) **não são mais usados pelo JS** — existem apenas como referência. Toda agregação é dinâmica a partir de `DATA.detalhes`.

## Pitfalls conhecidos

- **Tamanho do HTML**: não embutir arrays com 100k+ registros no JSON. A lista `nfe_sem_cte` (~123k itens) foi removida do output por isso; apenas o count fica em `resumo.nfe_sem_cte`.
- **Python 3.13 + ElementTree**: nunca usar `elem1 or elem2` com elementos XML — o operador `or` é sempre truthy. Usar sempre `if el is None` explícito.
- **Encoding**: sempre rodar com `$env:PYTHONIOENCODING = "utf-8"` no PowerShell antes de `py processar_frete.py`.
- **Período do faturamento**: o arquivo `.xls` exportado deve ser do mesmo mês/ano dos CTe importados, senão o cruzamento retorna zero vínculos.
