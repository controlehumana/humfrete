# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Reset de senha de usuário (Admin)

O painel Admin **não é capaz de trocar a senha de um usuário existente** — o campo "Senha" só funciona ao criar um usuário novo (`createUserWithEmailAndPassword`). Alterar a senha de outro usuário exigiria uma Cloud Function com Admin SDK (o SDK client-side não permite), e isso requer o plano Blaze (pay-as-you-go) no Firebase — **decisão consciente do usuário de não migrar para Blaze** (evita precisar cadastrar cartão de crédito no projeto).

**Workaround oficial:** rodar `reset_senha.js` (raiz de `Frete/`) localmente:
```
npm install firebase-admin   # uma vez
node reset_senha.js <email> <novaSenha>
```
Usa `serviceAccountKey.json` (já presente, nunca commitado) via Admin SDK para setar a senha diretamente, sem depender de e-mail. A tela de edição de usuário no `index.html` desabilita o campo "Senha" ao editar usuário existente e mostra uma nota explicando isso, para não sugerir uma funcionalidade que não existe.

**"Esqueci minha senha" (tela de login):** `sendPasswordResetEmail` retorna sucesso mas o e-mail pode não chegar (suspeita: filtro corporativo Microsoft 365 bloqueando o remetente `noreply@frete-db255.firebaseapp.com`, domínio compartilhado do Firebase). Ainda não investigado a fundo — se voltar a acontecer, usar `reset_senha.js` como alternativa imediata.

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
    importar_entregadores.py    # Importa XLSX de referência → tabela entregadores
    buscar_nfse_entregadores.py # Busca NFS-e dos entregadores via API Arquivei → nfse_entregadores
    import_log.py               # Helper compartilhado: registra execuções na tabela import_log
    cte.db                      # SQLite: CTe + faturamento + NF entrada + delivery + log
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
| `cte_cancelamento` | CTe cancelados (chave_cte, chave_canc, data_cancelamento, justificativa) |
| `nf_saida_items` | Faturamento de saída — 1 linha por item, acumulativo. Colunas: `canal` (L), `nicho` (J) |
| `nf_entrada` | NF de entrada (compras) — 1 linha por NF |
| `cnpj_nomes` | Cache CNPJ→Razão Social consultado via API. Chave: 14 dígitos sem formatação |
| `entregadores` | Referência cadastral de entregadores autônomos (nome, CNPJ, empresa do grupo) |
| `nfse_entregadores` | NFS-e de serviço emitidas pelos entregadores (módulo Delivery) |
| `import_log` | Histórico de execuções dos scripts de importação/busca — exibido no Painel Admin |

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
  ├── Dev. Marketplace         → transportadora Shopee/ML/TikTok Shop → 'devolucoes_mkt'
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

### Banner "Dados no Sistema" (universo-faixa)
Faixa compacta no topo da aba Visão Geral (antes do `.hero-grid`) mostrando o volume total de registros no sistema — contexto para novos usuários entenderem a base de dados. Populado por `renderUniverso()` a partir de `DATA.resumo`:

| ID | Campo | Descrição |
|---|---|---|
| `univ_cte` | `r.total_cte` | CT-e baixados |
| `univ_nfe_fat` | `r.nfe_fat_periodo` | NF-e de faturamento |
| `univ_compras` | `DATA.compras.length` | NF de entrada (compras) |
| `univ_devmkt` | `DATA.devolucoes_mkt.length` | Devoluções Marketplace |
| `univ_delivery` | `DATA.delivery.length` | NFS-e de entregadores |

### Terminologia correta
- **"% Frete / Faturamento"** — denominador é `total_nf` de todas as NF-e de saída (vendas + bonificações + transferências). Nunca chamar de "% Frete / Venda".
- **"Frete de Saída"** — categoria no Custo Logístico Consolidado. Cobre todo CTe vinculado ao faturamento de saída, não apenas vendas.
- **"Notas com Frete"** — campo `total_nf` no módulo geográfico e tooltips. Não usar "Notas de Venda".

### Vendas com Frete Rastreado + NF-e Vinculadas
- **Cards:** `k_cobertura` / `k_cobertura_sub` e `k_vinc` / `k_vinc_sub`
- **Numerador:** `agg.qtd` — NF-e vinculadas a CTe, já filtradas por todos os filtros ativos
- **Denominador:** `_effDen()` — itera `nfe_fat_por_emp_ano_mes` cobrindo simultaneamente `state.empresas[]`, `state.ano` e `state.meses[]`. Sem filtro: retorna `nfe_fat_periodo` global.
- **Nat. ops excluídas do denominador:** devoluções, entradas, perdas/roubo, saldo ICMS, imobilizado, NF consumidor, simples remessa, retorno de locação — TRANSFERÊNCIA SAÍDA mantida
- **`_periodoLabel`:** label descritivo montado a partir de `state.ano`, `state.meses[]` (formatados via `MESES[+m]`) e `state.empresas[]` — ex.: `" — 2026 · Jun · BRU1"`. **Não usar `state.empresa`** (morto).
- Threshold: verde ≥80%, amarelo ≥65%, vermelho <65%
- **ATENÇÃO:** `_effDen()` deve ser definida no escopo global (antes de `renderInsights` e `renderAll`) — se definida dentro de `renderAll`, causa `ReferenceError` em `renderInsights`

### Dicts por empresa/ano no resumo (processar_frete.py)
Todos calculados com a mesma lógica de exclusão de nat. ops sem frete:
| Campo | Estrutura | Uso |
|---|---|---|
| `nfe_fat_periodo` | `int` | denominador global (todos os anos/empresas) |
| `nfe_fat_por_empresa` | `{emp: int}` | denominador por empresa |
| `nfe_fat_por_ano` | `{ano: int}` | denominador por ano |
| `nfe_fat_por_emp_ano` | `{emp: {ano: int}}` | denominador empresa×ano |
| `nfe_fat_por_emp_ano_mes` | `{"emp\|ano\|mes": int}` | denominador empresa×ano×mês — chave flat com `\|` como separador |
| `cte_conc_por_empresa` | `{emp: {total, nao_vinculados}}` | CTe Conciliados por empresa |
| `cte_conc_por_emp_ano_mes` | `{"emp\|ano\|mes": {total, nao_vinculados}}` | CTe Conciliados empresa×ano×mês — mesmo padrão de chave flat |
| `nfe_sem_cte_por_empresa` | `{emp: int}` | warning NF sem CTe por empresa |

Em `_mergeData` os dicts de chave flat (`nfe_fat_por_emp_ano_mes`, `cte_conc_por_emp_ano_mes`) são mesclados via `Object.assign` sem conflito — cada empresa emite só suas próprias chaves.

### `_effDen()` — denominador de NF-e Vinculadas / Vendas com Frete Rastreado
Função global (definida antes de `renderInsights` e `renderAll`). Itera `nfe_fat_por_emp_ano_mes` filtrando pelas dimensões ativas:
```javascript
function _effDen(){
  const r2=DATA?.resumo||{};
  const ano=state.ano;
  const emps=(state.empresas&&state.empresas.length)?state.empresas:null;
  const meses=(state.meses&&state.meses.length)?state.meses:null;
  if(!ano&&!emps&&!meses) return r2.nfe_fat_periodo||r2.total_nfe_fat||0;
  const map=r2.nfe_fat_por_emp_ano_mes||{};
  let total=0;
  for(const k in map){
    const [e,a,m]=k.split('|');
    if(ano&&a!==ano) continue;
    if(emps&&!emps.includes(e)) continue;
    if(meses&&!meses.includes(m)) continue;
    total+=map[k];
  }
  return total;
}
```
**Atenção:** `state.meses` armazena strings zero-padded `"06"` (extraído de `(d.data||'').slice(3,5)` pelo multiselect) — a comparação com `m` (também `"06"` das chaves do dict) é sempre consistente.

### `_filtCteConc()` — CTe Conciliados com filtro
Mesma lógica de iteração que `_effDen()`, mas sobre `cte_conc_por_emp_ano_mes`. Retorna `{total, naoVinc, vinc, pct}` ou `null` quando não há filtro ativo (neste caso o card usa os valores globais `r.total_cte`/`r.ctes_nao_vinculados_count`).

### CTe Conciliados (card Visão Geral)
- **Sem filtro:** exibe % global (`r.total_cte` e `r.ctes_nao_vinculados_count`) + sub-texto "X de Y CTe — global"
- **Com filtro ativo (empresa/ano/mês):** exibe % filtrado (via `_filtCteConc()`) como valor principal + global como comparativo no sub-texto: `"X de Y CTe no filtro  |  global: Z%"`
- Threshold: verde ≥98%, amarelo ≥90%, vermelho <90%

### Integridade da Análise (aba Consolidação Frete)
- **Fórmula:** `pctConc × 0,6 + cobDados × 0,4`
- `pctConc` = CTe Conciliados — **respeita empresa** via `cte_conc_por_empresa` (igual ao card Visão Geral)
- `cobDados` = % CTes com cliente, data e destino preenchidos — filtrado via `filterRows()`
- Threshold: verde ≥95%, amarelo ≥85%, vermelho <85%

