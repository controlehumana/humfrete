# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Rotina diária de atualização

### Automático (Agendador de Tarefas — 08h30)
```
py "C:\Users\caio.zinsly\Documents\ClaudeCode\atualizar.py"
```
Executa: download CTe **D-3 a D-1** → importa NF Entrada → importa Faturamento → cria views → sobe Firestore.
A janela D-3 a D-1 garante que o sábado seja capturado quando o script roda na segunda-feira.

### Manual (após exportar do ERP)
```
py atualizar_sem_download.py   ← pula download, importa arquivos, processa e publica
```

### Pastas de entrada (ERP → banco)
```
ClaudeCode\Faturamento\      ← qualquer nome, qualquer período, acumula sem duplicar
ClaudeCode\NF_Entrada\       ← relatório NF de Entrada, acumula sem duplicar
```

## Scripts principais

| Script | O que faz |
|---|---|
| `atualizar.py` | Orquestrador completo D-3→D-1 automático (4 etapas) |
| `atualizar_sem_download.py` | Igual mas pula download da API |
| `importar_faturamento.py` | Importa CSV de faturamento → `nf_saida_items` |
| `importar_nf_entrada.py` | Importa XLS de NF Entrada → `nf_entrada` |
| `Frete/processar_frete.py` | ETL: banco → cruzamento → Firestore |

## Estrutura do projeto

```
ClaudeCode/
  atualizar.py                  # Orquestrador principal (D-3→D-1 automático)
  atualizar_sem_download.py     # Versão sem download (reprocessamento)
  importar_faturamento.py       # Importa faturamento de saída para o banco
  importar_nf_entrada.py        # Importa NF de entrada para o banco
  Faturamento/                  # Relatórios de faturamento do ERP (qualquer nome)
  NF_Entrada/                   # Relatórios de NF de Entrada do ERP (qualquer nome)
  QUIVE/
    buscar_cte.py               # Baixa CTe da API Qive → cte.db
    criar_view.py               # Parseia XMLs → tabelas cte_campos, cte_nf
    cte.db                      # SQLite: CTe + faturamento + NF entrada
  Frete/
    processar_frete.py          # ETL: cte.db → cruzamento → Firestore
    index.html                  # Web app GitHub Pages (arquivo único)
    firestore.rules             # Regras Firestore (aplicar via Console Firebase)
    CTe/
      FATURAMENTO.csv           # Fallback CSV (se banco indisponível)
      Geral/Tomador/            # XMLs de CTe
      Geral/Eventos de cancelamento/
```

## Banco de dados (QUIVE/cte.db)

### Tabelas principais
| Tabela | Conteúdo |
|---|---|
| `cte_campos` | Dados dos CTe (58k+ registros) |
| `cte_nf` | Mapeamento CTe → NF-e referenciadas (chave_cte, chave_nfe) |
| `cte_cancelamento` | CTe cancelados (chave_cte, chave_canc, data_cancelamento) |
| `nf_saida_items` | Faturamento de saída — 1 linha por item, acumulativo |
| `nf_entrada` | NF de entrada (compras) — 1 linha por NF |

### Views principais
| View | O que agrega |
|---|---|
| `vw_nf_saida` | Faturamento agregado por chave NF-e (1 linha por nota) |
| `vw_cte_nf_entrada` | CTe × NF de entrada (join cte_nf + nf_entrada) |
| `vw_cte` | View base dos CTe ativos |

## CNPJ_MAP das empresas

```python
CNPJ_MAP = {
    "02786436000183": "BRU1",
    "02786436000264": "BRU2",
    "02786436000698": "RBP",
    "02786436000930": "CGR",
    "02786436000345": "CMP",
    "02786436000507": "PPE",
    "02786436000779": "SOR",
    "02786436001074": "UBE",
}
```

**Derivar empresa a partir de chave NF-e (JS):**
```javascript
const emp = CNPJ_EMPRESA[chave.slice(6, 20)];
```

**Derivar número NF ou CTe a partir da chave:**
```javascript
const num = parseInt(ch.slice(25, 34));  // posições 25–33 = nNF/nCT
```

## Classificação dos CTe no processar_frete.py

```
CTe total (~58k)
  ├── Frete de Saída           → NF em nf_saida_items → 'detalhes'
  ├── Frete de Compra (NF Entrada) → vw_cte_nf_entrada → 'compras'
  ├── Frete de Compra (dest CNPJ_MAP) → dest_cnpj Humana → 'compras'
  ├── Frete de Compra (tomador Humana) → rem_cnpj Humana + NF externa → 'compras'
  ├── Dev. Marketplace         → transportadora Shopee/ML → 'devolucoes_mkt'
  ├── CTe c/ NF Cancelada      → NF de CNPJ Humana ausente do fat → 'ctes_nf_cancelada'
  └── Sem Vínculo (~340)       → resto → 'ctes_nao_vinculados'
```