### `state.empresa` — removido (jun/2026)
`state.empresa` (singular) foi **removido do código** — todas as 6 ocorrências foram substituídas por `state.empresas` (array multi-select). **Nunca adicionar referências a `state.empresa`; usar sempre `state.empresas`.**

Efeitos do cleanup:
- `_renderNC` e `_renderCancel` agora filtram por empresa quando `state.empresas` está ativo
- `geo_filtro_lbl` e `_filtParts` (Rotas) agora exibem empresa quando exatamente 1 empresa selecionada
- `_nfeSemCteVal` usa `nfe_sem_cte_por_empresa` para 1 empresa, soma para múltiplas, global para nenhuma
- `_ccEmp` (renderClientes) usa `cte_conc_por_empresa[empresas[0]]` quando exatamente 1 empresa selecionada

### Repasse/Diferença de Frete ao Cliente (card Visão Geral)
- Usa `agg.difCom` — soma de `diferenca_frete` **apenas** nas entregas com `frete_cobrado > 0`
- **Não usar `agg.difTot`** — ele soma todas as linhas incluindo frete grátis (`cob=0` → `dif=-valor_frete`), inflando artificialmente o negativo
- Quando `difCom >= 0`: card label "Repasse de Frete ao Cliente" (verde)
- Quando `difCom < 0`: card label "Diferença de Frete ao Cliente — Deixamos de Cobrar" (vermelho), exibe `Math.abs(difCom)`
- Para validar manualmente: exportar aba Operacional com filtro **"Todos"** (não "Saldo Negativo") e somar a coluna Saldo — resultado deve bater com o card. Se exportado com `opSaldoFilter='NEG'`, o total da planilha excluirá as linhas de saldo positivo e não baterá com o card (que é posição líquida).

### Filtro de Saldo na aba Operacional
Botões Todos / Saldo Positivo / Saldo Negativo / Sem Cobrança acima da tabela. Controlado por `opSaldoFilter` (global) via `setOpSaldoFilter(val)`. Tanto `renderTable()` quanto `opExportXLSX()` usam `opSaldoFilteredRows()` em vez de `tableRows` diretamente — **o export reflete o filtro de saldo ativo no momento**.

### % Frete / Faturamento — Mapa de Transportadoras
- **Denominador:** faturamento das NF-e **transportadas por aquela carrier** (não o total da empresa)
- Mede eficiência: quanto custa transportar R$100 de faturamento de saída com cada parceiro

### Mapa de Desempenho por Empresa — Tooltip Explicativo (jul/2026)
O heatmap `% Frete/Faturamento - Mapa de Desempenho por Empresa` (`renderYoY()`, container `#yoy_heatmap`) ganhou um tooltip (`#heat_tip`, mesmo padrão visual/hover de `#geo_tip` no módulo Geográfico) que explica automaticamente por que uma célula está acima do benchmark, em vez de só mostrar a cor.

- **Dados agregados:** ao lado de `byYME` (frete `fr` / faturamento `nf` por `ano|emp` × mês, já existente), o loop de `tableRows.forEach` em `renderAll()` agora também popula `detYME[ano+'|'+emp][mes] = {nfes:Set<chave_nfe>, porTr:{trKey:frete}}` — conjunto de NF-e distintas (cobertura/ticket médio) e frete por transportadora (top carrier). Ambos exportados via `window._yoyData`.
- Só células com `val!==null` recebem `class="heat-cell" data-emp data-ano data-mes` e `cursor:help`; `mouseenter`/`mousemove`/`mouseleave` são ligados após `container.innerHTML=html` em `renderYoY()`.
- `_heatHover(e)` monta o tooltip a partir de 4 números, todos derivados de `window._yoyData` no momento do hover (sem nova consulta ao Firestore):
  - **% Frete/Faturamento** da célula + diferença em pp vs a linha "Total Grupo" do mesmo mês (`byYME[ano][mes]`, sem sufixo de empresa)
  - **Cobertura de Frete Rastreado** — `det.nfes.size` (NF-e com CT-e) ÷ `DATA.resumo.nfe_fat_por_emp_ano_mes["emp|ano|mes"]` (total de NF-e de venda do mês/empresa, mesmo dict usado por `_effDen()`)
  - **Ticket Médio** das entregas rastreadas — `cell.nf / det.nfes.size`
  - **Transportadora Principal** — maior valor em `det.porTr`, com `trDisp()` para nome canônico (respeita modo Grupo Econômico)
- **"Possíveis motivos" (heurística, não é causalidade provada):** cobertura `<30%` → percentual calculado sobre uma fatia pequena das vendas, pode não representar o custo logístico total; ticket médio `<R$1000` combinado a % acima do grupo → frete cobrado por entrega tende a pesar mais sobre nota pequena; transportadora com `>50%` do frete da célula → concentração de fornecedor. Sem nenhum desses, mostra frase genérica de "dentro do padrão".
- Reaproveita exatamente os mesmos campos que já alimentam `_effDen()`/`_filtCteConc()` (`nfe_fat_por_emp_ano_mes`) — qualquer mudança na definição desse dict no backend afeta a cobertura mostrada aqui também.

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
| `marketplace` | Marketplace | Shopee + Mercado Livre + TikTok Shop separados |
| `compras` | Frete Compras | Frete de entrada (NF fornecedores) |
| `delivery` | Delivery | Custo com NFS-e de entregadores autônomos |
| `dev-mkt` | Devoluções Marketplace | Devoluções via Shopee/ML/TikTok Shop |
| `separacao` | Separação | Produtividade de picking por unidade — pedidos, itens separados, ranking, dia da semana, canal |
| `empresa` | Por Empresa | Análise por filial |
| `transferencias` | Transferências | Frete de transferência entre unidades — quebra Matriz→Unidade/Unidade→Matriz/Entre Unidades + Delivery, levantamento Unidade×Mês exportável |
| `operacional` | Operacional | Tabela detalhada por NF-e |
| `natop` | Por Tipo de Venda | Cobertura de frete por natureza de operação — drill-down para Operacional |
| `clientes` | Por Cliente | Oportunidades de consolidação + frete grátis por cliente |
| `nao-vinculados` | CT-e sem Identificação | CTe sem NF correspondente — respeita filtros globais; botão espelho por linha |
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
- **Shopee, Mercado Livre e TikTok Shop excluídos** do ranking — pertencem à aba Marketplace
- `isMarketplace()` filtra SHPS TECNOLOGIA, EBAZARCOMBR e TIKTOK LOGISTICS

## Módulo Marketplace — `marketplace` (index.html)

Mostra o frete das **vendas de saída** (não devoluções — essas ficam na aba Dev. Marketplace) realizadas via marketplaces que usam logística própria/dedicada e emitem CT-e identificável.

### Canais reconhecidos
| Canal | `marketplace_type` | Transportadora / `canal` (NF) |
|---|---|---|
| Shopee | `shopee` | `SHPS TECNOLOGIA E SERVI[Ç/C]O LTDA` ou `canal` ∈ `{SHOPPE, SHOPEE}` |
| Mercado Livre | `ml` | `EBAZARCOMBR LTDA` / `MERCADO LIVRE` ou `canal = MERCADO LIVRE` |
| TikTok Shop | `tiktok` | `TIKTOK LOGISTICS BRAZIL LTDA` (nome contém `TIKTOK`) ou `canal` ∈ `{TIKTOSHOP, TIKTOKSHOP, TIKTOK SHOP}` |

### Classificação (processar_frete.py)
- `_marketplace_type(tr, canal)` em `cruzar()` retorna `'shopee'|'ml'|'tiktok'|None` — popula `is_marketplace` e `marketplace_type` em cada item de `detalhes`
- `_mkt_type_tr(tr)` (lógica equivalente, só por nome da transportadora) é usada para classificar `devolucoes_mkt`
- **Atenção:** os dois helpers fazem a mesma classificação por motivos históricos — qualquer novo canal de marketplace deve ser adicionado em **ambos**

### `renderMarketplace()` (index.html)
- `mktRows = filterRows(DATA.detalhes, {excMkt:false, onlyMkt:true})` — só linhas com `is_marketplace:true`
- Filtra por `d.marketplace_type` (`'shopee'|'ml'|'tiktok'`) para separar os 3 canais
- KPIs por canal: Total Frete e Frete Médio (`mkt_<canal>_frete/qtd/med`)
- Botões `setMktFilter('SHOPEE'|'MERCADO LIVRE'|'TIKTOK SHOP')` filtram a tabela de detalhes (`mkt_f_shopee/ml/tiktok`)
- Gráfico `ch_mkt_timeline` — 3 linhas (Shopee laranja `#FF6900`, Mercado Livre amarelo `#FFE600`, TikTok Shop rosa `#FF0050`) com evolução mensal do frete
- Alertas automáticos comparam mês atual vs anterior por canal (`['shopee'|'ml'|'tiktok', cor, label]`)