**'detalhes' inclui todas as nat_operacao de saída** — vendas, bonificações, transferências e demais. Não é exclusivo de vendas.

### Campos do payload `ctes_nao_vinculados`
```python
{
  "cte_chave", "transportadora", "transp_cnpj",   # CNPJ da transportadora emitente
  "data_emissao",                                   # DD/MM/YYYY
  "origem_cidade", "origem_uf",
  "destino_cidade", "destino_uf",
  "dest_cnpj", "dest_nome",
  "rem_cnpj", "rem_nome",                           # remetente (tomador frequente)
  "numero_cte", "valor_frete", "peso_kg",
  "nfe_refs",                                       # lista de chaves NF-e
  "motivo",                                         # razão do sem-vínculo
}
```
`ctes_nf_cancelada` tem o mesmo shape + `empresa_nf`.

## KPIs principais (index.html)

### Terminologia correta
- **"% Frete / Faturamento"** — denominador é `total_nf` de todas as NF-e de saída (vendas + bonificações + transferências). Nunca chamar de "% Frete / Venda".
- **"Frete de Saída"** — categoria no Custo Logístico Consolidado. Cobre todo CTe vinculado ao faturamento de saída, não apenas vendas.
- **"Notas com Frete"** — campo `total_nf` no módulo geográfico e tooltips. Não usar "Notas de Venda".

### Cobertura de Faturamento
- **Fórmula:** `nfe_com_cte / nfe_fat_periodo`
- **Denominador (`nfe_fat_periodo`):** NF-e do período CTe (2025+) **excluindo** nat. ops sem frete
- **Nat. ops excluídas:** devoluções (qualquer tipo), entradas (qualquer tipo), perdas/roubo, saldo ICMS, imobilizado, NF consumidor, simples remessa, retorno de locação
- **TRANSFERÊNCIA SAÍDA é mantida** — pode ter CTe associado
- Threshold: verde ≥80%, amarelo ≥65%, vermelho <65%

### CTe Conciliados
- **Fórmula:** usa dados **globais** de `r.total_cte` e `r.ctes_nao_vinculados_count` (DATA.resumo)
- NÃO respeita filtros ativos — é métrica de qualidade global, não analítica
- Threshold: verde ≥98%, amarelo ≥90%, vermelho <90%

### Integridade da Análise (aba Consolidação Frete)
- **Fórmula:** `pctConc × 0,6 + cobDados × 0,4`
- `pctConc` = CTe Conciliados global; `cobDados` = % CTes com cliente, data e destino preenchidos
- Threshold: verde ≥95%, amarelo ≥85%, vermelho <85%

### % Frete / Faturamento — Mapa de Transportadoras
- **Denominador:** faturamento das NF-e **transportadas por aquela carrier** (não o total da empresa)
- Mede eficiência: quanto custa transportar R$100 de faturamento de saída com cada parceiro

## Agrupamento por Grupo Econômico (index.html)

Botão **"Grupo Econômico"** na barra de filtros — ativo por padrão, persiste em `localStorage('groupCarriers')`.

### Funções principais
| Função | O que faz |
|---|---|
| `trKey(d)` | Chave de agrupamento: base 8 dígitos do `transp_cnpj` (modo grupo) ou `d.transportadora` (modo individual) |
| `trDisp(key)` | Nome canônico para exibição: busca em `trGroupMap[key]` e aplica `trName()` |
| `toggleGrupoEc()` | Alterna modo, limpa `state.transp`, repopula select, chama `renderAll()` |
| `_populateTranspSelect()` | Popula o select com `XX.XXX.XXX — Nome` (modo grupo) ou nome simples (modo individual) |

### Globals
- `groupByEconGroup` — `true` quando modo grupo ativo (`localStorage !== '0'`)
- `trGroupMap` — `{ base8cnpj: nomeCanônico }` — nome mais frequente por CNPJ base, construído em `renderAll()`
- `trCnpjMap` — `{ nomeRaw: Set<cnpj> }` — todos os CNPJs por nome de transportadora

### Impacto do modo grupo
Afeta todos os pontos de agrupamento por transportadora: `aggregate()` (`byTr`), `byYMT` (heatmap), gráfico donut Top 10, KPIs de concentração, `_geoByUF.byTr`, `renderRotas()`, `filterRows()` (cheque `state.transp`).