### Pitfall — TikTok Shop não aparece em Dev. Marketplace
Os ~61 CT-e da `TIKTOK LOGISTICS BRAZIL LTDA` encontrados no banco (mar–abr/2026) são **todos entregas de saída** (Humana → cliente final/CPF), não devoluções — não há nenhum CT-e com `cnpj_destinatario` em `CNPJ_MAP` (que indicaria retorno para a Humana), diferente de Shopee/ML que têm logística reversa documentada via CT-e. Por isso o card "TikTok Shop" na aba Dev. Marketplace aparece zerado — **comportamento correto**, não é bug. Caso a TikTok passe a gerar CT-e de devolução, `_mkt_type_tr()` já está pronto para classificá-los automaticamente.

### `HTML_TEMPLATE` em processar_frete.py
O script mantém uma cópia quase idêntica do HTML/JS do `index.html` em `HTML_TEMPLATE` (usada para gerar o `dashboard_frete.html` local standalone via `OUTPUT_HTML`). **Qualquer mudança na aba Marketplace (ou outras abas presentes no template) precisa ser replicada manualmente nos dois lugares** — não há compartilhamento de código entre o app publicado (lê do Firestore) e o dashboard standalone (dados embutidos no HTML).

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
- **Firestore `/dados/{empresa}`:** payload sem detalhes + N chunks de 800 itens (`{emp}_det_000`, `{emp}_det_001`, …) + `_meta` global
- `_mergeData()` soma corretamente: `total_cte`, `ctes_nao_vinculados_count`, `nfe_com_cte`; `nfe_fat_periodo` não é somado (vem global no spread de datas[0])
- **CDN Chart.js:** primário cdnjs, fallback jsdelivr via `onerror`
- **CDN Font Awesome:** primário cdnjs, fallback fontawesome.com via `onerror`
- **CDN SheetJS (xlsx):** primário cdnjs, fallback jsdelivr via `onerror` — necessário para export Excel

## Segurança e LGPD

### O repositório `controlehumana/humfrete` é PÚBLICO
GitHub Pages free tier exige repo público. Consequência crítica: **nada com dado real pode ser versionado**, porque tudo no Git fica acessível sem autenticação — inclusive em commits antigos do histórico, mesmo após remoção do HEAD.
- **NUNCA versionar arquivos com `const DATA={...}` embutido** (snapshots, protótipos, relatórios standalone). O `.gitignore` já cobre `test_*.js`, `teste_*.html`, `dashboard_frete.html` — mas o `.gitignore` **não remove o que já está rastreado**. Ao criar arquivo novo de teste/preview, confirmar que casa com o `.gitignore` ANTES do primeiro `git add`.
- O `index.html` e o `processar_frete.py` podem ser públicos (a `apiKey` Firebase no client é pública por design; os dados ficam no Firestore, protegidos pelas rules).

### Incidente corrigido (2026-06-12)
`test_js.js` (~19MB) e `teste_relatorio.html` continham faturamento/fretes/CNPJs reais embutidos e eram servidos sem login via Pages (contornavam o Firebase Auth). Já estavam no `.gitignore` mas seguiam rastreados de commits antigos. Fix (commit `b36bc7d`): `git rm --cached` + push → 404 no Pages. **Pendente:** dados ainda no histórico do repo público — exige reescrita de histórico (`git filter-repo`/BFG + `push --force`).

### Gaps de segurança/resiliência conhecidos (auditoria 2026-06-12, ainda em aberto)
1. **Histórico Git vazado** (acima) — limpar com filter-repo/BFG.
2. **Sem backup do `cte.db`** — banco único (~684MB) numa só máquina; nenhum script faz cópia. Maior risco do projeto. Firestore só guarda o agregado, não reconstrói o banco.
3. **Sem Firebase App Check** — login/Firestore abertos a abuso de cota de qualquer origem.
4. **Sem 2FA** para conta admin (controla usuários e empresas).
5. **`firestore.rules` aplicadas à mão** no Console (risco de divergência entre repo e produção).
6. **`serviceAccountKey.json`** (admin total do Firestore) parado na máquina, sem rotação.

### XSS — sempre escapar dados externos com `esc()` em innerHTML/template strings
Regra #6 das "Regras obrigatórias". Corrigido em `renderAdminUsers()` (2026-06-12), que injetava `displayName`/`email`/`empresas`/`abas` sem escape. Auditar qualquer novo render que monte HTML com dados de usuário/Firestore.

### Firestore rules (`firestore.rules`)
**Aplicar manualmente no Firebase Console → Firestore → Rules após qualquer alteração** — o arquivo no GitHub não publica automaticamente.

| Coleção | Regra |
|---|---|
| `dados/{docId}` | Admin lê tudo; usuário comum lê apenas docs onde `empresaDoDoc(docId) in userDoc().empresas`; `_meta` somente admin |
| `users/{uid}` | Leitura: próprio uid ou admin; escrita: usuário não pode alterar `isAdmin`/`empresas`/`tabs`; deleção bloqueada |

`empresaDoDoc(docId)` = `docId.split('_det_')[0]` → extrai `BRU1` de `BRU1_det_000`.

**Antes (jun/2026):** `allow read: if request.auth != null` — qualquer autenticado lia dados de todas as empresas contornando o filtro frontend.

### Dados pessoais (LGPD)
- **`entregador_cnpj` removido do Firestore** (jun/2026) — permanece apenas no `cte.db` local. MEI/CPF dos entregadores não sobe para a nuvem.
- Frontend conta entregadores únicos por `entregador_nome` (não mais por CNPJ).
- Export `dlvExportXLSX` não inclui CNPJ do entregador.
- Dados de PJ (CNPJs de clientes/fornecedores, razão social) permanecem no Firestore — acesso restrito pelas regras acima.

## Exportação para Excel (index.html)

Botões com classe CSS `btn-xlsx` (verde, tema-aware via `html.ocean .btn-xlsx`):

| Função | Escopo | Aba | Respeita busca/filtros? |
|---|---|---|---|
| `nvExportXLSX()` | local `initApp()` + `window.nvExportXLSX` | CT-e sem Identificação | ✅ filtros locais + globais |
| `opExportXLSX()` | global | Operacional | ✅ filtros + ordenação ativos |
| `natopExportXLSX()` | global | Por Tipo de Venda | ✅ `_natopRows` já filtrado |
| `cliExportXLSX()` | global + `window.cliExportXLSX` | Por Cliente | ❌ ignora busca — exporta todos `cliData`; aba única "Consolidacoes", 1 linha por NF-e |
| `compExportXLSX()` | local `initApp()` + `window.compExportXLSX` | Frete Compras | ✅ empresa, ano, mês, busca |
| `dlvExportXLSX()` | local `initApp()` + `window.dlvExportXLSX` | Delivery | ✅ empresa, ano, mês, busca |
| `dmExportXLSX()` | local `initApp()` + `window.dmExportXLSX` | Devoluções Marketplace | ✅ plataforma, empresa, ano, mês, busca |

- Guard obrigatório: `if(typeof XLSX==='undefined')` antes de usar SheetJS
- Funções dentro de `initApp()` **devem** ser expostas via `window.fn = fn` para o `onclick` do HTML alcançar — mesmo padrão de `window._renderNV`, `window._nvShowEspelho`
- Colunas monetárias recebem `cell.z = '"R$"#,##0.00'` após `json_to_sheet`
- Arquivo gerado: `<prefixo>_YYYY-MM-DD.xlsx`

## Lookup de Razão Social por CNPJ

### Arquitetura (3 camadas, da mais rápida para a mais lenta)
1. **`_cnpjNameCache`** — dict em `localStorage('_cnpjNC')`: persiste entre sessões, carregado na inicialização
2. **`DATA.cnpj_nomes`** — dict `{cnpj: razao_social}` pré-carregado do Firestore: populado pelo `processar_frete.py` a cada execução
3. **API pública** — consultada apenas para CNPJs ausentes nas duas camadas acima

`_loadCnpjNames()` resolve na ordem 1 → 2 → 3. A API só é chamada para CNPJs genuinamente novos. Isso elimina a lentidão anterior onde todos os CNPJs iam para a API a cada render.

### Tabela SQLite `cnpj_nomes` (cte.db)
```sql
CREATE TABLE cnpj_nomes (
    cnpj          TEXT PRIMARY KEY,  -- 14 dígitos sem formatação
    razao_social  TEXT,
    consultado_em TEXT               -- YYYY-MM-DD
)
```
Criada automaticamente em `_popular_cnpj_nomes()`. CNPJs sem resultado ficam com `razao_social = ''`.

**Regra de re-consulta (30 dias):** um CNPJ é considerado "já consultado" (e pulado) apenas se tiver `razao_social != ''` **OU** `consultado_em >= date('now','-30 days')`. CNPJs com nome vazio e consulta mais antiga que 30 dias são re-tentados automaticamente. Isso evita o bloqueio permanente de CNPJs que falharam temporariamente na API.

### Funções Python (processar_frete.py)
| Função | O que faz |
|---|---|
| `_popular_cnpj_nomes(nfe_map)` | Cria tabela, coleta CNPJs distintos do `nfe_map`, resolve via dados locais + API (ver abaixo), salva resultados |
| `_ler_cnpj_nomes()` | Lê `cnpj_nomes` e retorna `{cnpj: razao_social}` (só com nome preenchido) |

Chamadas em `main()` logo após `parse_faturamento()`. O dict vai para `dados["cnpj_nomes"]` → `split_by_empresa` → Firestore.

### `_popular_cnpj_nomes` — resolução em 2 camadas (corrigido 2026-06-10)
1. **Camada local (gratuita, instantânea):** para cada CNPJ "novo", busca `nome_destinatario`/`nome_remetente` em `cte_campos` (já vêm do XML do CT-e, indexado por `cnpj_destinatario`/`cnpj_remetente`). Cobre tipicamente ~70% dos CNPJs novos sem nenhuma chamada de rede.
2. **Camada API (throttled):** só para os CNPJs que sobraram. `MAX_API_POR_EXECUCAO = 20` por rodada — BrasilAPI primeiro (`User-Agent: Mozilla/5.0`), se falhar `time.sleep(20)` antes do fallback CNPJ.ws (`publica.cnpj.ws`, rate-limit ~3 req/min sem chave), depois `time.sleep(1.5)` entre CNPJs. CNPJs não processados na rodada ficam para a próxima execução.

**NUNCA remover o limite/throttling nem processar um lote grande de uma vez** — BrasilAPI/CNPJ.ws bloqueiam (403/429) rapidamente sem chave de API, e a regra de 30 dias faria os CNPJs que falharem ficarem com `razao_social=''` por um mês. Se precisar reprocessar um backlog grande de CNPJs vazios, resetar `consultado_em` para uma data antiga (reabre para `novos`) e deixar o throttling de 20/execução resolver gradualmente ao longo dos dias.

### Funções JS (index.html)
| Função | O que faz |
|---|---|
| `_isCNPJ(s)` | Retorna `true` se `s` tem 14 dígitos (remove não-dígitos antes) |
| `_cliClientCell(cliente, partCnpj)` | Renderiza célula: nome se em cache, senão CNPJ formatado + `⟳` + `data-cnpj` attr |
| `_applyCnpjToEl(el, nm)` | Aplica nome (ou "—" se vazio) à célula `td` mais próxima do elemento `[data-cnpj]` |
| `_loadCnpjNames()` | Resolve camada 1→2→3; API só para os restantes; salva cache; atualiza DOM |

### Fluxo JS
1. `renderCliTable()` chama `_cliClientCell()` por linha — renderiza CNPJ formatado com `data-cnpj`
2. `_loadCnpjNames()` chamada após render
3. Resolve imediatamente do `_cnpjNameCache` (localStorage) ou `DATA.cnpj_nomes` (Firestore)
4. Apenas CNPJs ausentes em ambos vão para BrasilAPI → fallback CNPJ.ws
5. DOM atualizado via `_applyCnpjToEl()`; cache salvo em localStorage

**APIs:** `https://brasilapi.com.br/api/cnpj/v1/{cnpj}` → `https://publica.cnpj.ws/cnpj/{cnpj}`. Campo: `razao_social || nome_fantasia`.

## Etapas do atualizar.py

```
Etapa 0a — importar_faturamento.py   (se houver arquivo em Faturamento/)
Etapa 0b — importar_nf_entrada.py    (se houver arquivo em NF_Entrada/)
Etapa 1/4 — buscar_cte.py            (download D-3→D-1 da API Qive)  ← pulado em --pular-download
Etapa 2/4 — criar_view.py            (parseia XMLs, atualiza views)
Etapa 3/4 — processar_frete.py       (cruza dados, sobe para Firestore)
```

## Log de Importações — Painel Admin (index.html)

Histórico das execuções de scripts que alimentam o `cte.db`, exibido na aba Admin para acompanhar volume, erros e crescimento do banco (apoia decisão de migração futura, ex.: para Supabase).

### Arquitetura
```
QUIVE/import_log.py            ← helper compartilhado: registrar(conn, script, origem, fonte, registros, novos, erros, status, detalhes)
  ├── importar_faturamento.py        (origem='arquivo')
  ├── importar_nf_entrada.py / buscar_nf_entrada.py  (origem='api')
  ├── importar_entregadores.py       (origem='arquivo')
  ├── buscar_cte.py                  (origem='api')
  └── buscar_nfse_entregadores.py    (origem='api')
processar_frete.py             ← _carregar_import_log() → campo "import_log" no payload (meta, não por empresa)
index.html                     ← card "Log de Importacoes" na aba Admin, renderAdminImportLog()
```

### Tabela `import_log` (cte.db)
```sql
CREATE TABLE import_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data_hora TEXT, script TEXT, origem TEXT, fonte TEXT,
    registros INTEGER, novos INTEGER, erros INTEGER,
    status TEXT, detalhes TEXT, tamanho_mb REAL
)
```
- `origem` — `'arquivo'` ou `'api'`
- `status` — `'sucesso'`, `'parcial'` (terminou mas com erros) ou `'erro'` (falha fatal)
- `tamanho_mb` — tamanho do `cte.db` em disco no momento do registro (ver abaixo)
- Coluna `tamanho_mb` adicionada via `ALTER TABLE ... ADD COLUMN` dentro de `registrar()` (try/except idempotente) — registros antigos ficam com `NULL`

### `import_log.py` — helper compartilhado
- `registrar(conn, script, origem, fonte, registros, novos, erros, status, detalhes)` — cria a tabela se não existir, insere o log e faz commit
- `_tamanho_banco_mb(conn)` — descobre o caminho do `.db` via `PRAGMA database_list` e mede com `os.path.getsize()`; retorna `None` se não conseguir
- Importado via `sys.path.insert(0, str(BASE / "QUIVE"))` nos scripts fora da pasta QUIVE (ex.: `importar_faturamento.py`)
- Cada script chama `registrar()` ao final do `main()` (sucesso) e dentro do `except` (erro fatal, preservando `raise` para não perder o traceback)

### `_carregar_import_log()` (processar_frete.py)
- Lê os últimos 60 registros de `import_log` ordenados por `id DESC`
- Detecta dinamicamente a existência da coluna `tamanho_mb` via `PRAGMA table_info` — compatibilidade com bancos onde a tabela já existia antes da coluna
- Incluído no dict `meta` (não em `split_by_empresa` — é dado global, igual para todos os usuários admin)

### `renderAdminImportLog()` (index.html)
- Tabela com colunas: Data/Hora, Script, Origem (chip azul=API/cinza=Arquivo), Arquivo/Período, Registros, Novos, Erros (vermelho se >0), Status (chip verde=Sucesso/vermelho=Erro/amarelo=Parcial), Tam. Banco, Detalhes
- `fmtTamanho(mb)` — formata em MB ou GB e aplica cor de alerta progressiva: cinza (<1GB), amarelo (≥1GB), vermelho (≥2GB) — sinaliza quando considerar migração
- `_fmtDataHora(dh)` — converte `data_hora` de `YYYY-MM-DD HH:MM:SS` (formato salvo no banco) para exibição `DD/MM/YYYY HH:MM:SS`. **Não alterar o formato salvo no banco** — só a exibição
- **Filtro por intervalo de datas:** inputs `admin-log-data-de`/`admin-log-data-ate` (`type="date"`, `onchange="adminFilterImportLog()"`) acima da tabela + botão "Limpar filtro" (`adminClearLogFilter()`). `_adminImportLogsRaw` guarda o array bruto vindo do Firestore; `adminFilterImportLog()` filtra por `data_hora.slice(0,10)` comparando strings `YYYY-MM-DD` (mesmo formato do `<input type="date">`) e chama `renderAdminImportLog()` com o resultado

## Usuários Cadastrados — Painel Admin (index.html)

- `renderAdminUsers()` lista cada usuário com avatar, nome/email, badge ADMIN (se aplicável) e meta-info `Empresas: ... · Abas: ...`
- **Abas exibidas pelo nome do módulo** (não pela contagem): mapeia `u.tabs` (array de IDs) para os `label` correspondentes em `ALL_TABS_INFO` — ex. `"Visão Geral, Delivery, Operacional"`. Admin mostra `"Todas"`. Isso dá visibilidade imediata de quais módulos cada usuário pode acessar, sem precisar abrir o formulário de edição

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
12. **Botões de ação nos cards** — usar classe `btn-xlsx` (definida no CSS global com override `html.ocean`) para garantir legibilidade em ambos os temas; nunca hardcode de cor inline nesses botões

## Módulo Nat. Operação — `natop` (index.html)

### Fonte de dados
| Campo | Origem | Comportamento |
|---|---|---|
| Com Frete | `filterRows(DATA.detalhes, {excMkt:false})` agrupado por `d.nat_operacao` | Respeita todos os filtros globais |
| Sem Frete | `DATA.nat_op_sem_cte` (dict `{nat: count}`) | **Global** — não filtrado por empresa/ano/mês |