### Reverter para modo individual
Clicar no botão "Grupo Econômico" (fica cinza) — imediato, sem reprocessamento.

### `transp_cnpj` no payload
Campo adicionado em `processar_frete.py` (`cnpj_emitente` do CTe). Necessário para o agrupamento. Se ausente, `trKey(d)` degrada graciosamente para `d.transportadora`.

## Abas do dashboard (index.html)

| id | Label | Descrição |
|---|---|---|
| `visao-geral` | Visão Geral | KPIs, gráficos temporais, geo, eficiência por peso |
| `marketplace` | Marketplace | Shopee + Mercado Livre separados |
| `compras` | Frete Compras | Frete de entrada (NF fornecedores) |
| `dev-mkt` | Dev. Marketplace | Devoluções via Shopee/ML |
| `empresa` | Por Empresa | Análise por filial |
| `operacional` | Operacional | Tabela detalhada por NF-e |
| `clientes` | Consolidação Frete | Oportunidades de consolidação + frete grátis por cliente |
| `nao-vinculados` | Cobertura de Dados | CTe sem NF correspondente — respeita filtros globais; botão espelho por linha |
| `geo` | Geográfico | Mapa SVG do Brasil + ranking por estado |
| `rotas` | Rotas | Análise de rotas origem→destino (excl. Marketplace) |
| `admin` | Admin | Gestão de usuários e permissões |

`ALL_TABS_INFO` (array JS) controla quais abas aparecem no painel de permissões do admin — toda nova aba deve ser adicionada ali.

## Módulo Geográfico (index.html)

### Estrutura de dados `_geoByUF`
```js
_geoByUF[uf] = {
  total,      // frete total para o estado
  linhahum,   // frete Linhahum
  humana,     // frete Humana Alimentar
  qtd,        // nº de CT-e
  total_nf,   // valor das NF-e com frete (vendas + bonificações + transferências)
  byTr: {     // breakdown por transportadora — chave = trKey(d) (respeita modo grupo)
    [key]: { frete, qtd }
  }
}
```

`_geoByUF_prev` e `_geoPrevLabel` guardam o período de comparação (mesmo shape, só `total` e `qtd`).

### Evolução geográfica (tendência)
`_geoPrevRows()` determina o período de comparação automaticamente:
- **1 mês selecionado** → mês anterior
- **Ano sem mês** → ano anterior
- **Múltiplos meses ou sem filtro** → sem comparação (retorna null)

Tendência exibida em dois lugares:
- **Ranking** de estados: chip `▲/▼ X%` ao lado do valor (vermelho = cresceu, verde = caiu)
- **Tooltip** do mapa: linha final `vs [período] → ▲/▼ X% (R$ anterior → R$ atual)`

### Tooltip do mapa (_geoHover)
- Cores via variáveis tema-aware: `tipText`, `tipLabel`, `tipBorder`, `tipSep`, `tipAccent`, `tipGold`
- Label do campo `total_nf`: **"Valor das Notas com Frete"** (não "de Venda")
- **Shopee e Mercado Livre excluídos** do ranking — pertencem à aba Marketplace
- `isMarketplace()` filtra SHPS TECNOLOGIA e EBAZARCOMBR

## Módulo Rotas (index.html)

- `renderRotas()` usa `filterRows(DATA.detalhes, {excMkt:true})` — exclui Marketplace
- Agrupa por `origem_uf → destino_uf`
- Campos disponíveis por rota: `frete`, `qtd`, `peso`, `byTr` (breakdown por transportadora)
- Gráficos: Top 10 por custo total (`mkMultiBar`) + Top 10 por R$/kg (`mkBarRkg`)
- Tabela: Top 25 por custo total com transportadora principal e % de concentração

## Eficiência por Peso — Visão Geral (index.html)

- Calculado inline em `renderAll()` sobre `filteredRows` (excMkt:true)
- Filtra apenas linhas com `peso_kg > 0`; CTe sem peso são contados mas excluídos do cálculo
- KPIs: R$/kg médio global, peso total, transportadora mais eficiente por kg
- Gráfico `ch_rkg` via `mkBarRkg()` — top 10 transportadoras por volume de carga (não por R$/kg)

## Política de Frete Grátis — Consolidação Frete (index.html)

- `renderFreteGratis(rows)` chamado ao final de `renderClientes()`
- Frete grátis = `frete_cobrado < 0.01` (cliente não foi cobrado na NF-e)
- Ranking por custo absorvido (valor_frete pago à transportadora sem repasse ao cliente)

## Helpers de gráfico (index.html)

| Função | Uso |
|---|---|
| `mkBar(id, lbs, vals, color, lbl)` | Barras verticais — eixo Y em BRL |
| `mkBarRkg(id, lbs, vals)` | Barras verticais — eixo Y em R$/kg (não BRL) |
| `mkMultiBar(id, lbs, vals, colors)` | Barras com cor por coluna |
| `mkDonut(id, lbs, vals)` | Rosca |
| `mkLine / mkLinePct` | Linhas temporais |

## Arquitetura web (index.html)

- **GitHub Pages:** https://controlehumana.github.io/humfrete/
- **Firebase Auth v8.10.1 compat** (v10 causa falha no WebChannel)
- **Firestore `/dados/{empresa}`:** payload sem detalhes + N chunks de 800 itens
- `_mergeData()` soma corretamente: `total_cte`, `ctes_nao_vinculados_count`, `nfe_com_cte`; `nfe_fat_periodo` não é somado (vem global no spread de datas[0])
- **CDN Chart.js:** primário cdnjs, fallback jsdelivr via `onerror`
- **CDN Font Awesome:** primário cdnjs, fallback fontawesome.com via `onerror`

## Etapas do atualizar.py

```
Etapa 0a — importar_faturamento.py   (se houver arquivo em Faturamento/)
Etapa 0b — importar_nf_entrada.py    (se houver arquivo em NF_Entrada/)
Etapa 1/4 — buscar_cte.py            (download D-3→D-1 da API Qive)  ← pulado em --pular-download
Etapa 2/4 — criar_view.py            (parseia XMLs, atualiza views)
Etapa 3/4 — processar_frete.py       (cruza dados, sobe para Firestore)
```

## Regras obrigatórias no index.html

1. **Tooltips em todos os cards** — `<div class="kpi-tooltip">` em todo card numérico
2. **Tabelas com dtbl** — toda tabela usa `.tw.dtbl` + `max-height:70vh;overflow-y:auto`
3. **Erros Firebase** — sempre usar `_authMsg(e.code)`, nunca `e.message` bruto
4. **Cores do heatmap** — sempre tema-aware via `_isOcean()`, nunca hardcode
5. **IDs únicos** — cada elemento com ID aparece exatamente uma vez
6. **XSS** — dados externos sempre via `esc()` antes de inserir em innerHTML
7. **Guards de null** — `document.getElementById` seguido de `.textContent`/`.style` deve ter `if(el)` ou `el?.`
8. **Tooltip geo** — cores via variáveis `tipText`, `tipLabel`, `tipBorder`, `tipAccent`, `tipGold` (tema-aware); nunca hardcode hex no `_geoHover`
9. **Insight body** — `.ok`/`.hi`/`.bad` têm override para ocean em CSS (`html.ocean .insight-body .ok` etc.)
10. **card-tip** — tem `z-index:1000` no hover para ficar acima de células `position:sticky` do heatmap
11. **Nova aba** — ao criar nova aba: adicionar tab-btn no sidebar, tab panel HTML, entrada em `_TAB_NAMES`, caso no tab switching, entrada em `ALL_TABS_INFO`

## Módulo Cobertura de Dados — `nao-vinculados` (index.html)

### Arquitetura de dados (3 camadas)
| Variável | Conteúdo |
|---|---|
| `nvAllRows` | Dataset completo (sem filtros) — populado uma vez em `initApp()` |
| `nvBase` | Filtrado pelos filtros globais (ano, mês, empresa) |
| `nvRows` | Filtrado pelos filtros locais da aba (UF, transportadora, motivo, busca) |

### Funções-chave
| Função | Escopo | O que faz |
|---|---|---|
| `_nvEmpresaTomadora(c)` | local `initApp()` | Retorna empresa Humana: `rem_cnpj` → chave NF-e |
| `nvRebuildBase()` | local + `window._renderNV` | Aplica filtros globais → repopula selects → atualiza KPIs → chama `nvFilter()` |
| `nvFilter()` | local `initApp()` | Aplica filtros locais → `nvRows` → `nvRender()` |
| `nvRender()` | local `initApp()` | Renderiza tabela da página atual; botão espelho em cada linha |
| `nvShowEspelho(chave)` | local + `window._nvShowEspelho` | Abre modal DACTE com dados do CTe |

### Integração com filtros globais
- `renderAll()` chama `window._renderNV()` quando aba NV está ativa
- Tab click handler chama `window._renderNV()` ao entrar na aba
- Filtros aplicados: `state.ano`, `state.meses`, `state.empresas`
- Filtros NÃO aplicados ao NV: `state.transp` (aba tem filtro local próprio), `state.linha`, `state.natop`, `state.canal`