`nat_op_sem_cte` é calculado em `processar_frete.py` sobre todas as NF-e do `nfe_map` que não estão em `linked_nfe_chaves`. É um campo global e **deve ser incluído explicitamente em `split_by_empresa`** (copiado inteiro para cada empresa — não filtrado). Se omitido, chega como `{}` no frontend e a coluna Sem Frete fica zerada.

Em `_mergeData()`, é mesclado somando os valores: `datas.forEach(d=>Object.entries(d.nat_op_sem_cte||{}).forEach(([k,v])=>{m[k]=(m[k]||0)+v}))`.

### State e sort
- `let natopSort = {col:'total', dir:'desc'}` — global
- `let _natopRows = []` — array de `{nat, com, sem, total, pct, frete, nf, pctFr}` — populado por `renderNatOp()`

### Funções
| Função | O que faz |
|---|---|
| `renderNatOp()` | Reconstrói `_natopRows`, atualiza KPIs, aviso de filtro, sort headers e tabela |
| `natopSortBy(col)` | Alterna `natopSort.dir` ou muda `natopSort.col`, re-renderiza |
| `natopExportXLSX()` | Exporta `_natopRows` para Excel via SheetJS |
| `natopDrillDown(i)` | Aplica `state.natop=[nat]`, atualiza checkboxes e label do multiselect, troca para aba `operacional`, chama `renderAll()` |

### Aviso de filtro
`natop_filter_warn` (div `.alert.a-yellow`) fica visível quando `state.ano || state.meses.length || state.empresas.length`. Informa que a coluna Sem Frete é global e não reflete os filtros ativos.

### Cobertura — cores
- Verde ≥ 80%, Amarelo ≥ 50%, Vermelho < 50%

### Toggle de visão
Três botões no topo do módulo: **Nat. Operação | Canal | Nicho**. Controlado por `natopView` (`'natop'|'canal'|'nicho'`) e `natopSetView(v)`. Config centralizada em `_NATOP_VIEW_CFG`:
```javascript
{field, label, kpiLbl, title, hasSem}
```
- `hasSem:true` apenas para `natop` (colunas Sem Frete / Total / Cobertura são ocultadas para Canal e Nicho)
- `field` é o campo de `d` usado para agrupar: `nat_operacao`, `canal`, `nicho`

### Campo `nicho` no pipeline
- Coluna J do CSV de faturamento, header `"Nicho"`
- Adicionada em `importar_faturamento.py` (COLS, idx, CREATE TABLE, INSERT, vw_nf_saida)
- `nf_saida_items` — `ALTER TABLE ADD COLUMN nicho TEXT` (executar uma vez em bancos existentes)
- `vw_nf_saida` — `MAX(nicho) AS nicho`
- `processar_frete.py` — `nfe_map[chave]["nicho"]` e `detalhes.append({"nicho":...})`
- **Atenção:** usar `r["nicho"]` (não `r.get("nicho")`) — `sqlite3.Row` não tem método `.get()`

### Drill-down
`natopDrillDown(i)` usa índice de `_natopRows` (evita escape de aspas no onclick gerado). Comportamento por visão:
- `natop` → aplica `state.natop=[nat]`, atualiza checkboxes e label do multiselect
- `canal` → aplica `state.canal=val`, atualiza `#filter_canal`
- `nicho` → aplica `state.nicho=val`; chip "Nicho: X ×" aparece na barra de filtros via `updateTags`; `filterRows` filtra `d.nicho` quando `state.nicho` preenchido

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
| `nvShowEspelho(data)` | local + `window._nvShowEspelho` | Aceita chave string (busca em `nvRows`) **ou objeto direto**. Abre modal DACTE. |

### Espelho CT-e — outras tabelas
- **NF Cancelada (`nc_tbody`):** `window._ncData` exposto; botão âmbar chama `window._nvShowEspelho(window._ncData[i])`. Campo `empresa_nf` usado para tomador e para filtro.
- **CTe Cancelados (`cancel_tbody`):** `window._cancelData` exposto. Payload `cancelados_data` inclui:
  - `empresa` (campo adicionado — CNPJ_MAP da empresa Humana tomadora)
  - `cte_chave`, `transportadora`, `valor_frete`
  - `data_cancelamento` (YYYY-MM-DD), `justificativa` (`xJust` do XML SEFAZ)
  - `nfe_refs` — lista de chaves NF-e referenciadas (GROUP_CONCAT via LEFT JOIN `cte_nf`)
  - `cte_substituto` — `{cte_chave, transportadora, transp_cnpj, data_emissao, origem, destino, valor_frete}` ou `null`. Query: JOIN duplo em `cte_nf` (mesma `chave_nfe`, CTe ativo diferente).
- **Tabela CTe Cancelados:** colunas Transportadora, Data Canc., Justificativa, NF(s) Ref. (até 3 + contador), chip Substituto ("✓ Reemitido" / "— Sem subst."), Valor Frete.
- **Label motivo no espelho:** "⚠ NF-e cancelada no ERP" se `c.empresa_nf`; "🚫 CT-e Cancelado" se `c.data_cancelamento`; senão "⚠ Motivo sem vínculo".
- **Seções do espelho para CTe cancelados:** `esp_cancel_section` (data + justificativa), `esp_subst_section` (verde — dados do substituto), `esp_no_subst_section` (aviso sem substituto).

### Funções reativas NC e Cancelados (segurança da informação)
- `_renderNC()` — filtra `DATA.ctes_nf_cancelada` por `empresa_nf === state.empresa` quando empresa ativa
- `_renderCancel()` — filtra `DATA.cancelados_data` por `empresa === state.empresa` quando empresa ativa
- Ambas expostas em `window` e chamadas dentro de `window._renderNV` (que por sua vez é chamado de `renderAll` quando a aba NV está ativa)
- **NÃO são IIFEs** — rodam a cada mudança de filtro

### Integração com filtros globais
- `renderAll()` chama `window._renderNV()` quando aba NV está ativa → dispara NV + NC + Cancelados
- Tab click handler chama `window._renderNV()` ao entrar na aba
- Filtros aplicados: `state.ano`, `state.meses`, `state.empresa`, `state.empresas`
- Filtros NÃO aplicados ao NV: `state.transp`, `state.linha`, `state.natop`, `state.canal`, `state.nicho`

### Modal Espelho CT-e
- Abre com `window._nvShowEspelho(cte_chave)`
- Campos exibidos: transportadora + CNPJ, número/série/data/chave 44 dígitos, origem→destino, valor + peso, remetente, destinatário, tomador Humana, NF-e referenciadas, motivo
- Botão **Imprimir / Salvar PDF** via `window.print()` com `@media print` que esconde tudo exceto `#nv-espelho-print`
- Fechar: clique fora do modal ou botão "Fechar"

## Comportamento de inicialização

- **Ano padrão:** ao carregar, `initApp()` pré-seleciona o ano mais recente disponível nos dados (`anos[anos.length-1]` após `.sort()`). Avança automaticamente quando chegar 2027+.

### `state` — objeto global de filtros
```javascript
const state={ano:'',meses:[],empresas:[],linha:'',natop:[],estado:'',transp:'',canal:'',nicho:'',q:'',categoria:''};
```
`nicho` (string) — preenchido pelo drill-down da visão Nicho em `natopDrillDown()`; limpo via chip `×` em `updateTags()`; aplicado em `filterRows()` como `d.nicho !== state.nicho`.

## Filtros do Topbar — Multiselect (index.html)

Padrão `.ms-wrap > .ms-btn + .ms-dropdown` usado pelos 3 filtros multiselect do topbar: Mês (`ms_mes_*`), Empresa (`ms_emp_*`) e Nat. Operação (`ms_natop_*`, dentro de "Mais filtros"). Cada um segue a mesma estrutura: botão (`.ms-btn`) que abre um dropdown `position:fixed` (`.ms-dropdown`) com um checkbox "Todos" no topo + opções (`.ms-opt`), e uma função `sync*()` que recalcula `state.*` a partir dos checkboxes marcados e chama `renderAll()`.

### Grade de meses (jul/2026)
O filtro de Mês foi trocado de lista vertical de checkboxes (rolagem, itens pequenos) para uma grade `.mes-grid` de 4×3 chips clicáveis — todos os 12 meses visíveis sem rolar. Implementação:
- Os 12 `.ms-opt` dos meses ficam dentro de um `<div class="mes-grid">` separado do checkbox "Todos os meses" (que continua fora da grade, como linha própria)
- Checkbox de cada mês fica `display:none`; o `<label for="mes_XX">` ocupa o chip inteiro (clique em qualquer ponto do chip aciona o checkbox associado nativamente — sem JS extra de clique)
- `.ms-opt.active` (aplicada/removida em `syncMeses()` a cada mudança) estiliza o chip selecionado; `updateTags()` também precisa marcar/desmarcar `.active` ao limpar o filtro via chip `×` (não só `checked`)
- Esse padrão de grade (chip com label cobrindo a área toda) pode ser reaproveitado para outros multiselects com poucas opções fixas no futuro

### `_msPosition(btn, drop)` — posicionamento dos dropdowns (jul/2026)
Helper global que substitui o cálculo manual de `top`/`left` que cada multiselect fazia no próprio `click` handler. **Motivo:** `header.topbar` usa `backdrop-filter: blur(20px)`, e isso torna o header o *containing block* dos filhos `position:fixed` (mesma regra do CSS que se aplica a `transform`/`filter`/`will-change`). Como `.ms-dropdown` é `position:fixed`, `left`/`top` calculados com `btn.getBoundingClientRect()` (coordenadas relativas ao *viewport*) ficavam deslocados — o dropdown abria ao lado/abaixo da posição errada, tanto mais quanto maior o offset do header em relação à viewport (ex.: sidebar lateral empurra o header para a direita).
```javascript
function _msPosition(btn,drop){
  const r=btn.getBoundingClientRect();
  const cb=(btn.closest('header')||document.body).getBoundingClientRect();
  drop.style.top=(r.bottom-cb.top+4)+'px';
  drop.style.left=(r.left-cb.left)+'px';
  drop.style.right='auto';
}
```
Corrige subtraindo a posição do próprio `header` (o containing block real) antes de aplicar. **Não seria possível trocar para `position:absolute`** — `.topbar-row2` tem `overflow-y:hidden` (para permitir scroll horizontal dos filtros em telas estreitas), o que cortaria um dropdown absolute; por isso o `position:fixed` + correção manual é necessário.
Usado pelos 3 dropdowns (`ms_mes_drop`, `ms_emp_drop`, `ms_natop_drop`) no lugar do cálculo inline duplicado.

## Globals críticos (ordem importa)

Declarar no bloco de globals (antes de `onAuthStateChanged`) para evitar TDZ:
- `let DATA = null`
- `let _currentUser = null`
- `let nvAllRows = [], nvBase = [], nvPage = 0, nvRows = []`
- `let CNPJ_EMPRESA = {}`  ← Firebase v8 pode invocar onAuthStateChanged sincronamente
- `const _cnpjNameCache = (()=>{try{return JSON.parse(localStorage.getItem('_cnpjNC')||'{}')}catch{return {};}})()` ← cache CNPJ→nome

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

## Módulo Delivery — `delivery` (index.html)

Mede o custo com entregadores autônomos (NFS-e de serviço de transporte emitidas para o grupo Humana), não o frete por CTe. Abandonou a abordagem inicial via romaneio do ERP — implementado via busca de NFS-e na API Arquivei.

### Pipeline de dados
```
QUIVE/importar_entregadores.py     ← importa XLSX de referência (nome+CPF/CNPJ+empresa) → tabela entregadores
QUIVE/buscar_nfse_entregadores.py  ← busca NFS-e via API Arquivei (POST /v1/dfe/nfse, emitterCnpj=entregadores, takerCnpj=grupo) → tabela nfse_entregadores
Frete/processar_frete.py           ← _carregar_nfse_entregadores() → campo "delivery" no payload
index.html                         ← aba Delivery (tab-delivery)
```

### Tabelas SQLite (cte.db)
| Tabela | Conteúdo |
|---|---|
| `entregadores` | Referência cadastral: `cnpj_entregador`, `nome_entregador`, `cnpj_empresa` (recriada a cada import) |
| `nfse_entregadores` | NFS-e emitidas pelos entregadores: `id` (PK), `empresa`, `emit_cnpj`, `emit_nome`, `numero`, `competencia`, `dt_emissao`, `valor_servico`, `status` |

### `_carregar_nfse_entregadores()` (processar_frete.py)
- Filtra `status = 'Authorized'` (ignora NFS-e canceladas/rejeitadas)
- `LEFT JOIN entregadores` por `(cnpj_entregador, cnpj_empresa)` — usa `nome_entregador` cadastrado, com fallback para `emit_nome` da própria NFS-e
- Campos do payload: `id, empresa, entregador_nome, numero, competencia, data_emissao, valor_servico`
- **`entregador_cnpj` não publicado no Firestore** (LGPD — CPF/CNPJ de pessoa física via MEI). Permanece somente no `cte.db` local.
- Datas convertidas via `fmt_date()` para `DD/MM/YYYY`

### `renderDelivery()` (index.html)
- Filtros: empresa (select + `state.empresas`), ano/mês (`state.ano`/`state.meses` sobre `data_emissao.slice(6,10)`/`slice(3,5)`), busca por nome/número
- KPIs: `dlv_qtd`, `dlv_total`, `dlv_medio`, `dlv_qtd_entreg` (entregadores únicos por CNPJ) — `dlv_total`/`dlv_medio` têm chip de tendência (`dlv_total_trend`/`dlv_medio_trend`)
- Card **"Delivery vs. Frete Tradicional"** (`dlv_vs_cte`) — compara custo com entregadores autônomos × frete CT-e (`filteredRows`) no mesmo período/empresas filtrados: barra dupla + "a cada R$100 gastos com logística de saída, R$X fica com entregadores e R$Y com transportadoras". Usa `dlvGlobalRows` (filtrado só pelos filtros globais, sem os locais da aba) para comparação justa com `filteredRows`
- Gráfico `ch_dlv_mensal` — evolução mensal do custo total (`mkBar`)
- Tabela "Mapa de Desempenho por Empresa" — qtd, total, ticket médio, entregador top por empresa
- Ranking "Valor médio cobrado por entregador" — ordenado por ticket médio (`Valor Médio/NFS-e` = total ÷ qtd) decrescente. Coluna adicional **`Valor Médio/Dia`** = total ÷ dias corridos entre a primeira e a última `competencia` do entregador no período filtrado (helper `_dlvDt` parseia `DD/MM/YYYY` → timestamp UTC). **Atenção:** não usar "nº de competências distintas" como divisor — coincide quase sempre com a qtd de NFS-e (cada nota tende a ter `competencia` própria) e zera a diferença com o ticket médio
- Tabela detalhada paginada (`dlv_tbody` / `mkPager`)
- `_dlvPrevRows()` — espelha `_geoPrevRows()` do módulo Geográfico para achar o período de comparação (mês anterior se 1 mês selecionado, ano anterior se só ano selecionado, filtrando `DATA.delivery` por `data_emissao`)
- Exposta via `window._renderDelivery` — chamada pelo tab switching quando aba `delivery` ativa

## Módulo Transferências — `transferencias` (index.html, jul/2026)

Aba dedicada para analisar o frete de natureza "transferência" (movimentação de mercadoria entre unidades do próprio grupo), extraída da aba Por Empresa a pedido de um levantamento externo (planilha "Levantamento Geral": Unidade × Mês × Fretes Gerais/Delivery/Transf. Matriz→Unidade/Transf. Unidade→Matriz/Entre Unidades/Total). Todo o cálculo é feito no frontend, sem alteração no `processar_frete.py` — reaproveita `DATA.detalhes` (CT-e vinculados) e `DATA.delivery` (NFS-e de entregadores) já publicados.

### Matriz e classificação de direção
- `MATRIZ_UNIDADE='BRU1'` — constante global, única unidade tratada como matriz/centro de distribuição
- `_transfDestino(d)` — resolve a empresa do grupo destinatária via `CNPJ_EMPRESA[d.dest_cnpj]` (mesma lógica de `isTransferencia()`, mas isolada)
- `_transfCategoria(d)` — classifica uma linha em 3 categorias com base em **origem = `d.empresa`** (empresa emissora da NF-e/CT-e de saída) e **destino = `_transfDestino(d)`**:
  - `null` — destino não é uma unidade do grupo (não entra nas 3 categorias, mas soma no total "Fretes Gerais"/`geral`)
  - `'m2u'` — origem é a Matriz (BRU1 enviando para outra unidade)
  - `'u2m'` — destino é a Matriz (unidade enviando de volta pra Matriz)
  - `'entre'` — nem origem nem destino é a Matriz (lateral entre duas unidades)
- **Atenção:** a categoria é atribuída à linha do **emissor** (`d.empresa`), não ao destinatário — por isso na tabela "Levantamento Geral" a linha da própria BRU1 é que carrega os valores de "Transf. Matriz→Unidade" (é ela quem gerou o CT-e/NF-e de saída), não a unidade que recebeu

### `_transfBuildLevantamento(rows)` — Levantamento Geral (Unidade × Mês)
- Agrega `rows` (CT-e vinculados, `filterRows(DATA.detalhes,{excMkt:true})`) + `_transfDeliveryRows()` (`DATA.delivery` filtrado pelos filtros globais ano/mês/empresa, mesmo padrão do card "Delivery vs. Frete Tradicional") em um dict por chave `"emp|ano|mes"`
- Cada bucket: `{emp,ano,mes,geral,delivery,m2u,u2m,entre}` — `geral` soma **tudo** (comercial + as 3 categorias de transferência + delivery), as demais são quebras
- **`ano`/`mes` extraídos de `d.data`/`d.data_emissao` (formato `DD/MM/YYYY`)** via `slice(6,10)`/`slice(3,5)` — mesmo padrão usado em `_transfDeliveryRows`/`dlvGlobalRows`