### Modal Espelho CT-e
- Abre com `window._nvShowEspelho(cte_chave)`
- Campos exibidos: transportadora + CNPJ, número/série/data/chave 44 dígitos, origem→destino, valor + peso, remetente, destinatário, tomador Humana, NF-e referenciadas, motivo
- Botão **Imprimir / Salvar PDF** via `window.print()` com `@media print` que esconde tudo exceto `#nv-espelho-print`
- Fechar: clique fora do modal ou botão "Fechar"

## Globals críticos (ordem importa)

Declarar no bloco de globals (antes de `onAuthStateChanged`) para evitar TDZ:
- `let DATA = null`
- `let _currentUser = null`
- `let nvAllRows = [], nvBase = [], nvPage = 0, nvRows = []`
- `let CNPJ_EMPRESA = {}`  ← Firebase v8 pode invocar onAuthStateChanged sincronamente

## Erros de carregamento (catch no onAuthStateChanged)

- "Nenhuma empresa" → "Seu acesso não está configurado..."
- "nao encontrados" → "Os dados ainda não foram processados..."
- `permission-denied` → "Sem permissão..."
- `network/failed to fetch` → "Sem conexão..."
- Outros → "Não foi possível carregar o dashboard..."

## transp_cnpj no payload (processar_frete.py)

Campo `cnpj_emitente` do CTe exportado como `transp_cnpj` em cada item de `detalhes`.
- Necessário para `trKey()` e `trGroupMap` no frontend
- Tooltip do heatmap de transportadoras exibe CNPJ(s) formatados via `titleFn`
- `trCnpjMap[nomeRaw] = Set<cnpj>` — todos os CNPJs por nome bruto
- `trGroupMap[base8] = nomeCanônico` — nome mais frequente por CNPJ base

## Módulo Delivery (pendente)

Aguardando tabela de referência de entregadores (nome + CPF + empresa do grupo) do usuário.

**O que já está validado:**
- Arquivo romaneio: HTML-XLS do ERP, colunas Empresa / Nr. NFe / Data / Cliente / Cidade / UF / Transportadora (=entregador) / R$ Frete / R$ Total
- Vínculo por `numero_nfe + empresa` confirmado no banco — 100% de aproveitamento
- Gap de cobertura ~46% é causado por **entregas próprias** (frota da empresa, sem CTe) — não retiradas no depósito

**Pipeline planejado (quando dados chegarem):**
```
ClaudeCode/Romaneio/   ← arquivos HTML-XLS do ERP
  importar_romaneio.py ← parseia HTML, cruza com vw_nf_saida, salva tabela romaneio
  tabela romaneio      ← empresa, numero_nfe, data, entregador, frete, chave_nfe
  processar_frete.py   ← lê romaneio → dataset delivery → Firestore
  index.html           ← nova aba Delivery
```

## Pitfalls conhecidos

- **SDK Firebase v8** — usar v8.10.1 compat. v10 causa falha no WebChannel
- **Encoding Python** — sempre `$env:PYTHONIOENCODING = "utf-8"` antes de rodar scripts
- **Faturamento período** — NF de Nov/Dez 2024 e Jan 2025 ainda ausentes; exportar do ERP
- **~340 CTe sem vínculo** — não têm NF referenciada, investigação via espelho CT-e na aba Cobertura de Dados
- **Cobertura de Faturamento baixa (~46%)** — ~65k "Venda de Mercadoria" sem CTe são provavelmente retiradas no depósito (Caminho B: identificar flag de retirada no ERP para excluir do denominador)
- **CTe Conciliados ≠ Integridade quando filtrado** — CTe Conciliados usa dados globais; se parecerem diferentes, verificar se filtro de canal/categoria está ativo
- **Conflito de push git** — uploads via interface web do GitHub divergem do local; usar `git fetch && git reset --soft origin/main`
- **Duplicatas nos filtros** — `initApp()` usa `_initAppDone` para não re-adicionar opções; selects limpos com `clr()` antes de popular; select de transportadora populado via `_populateTranspSelect()` (não `addOpt` direto)
- **Destinatário em transferências** — `CNPJ_EMPRESA[cnpjRaw]` onde `cnpjRaw = d.part_cnpj.replace(/\D/g,'')` normaliza formatação antes do lookup; empresas do grupo exibidas em laranja com CNPJ formatado abaixo
- **`input()` no processar_frete.py** — envolvido em `try/except EOFError` para não travar execução automática
- **Chart.js guard** — `if(typeof Chart!=='undefined')` obrigatório antes de qualquer config de Chart.js; falha de CDN derruba o script inteiro por TDZ em cascata