### KPIs, gráfico e tabela principal
- 4 KPIs (`_transfRenderKPIs`): Frete Delivery, Transf. Matriz→Unidade, Transf. Unidade→Matriz, Frete Entre Unidades — cada um com % sobre o total geral do levantamento filtrado
- `_transfRenderEvolucao(lvt)` — gráfico `ch_transf_evol` (stacked, `mkStacked`) com evolução mensal das 4 categorias. **Chave de ordenação `ano+'-'+mes` (não `mes+'/'+ano`)** — string sort em `"MM/YYYY"` quebra virada de ano (ex. `"01/2026"` ordenaria antes de `"12/2025"`); ver mesmo cuidado em `ch_dlv_mensal` no módulo Delivery
- `_transfRenderLevantamento(lvt)` — tabela `transf_lvt_tbody`, 1 linha por unidade/mês, guarda o array em `_transfLvtRows` para o export. Também preenche `<tfoot id="transf_lvt_tfoot">` com a soma de cada coluna numérica (`geral,delivery,m2u,u2m,entre`) sobre o `lvt` já filtrado — linha "Total" com `position:sticky;bottom:0` para ficar visível mesmo rolando a tabela (`max-height:70vh`)
- `transfExportXLSX()` — exporta `_transfLvtRows` com as mesmas colunas/nomes da planilha de referência que originou o pedido (Unidade, Mês, Fretes Gerais, Frete Delivery, Frete Transferência Matriz→Unidade, Frete Transferência Unidade→Matriz, Frete Entre Unidades, Total Fretes), formatação `R$` via `.z` nas colunas monetárias (mesmo padrão de `compExportXLSX`/`dlvExportXLSX`)

### `_transfBuildDetalhe(rows)` — Detalhes por NF-e (validação do Levantamento Geral)
Card logo abaixo do Levantamento Geral, com 1 linha por NF-e/CT-e de transferência (não agregado) — usado para confirmar manualmente os totais da tabela agregada.
- Filtra `rows` (mesmo `filterRows(DATA.detalhes,{excMkt:true})` do restante da aba) por `_transfCategoria(d)` truthy — ou seja, **só as 3 categorias de transferência** (`m2u`/`u2m`/`entre`), não inclui Delivery nem o comercial
- Cada linha guardada em `_transfDetRowsAll`: `{numero,data,empresa,categoria,destino,transportadora,peso_kg,valor_frete,total_nf,cte_chave}` — `total_nf` é o valor da NF-e (`d.total_nf`), adicionado especificamente para comparar com o frete
- **Ordenação:** `_transfDtKey(data)` converte `DD/MM/YYYY` → `YYYYMMDD` para sort cronológico correto (evita o mesmo problema de sort textual em `"MM/YYYY"` do gráfico de evolução); critério secundário `valor_frete` desc para linhas do mesmo dia
- `_transfDetFiltered()` aplica os filtros locais da tabela (chips de categoria `transfDetCat` + busca `transfDetSearch` sobre `numero+transportadora+cte_chave+destino`) sobre `_transfDetRowsAll` — reaproveitado tanto pelo render quanto pelo export, para os dois sempre respeitarem o mesmo filtro ativo
- `setTransfDetCat(val)` alterna os 4 chips (`transf_det_f_all/m2u/u2m/entre`, classe `cat-btn` — mesmo padrão visual do filtro de Saldo na aba Operacional) e zera a página
- Paginação via `mkPager` (`PAGE` global, mesmo tamanho configurável usado em Operacional/Delivery/Cliente)

**Colunas da tabela (`transf_det_tbody`) e do export (`transfDetExportXLSX`):** NF-e, Data, Unidade, Categoria (chip colorido conforme a categoria), Destino, Transportadora, Peso, **Valor NF** (`r.total_nf`, valor da mercadoria), Valor Frete, **% Frete/NF** (`valor_frete/total_nf*100`, cor verde ≤8%, amarelo ≤15%, vermelho >15% — thresholds de leitura rápida por linha, não os mesmos usados nos KPIs agregados de Visão Geral), Chave CT-e.
- Guard `r.total_nf?...: '-'`/`:0` em ambos os lugares — evita `Infinity%`/divisão por zero quando `total_nf` vier zerado
- Export usa o mesmo padrão de `.z='"R$"#,##0.00'` nas colunas monetárias (`Valor NF (R$)`, `Valor Frete (R$)`), aplicado via loop nos dois headers depois do `json_to_sheet`

### Seções herdadas da aba Por Empresa (renomeadas, lógica intacta)
Movidas de `emp_*`/`_empRender*` para `transf_*`/`_transfRender*` — nenhuma mudança de comportamento, só remoção do escopo de "Por Empresa":
- `_transfRenderComercialOp` — KPIs Comercial vs Operacional + gráfico `ch_transf_tipo` + tabela "Custo Operacional por Empresa" (`transf_tbody`) — usa `isTransferencia(d)` (regex `NAT_TRANSF` OU destino no grupo), mais abrangente que `_transfCategoria` (não exige direção específica)
- `_transfRenderHumana` — "Transferências entre Lojas do Grupo" (KPIs + tabela `transf_hu_tbody` "Detalhe por Empresa Origem x Loja Destino") — filtra por `HU_CLI` (cliente contém "HUMANA ALIMENTAR"), critério diferente de `isTransferencia`/`_transfCategoria` (usa o nome do cliente na NF, não o `dest_cnpj`)
- `_transfRenderSemCte` — tabela `transf_sem_cte_tbody`, NF-e de transferência (`DATA.transf_sem_cte`, populado por `processar_frete.py`) sem CT-e vinculado
- `_periodoLabelHTML(rows)` — helper extraído (antes duplicado dentro de `_empRenderPeriodo`) para montar o texto "Exibindo: ..." dos banners de período; usado tanto por `_empRenderPeriodo` (Por Empresa) quanto por `_transfRenderPeriodo` (Transferências)

### `renderTransferencias()`
Orquestra tudo: filtra `rows`, calcula `freByEmp` via `_empAggregate` (reaproveitado de Por Empresa), constrói `lvt` via `_transfBuildLevantamento`, chama os renders acima na ordem KPIs → evolução → levantamento → detalhes por NF-e (`_transfBuildDetalhe`+`_transfRenderDetalhe`) → comercial/op → grupo → sem CTe → período. Chamada pelo tab-switch (2 lugares: click handler e `renderAll()`) quando `tab==='transferencias'`.

### Não replicado no `HTML_TEMPLATE`
Mesma ressalva do módulo Marketplace: `HTML_TEMPLATE` em `processar_frete.py` não tem a aba Transferências — só afeta o `dashboard_frete.html` standalone local, não o app publicado no GitHub Pages.

## Módulo Separação — `separacao` (index.html, jul/2026)

Produtividade de picking por unidade: quantidade de pedidos e itens separados no armazém, a partir do `nf_saida_items` item-a-item (não `vw_nf_saida`, que já vem agregado por NF-e — aqui a granularidade de `qtd_itens` é necessária).

### `_calcular_separacao()` (processar_frete.py)
- Lê `nf_saida_items` direto (empresa, chave, data_emissao, canal, qtd_itens, descricao_item), agrupa em memória por chave flat `"emp|ano|mes"`
- `qtd_itens` é `TEXT` com formato brasileiro (`"1,00"`, `"2.100,00"` com separador de milhar) — **usar sempre `br_float()`**, nunca `float(s.replace(',','.'))` direto (quebra silenciosamente em valores com milhar, ex. `"2.100,00"` vira `2.1`)
- LinhaHum vs Humana: mesmo critério já usado em `_parse_single_fat`/`cruzar()` — `"LINHAHUM" in descricao_item.upper()`. "Humana Alimentar" aqui é o complementar (tudo que não é LinhaHum: Fresubin, Trophic, etc.), não o total geral
- Dia da semana calculado via `datetime(ano,mes,dia).weekday()` (0=Segunda) — rótulos em português

### Dois dicts, tamanhos diferentes por design (ver pitfall do limite 1MB abaixo)
| Campo | Onde vive | Filtrado por empresa? | Conteúdo |
|---|---|---|---|
| `resumo.separacao_por_emp_ano_mes` | dentro de `resumo` (como `nfe_fat_por_emp_ano_mes`) | **Não** — embutido inteiro (todas empresas) em todo doc | Só `{pedidos, itens_total, itens_linhahum, itens_humana}` — leve (~23 KB), permite ranking cruzando empresas mesmo pra usuário restrito a 1 empresa |
| `separacao_detalhe` | top-level do payload (como `detalhes`/`compras`) | **Sim** — `split_by_empresa` filtra por prefixo `"{emp}|"` | Os mesmos 4 números + `por_canal`/`por_dow` — pesado (breakdown por canal/dia), só faz sentido escopado à própria empresa |

### Frontend (index.html)
- `_sepBase(ignoreEmpresa)` — itera `DATA.resumo.separacao_por_emp_ano_mes`; `ignoreEmpresa=true` usado **só** pelo ranking geral entre unidades (compara todas as empresas do período, ignora `state.empresas`); `false` usado pelos 4 KPIs (respeita todos os filtros globais)
- `_sepDetalhe()` — itera `DATA.separacao_detalhe`; sempre respeita `state.empresas` (dict já vem filtrado por empresa do backend, então nunca teria dado de outra empresa mesmo sem o filtro)
- `mkBarQtd(id,lbs,vals,color,lbl)` — variante de `mkBar` para quantidades (não BRL), usa `N()` nos eixos/tooltip
- `_mergeData()` mescla os dois: `separacao_por_emp_ano_mes` (dentro de `resumo`) via `Object.assign` simples (todo doc já tem tudo); `separacao_detalhe` (top-level) via `Object.assign` também, mas aqui cada doc só contribui as próprias chaves — o merge reconstrói a visão completa pra quem tem acesso a múltiplas empresas

## Pitfalls conhecidos

- **Limite de 1MB por documento Firestore — BRU1 já opera perto do teto** — o doc principal de cada empresa (tudo exceto `detalhes`, que são chunkados) precisa ficar abaixo de ~1024 KB. Em jul/2026, BRU1 estava em 978 KB (era 981 KB antes até do módulo Separação existir) — **~46 KB de margem**, a menor entre as 8 empresas por ser a maior filial. Campos que NÃO são filtrados por empresa (embutidos inteiros em todo doc) são os primeiros suspeitos ao investigar crescimento: `cnpj_nomes` (filtrado desde jul/2026 aos CNPJs de fato usados via `part_cnpj` em `detalhes` — única leitura no frontend é `_cliClientCell` na aba Por Cliente), `nfe_fat_por_emp_ano_mes`, `cte_conc_por_emp_ano_mes`, `separacao_por_emp_ano_mes` (todos pequenos, ok ficarem globais). **Antes de adicionar qualquer novo campo global ao payload, medir o impacto em KB no doc da BRU1** (o maior) com `json.dumps(...).encode('utf-8')` — se for pesado (breakdown por sub-categoria, por dia, etc.), preferir o padrão de `separacao_detalhe`: campo top-level filtrado por empresa em `split_by_empresa`, não dentro de `resumo`.
- **`position:fixed` + `backdrop-filter` no ancestral = containing block trocado** — `header.topbar` tem `backdrop-filter:blur(20px)`, o que o torna o *containing block* de qualquer descendente `position:fixed` (mesma regra de `transform`/`filter`/`will-change`). Definir `left`/`top` de um elemento fixed com coordenadas de `getBoundingClientRect()` (relativas ao viewport) sem descontar a posição do header dá elemento deslocado. Ver `_msPosition()` na seção "Filtros do Topbar — Multiselect". Vale para qualquer novo elemento `position:fixed` criado dentro do `header`.

- **`position:fixed` + `backdrop-filter` no ancestral = containing block trocado** — `header.topbar` tem `backdrop-filter:blur(20px)`, o que o torna o *containing block* de qualquer descendente `position:fixed` (mesma regra de `transform`/`filter`/`will-change`). Definir `left`/`top` de um elemento fixed com coordenadas de `getBoundingClientRect()` (relativas ao viewport) sem descontar a posição do header dá elemento deslocado. Ver `_msPosition()` na seção "Filtros do Topbar — Multiselect". Vale para qualquer novo elemento `position:fixed` criado dentro do `header`.
- **`HTML_TEMPLATE` duplicado em `processar_frete.py`** — gera o `dashboard_frete.html` standalone com HTML/JS quase idêntico ao `index.html`. Mudanças de UI/JS em qualquer aba presente no template (ex.: Marketplace) precisam ser replicadas manualmente nos dois arquivos — ver seção "Módulo Marketplace"
- **SDK Firebase v8** — usar v8.10.1 compat. v10 causa falha no WebChannel
- **Encoding Python** — sempre `$env:PYTHONIOENCODING = "utf-8"` antes de rodar scripts
- **Faturamento período** — NF de Nov/Dez 2024 e Jan 2025 ainda ausentes; exportar do ERP
- **~340 CTe sem vínculo** — não têm NF referenciada, investigação via espelho CT-e na aba Cobertura de Dados
- **`ctes_nao_vinculados` por empresa** — `_split_por_empresa()` usa `_nv_emp(c)` (rem_cnpj → nfe_refs) para filtrar por empresa. CTes sem empresa identificada entram em TODOS os documentos. `ctes_nf_cancelada` filtrado por `empresa_nf`. Antes deste fix, ALL CTes iam para TODOS os documentos.
- **Cobertura de Faturamento baixa (~46%)** — ~65k "Venda de Mercadoria" sem CTe são provavelmente retiradas no depósito (Caminho B: identificar flag de retirada no ERP para excluir do denominador)
- **`_effDen()` deve ser global** — definir ANTES de `renderInsights` e `renderAll`. Se definida dentro de `renderAll`, causa `ReferenceError` silencioso que impede renderização de todos os blocos posteriores (gráficos, heatmap, etc.)
- **Dev.Mkt data format** — `devolucoes_mkt.data_emissao` está em `DD/MM/YYYY` (igual a `compras`). Slice correto: ano=`slice(6,10)`, mês=`slice(3,5)`. Não usar `slice(0,4)`/`slice(5,7)` (formato YYYY-MM-DD)
- **Filtros respeitam empresa em todos os módulos** — `_renderNC` filtra por `empresa_nf` (via `state.empresas`), `_renderCancel` por `empresa` (via `state.empresas`), cards Visão Geral usam `_effDen()`, Integridade usa `cte_conc_por_empresa`. Qualquer novo KPI deve ser auditado para não usar valor global quando empresa filtrada. **Não usar `state.empresa` (removido) — usar sempre `state.empresas`**
- **Conflito de push git** — uploads via interface web do GitHub divergem do local; usar `git fetch && git reset --soft origin/main`
- **Duplicatas nos filtros** — `initApp()` usa `_initAppDone` para não re-adicionar opções; selects limpos com `clr()` antes de popular; select de transportadora populado via `_populateTranspSelect()` (não `addOpt` direto)
- **Destinatário em transferências** — `CNPJ_EMPRESA[cnpjRaw]` onde `cnpjRaw = d.part_cnpj.replace(/\D/g,'')` normaliza formatação antes do lookup; empresas do grupo exibidas em laranja com CNPJ formatado abaixo
- **`input()` no processar_frete.py** — envolvido em `try/except EOFError` para não travar execução automática
- **Chart.js guard** — `if(typeof Chart!=='undefined')` obrigatório antes de qualquer config de Chart.js; falha de CDN derruba o script inteiro por TDZ em cascata
- **`nat_op_sem_cte` e `cnpj_nomes` devem estar em `split_by_empresa`** — campos globais copiados inteiros para cada documento de empresa. Se omitidos, chegam como `{}` no frontend. Regra geral: qualquer campo global novo no payload de `processar_frete.py` precisa ser adicionado explicitamente em `split_by_empresa`.
- **`sqlite3.Row` não tem `.get()`** — ao ler campos de `vw_nf_saida` ou qualquer query SQLite com `row_factory = sqlite3.Row`, usar sempre `r["campo"]` (KeyError se ausente) ou `dict(r).get("campo","")` para acesso seguro. Nunca `r.get("campo")` — isso causa `AttributeError` silenciado pelo fallback de CSV, zerando todo o faturamento e gerando payload de 11MB no Firestore.
- **Crescimento do `cte.db`** — está em ~684 MB (jun/2026) e cresce continuamente (CTe + faturamento + NF entrada + NFS-e entregadores). Acompanhar via coluna `tamanho_mb` no Log de Importações (Admin); thresholds visuais: amarelo ≥1GB, vermelho ≥2GB. Se ficar grande demais para a máquina local, considerar migração para outro local ou Supabase (plano gratuito)
- **`cte.db` sem backup** — nenhum script faz cópia de segurança; é um banco único numa só máquina. Maior risco de perda de dados do projeto. Ao mexer no `atualizar.py`, considerar adicionar cópia datada para nuvem (ver "Gaps de segurança/resiliência conhecidos")
- **Repo público — não versionar dados** — qualquer arquivo com dados reais embutidos vaza sem autenticação (inclusive via histórico Git). Ver seção "Segurança e LGPD". `.gitignore` não desfaz tracking de arquivos já commitados — conferir antes do primeiro `git add`
- **Novo script de importação/busca deve registrar no log** — todo script que grava em `cte.db` deve chamar `import_log.registrar(conn, script, origem, fonte, registros, novos, erros, status, detalhes)` ao final do `main()` (sucesso) e no `except` (erro fatal, com `raise` simples para preservar o traceback). Ver seção "Log de Importações — Painel Admin" para o padrão completo
