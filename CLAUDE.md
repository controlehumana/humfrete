# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Reset de senha de usuário (Admin)

O painel Admin **não é capaz de trocar a senha de um usuário existente** — o campo "Senha" só funciona ao criar um usuário novo (`createUserWithEmailAndPassword`). Alterar a senha de outro usuário exigiria uma Cloud Function com Admin SDK (o SDK client-side não permite), e isso requer o plano Blaze (pay-as-you-go) no Firebase — **decisão consciente do usuário de não migrar para Blaze** (evita precisar cadastrar cartão de crédito no projeto).

**Workaround oficial:** rodar `reset_senha.js` (raiz de `Frete/`, **versionado desde ago/2026** — antes só existia na máquina local e se perderia numa troca de máquina; o script não carrega segredo, lê o `serviceAccountKey.json` em runtime, e esse arquivo está no `.gitignore` e nunca foi rastreado) localmente:
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
Executa: importa Faturamento → importa Volumetria → download CTe **D-3 a D-1** → importa NF Entrada → cria views → sobe Firestore.
A janela D-3 a D-1 garante que o sábado seja capturado quando o script roda na segunda-feira.

### Manual (após exportar do ERP)
```
py atualizar_sem_download.py   ← pula download, importa arquivos, processa e publica
```

### Pastas de entrada (ERP → banco)
```
ClaudeCode\Faturamento\      ← qualquer nome, qualquer período, acumula sem duplicar
ClaudeCode\NF_Entrada\       ← relatório NF de Entrada, acumula sem duplicar
ClaudeCode\Volumetria\       ← relatório de Volumetria por Transportadora, acumula sem duplicar
```

**`Volumetria/` (jul/2026):** relatório do ERP `adm_trans_volumetria` (`https://gestao.humanaalimentar.com.br/erp/_man/controle.php?adm_trans_volumetria`, export em `relatTransVolumetria.php?dt_inicio=...&dt_fim=...&filtro_empresa=TODAS&filtro_canal=...`). Uma linha por NF-e de saída com `CODIGO_TRANSPORTADORA`/`RAZAO_TRANSPORTADORA` — para entregas via entregador autônomo, esse código é o CNPJ do entregador (bate direto com `entregadores.cnpj_entregador`). Usado para medir o volume real de entregas de cada entregador (módulo Delivery), já que `nfse_entregadores` só tem o valor cobrado, não quantas entregas ele fez. Exportação manual do ERP por enquanto — sem automação via Playwright (diferente de `Faturamento/exportar_faturamento.js`).
**Lacuna ago–dez/2025 preenchida (ago/2026):** faltava esse período no banco, o que aparecia como buraco na série do módulo Delivery. Usuário exportou o relatório do ERP e a importação trouxe **34.297 linhas novas** (`volumetria_nfe`: ~96k → **130.820**). Série de entregas por entregador agora é contínua nos 19 meses (jan/2025–jul/2026). O importador usa `INSERT OR IGNORE` por `chave_acesso`, então reimportar arquivo já processado é seguro (0 novas) — foi o que aconteceu com o arquivo anterior que continuava na pasta.

**`Faturamento/` — fix do fluxo de pastas (2026-07-30):** `exportar_faturamento.js` salvava o CSV novo em `Faturamento/exports/`, mas `importar_faturamento.py` (`_find_latest()`) só lê a raiz de `Faturamento/` — os exports diários da tarefa agendada nunca eram vistos pela etapa 0a. Corrigido: o script agora salva o novo arquivo direto na raiz e move o anterior para `exports/` (que virou pasta de arquivo morto, sem leitura automática). Detalhes em `Faturamento/CLAUDE.md`.

## Scripts principais

| Script | O que faz |
|---|---|
| `atualizar.py` | Orquestrador completo D-3→D-1 automático (4 etapas) |
| `atualizar_sem_download.py` | Igual mas pula download da API |
| `importar_faturamento.py` | Importa CSV de faturamento → `nf_saida_items` |
| `importar_nf_entrada.py` | Importa XLS de NF Entrada → `nf_entrada` |
| `QUIVE/importar_volumetria.py` | Importa CSV de Volumetria (todos os arquivos da pasta) → `volumetria_nfe` |
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
  Volumetria/                   # Relatórios de Volumetria por Transportadora do ERP (qualquer nome)
  QUIVE/
    buscar_cte.py               # Baixa CTe da API Qive → cte.db
    criar_view.py               # Parseia XMLs → tabelas cte_campos, cte_nf
    importar_entregadores.py    # Importa XLSX de referência → tabela entregadores
    buscar_nfse_entregadores.py # Busca NFS-e dos entregadores via API Arquivei → nfse_entregadores
    importar_volumetria.py      # Importa relatório de Volumetria (todos os .csv da pasta) → volumetria_nfe
    import_log.py               # Helper compartilhado: registra execuções na tabela import_log
    cte.db                      # SQLite: CTe + faturamento + NF entrada + delivery + volumetria + log
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
| `volumetria_nfe` | Volume real de entregas por NF-e (relatório de Volumetria do ERP) — usado para cruzar com `entregadores` e `nfse_entregadores` |
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
| `users/{uid}` | Leitura: próprio uid ou admin; escrita: usuário não pode alterar `isAdmin`/`empresas`/`tabs`; deleção: **somente admin** (jul/2026 — antes era bloqueada para todos, `allow delete: if false`, o que deixava o botão "Excluir" do painel Admin sempre falhando com "Missing or insufficient permissions") |

`empresaDoDoc(docId)` = `docId.split('_det_')[0]` → extrai `BRU1` de `BRU1_det_000`.

### Exclusão de usuário — painel Admin (`adminDeleteUser`, jul/2026)
- Botão "Excluir" chama `_db.collection('users').doc(uid).delete()` — remove **só o documento de perfil/permissões no Firestore**, não a conta de login no Firebase Auth (o usuário continua existindo no Auth, mas sem `users/{uid}` o app bloqueia o acesso com a tela de erro "Seu acesso não está configurado...")
- Guard de segurança: `adminDeleteUser` bloqueia auto-exclusão (`uid===_currentUser.uid`) — sem isso, um admin poderia se excluir e ficar sem acesso ao próprio painel, precisando do Firebase Console para reverter
- Se precisar remover também a conta de login (Firebase Auth), não há isso no painel — usar o Firebase Console → Authentication, ou um script Admin SDK (mesmo padrão do `reset_senha.js`)

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
| `volumetria_nfe` | NF-e de saída do relatório de Volumetria: `chave_acesso` (PK, 44 dígitos), `empresa`, `numero_nfe`, `canal`, `data_emissao` (DD/MM/YYYY), `qtd_itens`, `peso_kg`, `volume_m3`, `transp_cnpj`, `transp_nome`, `total_nf` + colunas de cidade (ago/2026): `emit_cidade`/`emit_uf`/`emit_cod_cidade`, `dest_cidade`/`dest_uf`/`dest_cod_cidade`/`dest_cep` |

**Colunas de cidade e o upsert do `importar_volumetria.py` (ago/2026):** as 7 colunas acima foram adicionadas via `ALTER TABLE` idempotente e são preenchidas por um `INSERT ... ON CONFLICT(chave_acesso) DO UPDATE` que **só toca as colunas de cidade, e só quando ainda estão vazias**. O `INSERT OR IGNORE` original foi mantido em espírito para todo o resto: correções feitas à mão no banco (ex.: a transportadora da RIBEIRANIA) não podem ser desfeitas por uma reimportação do mesmo CSV. Como o upsert também toca linhas existentes, `cur.rowcount` deixou de distinguir novo de atualizado — a contagem de "novos" passou a ser `COUNT(*)` antes/depois do arquivo. **Cobertura: só as linhas dos CSVs que estiverem na pasta `Volumetria/` no momento da importação são preenchidas** (42.129 de 130.820 hoje); as demais caem no fallback de `part_cidade` do faturamento. Para preencher o resto, reexportar os períodos antigos do ERP e rodar de novo.

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
- Cada bucket: `{emp,ano,mes,geral,venda,delivery,m2u,u2m,entre}` — `geral` soma **tudo** e é sempre igual a `venda+delivery+m2u+u2m+entre` (verificado por construção: toda linha de `rows` cai em exatamente uma categoria — `venda` quando `_transfCategoria(d)` é `null` — mais `delivery` somado separadamente); `venda` foi adicionada explicitamente (antes só existia embutida em `geral`, sem coluna própria) a pedido do usuário para deixar visível que "Fretes Gerais" é a soma das colunas ao lado, não um número solto
- **`ano`/`mes` extraídos de `d.data`/`d.data_emissao` (formato `DD/MM/YYYY`)** via `slice(6,10)`/`slice(3,5)` — mesmo padrão usado em `_transfDeliveryRows`/`dlvGlobalRows`

### KPIs, gráfico e tabela principal
- 4 KPIs (`_transfRenderKPIs`): Frete Delivery, Transf. Matriz→Unidade, Transf. Unidade→Matriz, Frete Entre Unidades — cada um com % sobre o total geral do levantamento filtrado
- `_transfRenderEvolucao(lvt)` — gráfico `ch_transf_evol` (stacked, `mkStacked`) com evolução mensal das 4 categorias. **Chave de ordenação `ano+'-'+mes` (não `mes+'/'+ano`)** — string sort em `"MM/YYYY"` quebra virada de ano (ex. `"01/2026"` ordenaria antes de `"12/2025"`); ver mesmo cuidado em `ch_dlv_mensal` no módulo Delivery
- `_transfRenderLevantamento(lvt)` — tabela `transf_lvt_tbody`, 1 linha por unidade/mês, guarda o array em `_transfLvtRows` para o export. Também preenche `<tfoot id="transf_lvt_tfoot">` com a soma de cada coluna numérica (`geral,venda,delivery,m2u,u2m,entre`) sobre o `lvt` já filtrado — linha "Total" ao final da tabela, fundo `var(--s3)` (tom levemente mais escuro que as linhas normais) aplicado **em cada `<td>`**, não no `<tr>`
- Coluna **Frete Venda** (cor `var(--blue2)`) exibida entre "Fretes Gerais" e "Frete Delivery" — junto com as outras 4 colunas de quebra, soma exatamente o valor de "Fretes Gerais"/"Total Fretes" da mesma linha (conferido manualmente: `venda+delivery+m2u+u2m+entre === geral` linha a linha e também na soma do `tfoot`)
- **Pitfall descartado:** tentativa inicial usou `position:sticky;bottom:0` no `<tr>` do tfoot para a linha ficar fixa ao rolar — causou bug visual porque `.dtbl th/td:nth-child(1/2/3)` já são `position:sticky;left:...` (colunas congeladas horizontalmente) com `z-index:3`; a combinação de sticky vertical (no `tr`) com sticky horizontal (nos primeiros `td`) fazia as 3 primeiras células do rodapé ficarem "transparentes", mostrando a última linha do `tbody` por baixo. Revertido para posição estática (linha comum, última do `tbody`+`tfoot`) — mantém as colunas congeladas horizontalmente funcionando normalmente, sem a sobreposição. Se precisar de um total fixo na tela novamente, cada `<td>` precisaria de background próprio (não resolve o sticky vertical) — não tentar de novo sem entender essa interação primeiro
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

### `_transfRenderRankingChart(rows)` — Custo de Transferência por Unidade (jul/2026)
Gráfico de barras horizontais empilhadas (`ch_transf_rank`, `indexAxis:'y'`), substitui a Matriz Unidade x Unidade (`_transfRenderMatrix`, removida) — usuário achou a matriz ainda confusa mesmo depois de várias iterações; pediu explicitamente uma visão mais simples. Uma barra por unidade origem (`d.empresa`), segmentos empilhados por categoria (`m2u`/`u2m`/`entre`, mesmas cores roxo/âmbar/vermelho do resto da aba), ordenado por total ascendente (Chart.js horizontal desenha de baixo pra cima, então `sort` ascendente deixa a maior barra no topo). Usa `_transfCategoria(d)` (ao contrário da Matriz antiga, que evitava a função de categoria) — **só soma linhas de transferência real** (`Venda`/`Delivery` ficam de fora, são outra escala de valor e poluiriam o gráfico).
**Tooltip com detalhe por destino (jul/2026):** usuário pediu pra ver, ao passar o mouse num segmento (ex.: "SOR — Entre Unidades: R$529,55"), pra quais unidades esse valor foi. `byOrigemDestino[empresa][categoria][destino]` acumulado no mesmo loop que já monta `byOrigem` (usa `_transfDestino(d)`, já existente). Callback `afterLabel` do tooltip do Chart.js (retorna array de strings = linhas extras abaixo do label principal) busca `byOrigemDestino[c.label][_catKey[c.dataset.label]]`, ordena por valor desc e lista `→ Unidade: R$X` por linha. `c.label` no tooltip de uma barra horizontal (`indexAxis:'y'`) já resolve pro nome da unidade no eixo Y — não precisou de lookup extra. Testado: valores do breakdown somam exatamente o total do segmento.
**Decisão de design:** manter o Levantamento Geral (tabela linear, serve a planilha externa) e a "Detalhe por Rota" (lista filtrável) — cortar só a Matriz, que era redundante com as outras duas e ainda carregava a confusão da diagonal auto-referenciada.
**Export Excel do detalhe por destino (jul/2026):** `_transfRankByOrigemDestino` (mesmo objeto usado no `afterLabel` do tooltip, ver acima) guardado numa variável de módulo dentro de `_transfRenderRankingChart`, pra ficar disponível fora da função de render. `transfRankExportXLSX()` percorre esse objeto (`empresa → categoria → {destino: valor}`) e gera 1 linha por combinação Unidade Origem/Categoria/Unidade Destino — é literalmente o mesmo dado do tooltip, só que a planilha inteira de uma vez em vez de segmento por segmento.

### Fix — auto-referência em `_transfCategoria` (jul/2026)
**Causa raiz encontrada:** quando uma NF-e tem **mais de um CT-e vinculado** (cadeia de redespacho/subcontratação — comum em entregas de longa distância via transportadora + parceiro local), o `processar_frete.py` cria uma linha em `detalhes` por CT-e. A etapa intermediária desse redespacho pode ter a **própria empresa emissora como destinatário do CT-e** (ex.: CT-e do trecho local tem remetente=transportadora parceira, destinatário=BRU1), mesmo a venda sendo 100% normal para um cliente externo — confirmado com dados reais: os 54 casos de "BRU1→BRU1" tinham `nat_operacao` de venda/devolução normal (`VENDA DE MERCADORIA`, `DEVOLUCAO DE VENDAS`), nunca transferência de estoque.
- **Fix:** `_transfCategoria(d)` agora retorna `null` (cai em "Venda", não em transferência) quando `destino===d.empresa` — uma empresa não transfere pra si mesma de verdade
- **Efeito:** "Fretes Gerais"/"Total Fretes" **não mudam** (mesmo valor, só migra de coluna: antes ia errado pra Matriz→Unidade/Unidade→Matriz/Entre Unidades, agora vai certo pra Frete Venda). NF-e de Transferência caiu de 342 para 263 no teste com dados reais — os ~79 casos restantes eram esse artefato de redespacho
- **Não confundir com o pitfall de "CT-e de auto-transferência" registrado antes** (a entrada em Pitfalls conhecidos sobre 54 CT-e de BRU1 com origem===destino) — aquele pitfall descrevia o sintoma; este fix resolve a causa. Atualizar a entrada de Pitfalls para refletir que já está corrigido

### Seções herdadas da aba Por Empresa (renomeadas, lógica intacta)
Movidas de `emp_*`/`_empRender*` para `transf_*`/`_transfRender*` — nenhuma mudança de comportamento, só remoção do escopo de "Por Empresa":
- `_transfRenderComercialOp` — KPIs Comercial vs Operacional + gráfico `ch_transf_tipo` + tabela "Custo Operacional por Empresa" (`transf_tbody`) — usa `isTransferencia(d)` (regex `NAT_TRANSF` OU destino no grupo), mais abrangente que `_transfCategoria` (não exige direção específica)
- `_transfRenderHumana` — "Rotas de Transferência (Matriz e Entre Unidades)" (KPIs + tabela `transf_hu_tbody` "Detalhe por Rota — Empresa Origem x Unidade Destino"). **Corrigido (jul/2026):** usava `HU_CLI` (cliente contém "HUMANA ALIMENTAR") — critério frágil e incompleto, perdia rotas reais (ex.: BRU1→CMP não aparecia). Trocado para `_transfCategoria(d)` (mesma classificação do Levantamento Geral) — agrupa por `(d.empresa, _transfDestino(d))` com chip de categoria (m2u/u2m/entre) por linha. **O custo continua na linha da Empresa Origem** (quem emitiu a nota e pagou o frete) — só a granularidade mudou (por rota, não só por empresa); não confundir com "mudar de quem é o custo", que foi uma ideia descartada (ver abaixo)
- **Filtro por categoria (`transfHuCat`, jul/2026):** mesmo padrão visual/estrutural do filtro de `transf_det_*` (chips `cat-btn` Todos/Matriz→Unidade/Unidade→Matriz/Entre Unidades, `setTransfHuCat(val)` alterna a classe `active` e chama `renderTransferencias()`). Diferença importante: aqui o filtro também recalcula os 3 KPIs da seção (`transf_hu_qtd/frete/pct/ticket`), não só a tabela — porque esses KPIs ficam colados visualmente à tabela filtrável, enquanto em `transf_det_*` os KPIs equivalentes (`transf_k_*`) são cards separados no topo da aba e permanecem fixos independente do filtro local
- **Decisão explícita do usuário (jul/2026):** o custo de transferência DEVE ficar sempre na linha de quem emitiu a nota (o pagador), nunca no destinatário — "na lógica das transferências, o emitente é o responsável pelo custo". Uma tentativa de mover o custo de `m2u` para a linha da unidade destino foi implementada e revertida no mesmo dia depois que o usuário validou com o gestor. Não reabrir essa mudança sem confirmação explícita.
- **Filtro Origem/Destino (jul/2026):** dois `<select>` (`transf_hu_sel_origem`/`transf_hu_sel_destino`) ao lado dos chips de categoria, populados dinamicamente por `_transfPopulateOrigemDestino(rows)` (lista de empresas/destinos distintos nas linhas de transferência atuais, repovoada a cada render pra crescer sozinha conforme novos dados). Estado em `transfHuOrigem`/`transfHuDestino`, filtro aplicado dentro do mesmo `.filter()` de `_transfRenderHumana` junto com a categoria — permite isolar uma rota específica (ex.: BRU1→CMP) e ver só ela nos KPIs da seção e na tabela.

### "Recebido em Transferência (Matriz→Unidade)" no Levantamento Geral (jul/2026)
Usuário notou que a coluna "Frete Transf. Matriz→Unidade" fica sempre R$0,00 nas linhas das unidades não-Matriz (correto — só a Matriz emite m2u), mas isso passava impressão de "sem dado", prejudicando a credibilidade do relatório. **Fix:** nova coluna `recebidoM2U` em `_transfBuildLevantamento` — quando `cat==='m2u'`, além de somar no bucket da Matriz (como sempre), também soma num segundo bucket, o da **unidade destino** (`_transfDestino(d)`), num campo separado que **não entra no somatório de `geral`/`Fretes Gerais`** dessa linha (evita contar o mesmo frete 2x). Coluna nova "Pago por" ao lado mostra "Matriz" quando há valor. **Validado:** soma total de `m2u` (linhas da Matriz) bate exatamente com a soma total de `recebidoM2U` (linhas das outras unidades) — é o mesmo dinheiro visto de 2 ângulos, não duplicação nem dedução. Adicionado também no `transfExportXLSX`.
**Posicionamento do texto explicativo:** o bloco "O que significa cada coluna" (que já existia, cobrindo todas as colunas do Levantamento Geral) foi **movido** de dentro do card "Como Interpretar Esta Aba" (no topo da aba, longe da tabela) pra dentro do próprio card do Levantamento Geral, logo acima da `<table>` — pedido explícito do usuário: "hoje está fresco na memória do usuário, com o passar do tempo não vai estar... a explicação sempre tem que ficar perto do motivo". Regra geral a seguir: explicação de coluna/tabela fica sempre colada na tabela que ela explica, não solta em outro lugar da página.
- `_transfRenderSemCte` — tabela `transf_sem_cte_tbody`, NF-e de transferência (`DATA.transf_sem_cte`, populado por `processar_frete.py`) sem CT-e vinculado. **Coluna "Transportadora (Volumetria)" (jul/2026):** usuário perguntou se essas NF-e "sem CT-e vinculado" não teriam na verdade sido entregues por um entregador/transportadora — cruzando com `volumetria_nfe` (que cobre praticamente toda NF-e de saída, não só as de entregador autônomo) dá pra responder. `_carregar_volumetria_lookup()` (processar_frete.py) monta `{chave_acesso: {transp_nome, canal}}` de **todas** as linhas de `volumetria_nfe` (96.120 chaves, 46.639 com transportadora nomeada — testado com dados reais). Dentro de `cruzar()`, cada item de `transf_sem_cte_list` ganha `transp_volumetria`/`canal_volumetria` via esse lookup pela `chave` da NF-e. **Resultado real:** de 2.768 NF-e de transferência sem CT-e no filtro Ano=2026, 134 têm transportadora identificada na Volumetria — confirma que parte do gap é limitação de captura do CT-e, não ausência de transporte real. Frontend: chip verde (`var(--green2)`) com nome da transportadora + canal abaixo quando presente, "-" quando ausente (provável retirada no balcão)
- **Botão "Ver NF-e" / modal `transf-espelho-modal` (jul/2026):** cada linha de `transf_sem_cte_tbody` ganhou um botão que abre um espelho da NF-e (itens, transportadora do bloco `<transp>`, peso, informações complementares) — pedido do usuário pra investigar manualmente notas como a 27206 (CGR→BRU1) sem precisar sair do dashboard. Dados vêm de `QUIVE/buscar_nfe_espelho.py` (busca via API Arquivei pela chave da NF-e, ver `QUIVE/CLAUDE.md`), publicados como campo `transf_espelho` **chunked** (mesmo padrão de `detalhes`/`{emp}_det_NNN` — ver `Pitfall — payload > 1MB` abaixo). Modal reaproveita as classes CSS `.nv-esp-*` do "Espelho NF-e" já existente (`nfe-espelho-modal`), mas é um modal **separado** (`transf-espelho-modal`) porque os campos são diferentes (tem tabela de itens, que o espelho antigo não tem; não tem os campos de CT-e/rateio que não fazem sentido pra nota sem CT-e). `_transfSemCteRows` guarda o array na ordem renderizada pra o botão indexar por posição (`showEspelhoTransfSemCte(idx)`), mesmo padrão de `_opRows`/`_ncData`. Busca o espelho em `DATA.transf_espelho` por `chave` (não embutido na própria linha de `transf_sem_cte`, ver pitfall).
- **Pitfall — payload de `transf_espelho` > 1MB, corrigido no mesmo dia:** primeira tentativa embutiu o espelho completo (itens + infCpl) dentro de cada item de `transf_sem_cte_list` — BRU1 tem 994 NF-e sem CTe com espelho (994 itens × itens+texto = 1,08MB só nesse campo), Firestore rejeitou o upload (`payload is longer than 1048487 bytes`). **Fix:** campo separado `transf_espelho` (lista de `{chave, empresa, transp_cnpj, transp_nome, peso_bruto, qtd_volumes, info_complementar, itens}`), chunked em `upload_to_firestore()` com o **mesmo `CHUNK_SIZE=800`** e mesmo mecanismo de `detalhes` (`{emp}_esp_NNN`, contagem em `main_doc["espelho_chunks"]`). Frontend (`_loadData`) busca os chunks de espelho do mesmo jeito que já buscava os de detalhes, merge em `_mergeData` via `transf_espelho: datas.flatMap(...)`. **Se adicionar novos campos "grandes" (texto livre, listas) a qualquer parte do payload no futuro, sempre medir o tamanho por empresa antes de publicar** (`json.dumps(...).encode('utf-8')` / 1024) — BRU1 é sempre a empresa que estoura primeiro, por ter o maior volume.
- `_periodoLabelHTML(rows)` — helper extraído (antes duplicado dentro de `_empRenderPeriodo`) para montar o texto "Exibindo: ..." dos banners de período; usado tanto por `_empRenderPeriodo` (Por Empresa) quanto por `_transfRenderPeriodo` (Transferências)

### `renderTransferencias()`
Orquestra tudo: filtra `rows`, calcula `freByEmp` via `_empAggregate` (reaproveitado de Por Empresa), constrói `lvt` via `_transfBuildLevantamento`, chama os renders acima na ordem KPIs → evolução → levantamento → detalhes por NF-e (`_transfBuildDetalhe`+`_transfRenderDetalhe`) → comercial/op → grupo → sem CTe → período. Chamada pelo tab-switch (2 lugares: click handler e `renderAll()`) quando `tab==='transferencias'`.

### Não replicado no `HTML_TEMPLATE`
Mesma ressalva do módulo Marketplace: `HTML_TEMPLATE` em `processar_frete.py` não tem a aba Transferências — só afeta o `dashboard_frete.html` standalone local, não o app publicado no GitHub Pages.

### Volumetria por Entregador — validação do valor cobrado (jul/2026)

`nfse_entregadores` só mostra o que o entregador **cobrou** (1 NFS-e por mês, valor cheio) — não dava para saber quantas entregas isso cobria, nem se o valor era razoável. O relatório de Volumetria do ERP (`volumetria_nfe`) resolve isso: 1 linha por NF-e de saída, com o CNPJ de quem entregou. Quando esse CNPJ é de um entregador cadastrado, dá pra medir o volume real (NF-e, peso) e cruzar com o que ele faturou.

**`_carregar_volumetria_entregadores()` (processar_frete.py)** — agregado por empresa+entregador+ano+mês:
```python
JOIN entregadores e ON e.cnpj_entregador = v.transp_cnpj AND e.empresa = v.empresa
```
Campos: `empresa, entregador_nome, ano, mes, qtd_nfe, peso_kg, valor_nf, tem_nfse`. `tem_nfse` (bool) verifica se existe NFS-e `status='Authorized'` para o mesmo `(cnpj_entregador, empresa, "YYYY-MM")` em `nfse_entregadores` — é a base do painel de alerta (ver abaixo). Tabela pequena (poucas dezenas de linhas), sem risco de tamanho.

**`_carregar_volumetria_detalhe()` (processar_frete.py)** — 1 linha por NF-e entregue por um entregador, com `LEFT JOIN vw_nf_saida ON n.chave = v.chave_acesso` trazendo cliente/cidade/UF/natureza do faturamento (mesma chave de acesso — 98,6% de correspondência testado com dados reais de jun-jul/2026). **Janela de 6 meses** (`WHERE ... >= data de 182 dias atrás`) — diferente de `detalhes` (que é chunked em docs separados), este campo vai inteiro em cada doc de empresa.

**Medido em produção (jul/2026, após backfill retroativo jan/2025-jul/2026):** com janela de 12 meses, UBE chegou a **534 KB só nesse campo** (82% do doc principal de 653 KB) e SOR a 477 KB — reduzido pra 6 meses ficou em 476 KB (UBE) e 423 KB (SOR), pouca melhora real porque a maior parte do volume de entregadores está concentrado nos meses recentes (o histórico de 2025 tinha um buraco ago-dez, então "12 meses" já não trazia muito mais dado que "6 meses"). Docs finais publicados: SOR 670 KB (o maior), UBE 595 KB — dentro do limite, mas **se o número de entregadores cadastrados crescer bastante, ou o buraco ago-dez/2025 for preenchido, medir de novo antes de aumentar a janela** — a solução definitiva se isso voltar a ficar apertado é migrar este campo pro mesmo padrão de chunking de `detalhes` (`{emp}_det_NNN`), não aumentar a janela.

Ambos os campos são filtrados por empresa em `split_by_empresa` (mesmo padrão de `delivery`) e mesclados via `flatMap` em `_mergeData()`.

**Frontend (index.html, dentro da aba Delivery):**
- **Ranking (`dlv_rank_tbody`)** — 3 colunas novas: NF-e Entregues, R$/Entrega, R$/kg. `volByEntreg` cruza `DATA.volumetria_entregadores` pelos mesmos filtros da tabela (empresa/ano/mês) e soma por `entregador_nome`; `R$/Entrega = e.total/vol.qtd`, `R$/kg = e.total/vol.peso` — guard `vol.qtd?...:'-'` porque alguns entregadores (ex. EDCARLOS MOREIRA DE SOUZA) sempre têm `peso_kg=0` no relatório (canal não captura peso)
- **Card `dlv_gap_card`** ("Controle de Nota de Serviço por Entregador") — matriz entregador (linha, sticky à esquerda) × mês (coluna), mesmo padrão visual do heatmap `renderYoY()` (`stickyBase`/`thBase`, `var(--sticky-bg)`), mas com 3 estados discretos em vez de gradiente: ✓ verde (`var(--green2)`) = tem NFS-e autorizada naquele mês; ✕ vermelho (`var(--red2)`) = entregou mas não tem NFS-e; "—" cinza = sem registro naquele mês (não é gap, é normal). Tooltip (`title` nativo) mostra qtd de NF-e e valor de mercadoria ao passar o mouse. Substituiu uma primeira versão em lista (só linhas sem NFS-e) — usuário achou a lista pouco clara pra entender o padrão mês a mês; a matriz mostra o histórico completo de cada entregador de uma vez
  - **Escopo restrito a "a nota do mês foi emitida?" (ago/2026)** — a célula juntava valor de mercadoria (linhas reais da Volumetria) com valor de NFS-e (linhas sintéticas `sem_volumetria`) num número só; em fev/2026 o Vladimir/Henrique exibia R$42.931,01, que era R$42.431,01 de mercadoria + R$500 de nota de serviço. Hoje o tooltip do ✓ mostra **só o valor da NFS-e da competência**, lido de `DATA.delivery` via `nfseByKey` (chave `entregador_nome|YYYY-MM`); o ✕ segue citando as entregas sem nota. **Não voltar a misturar as duas métricas no mesmo painel/tooltip** — "quanto cobrou" e "quanto entregou" são perguntas diferentes, e juntá-las foi a origem da confusão relatada pelo usuário duas vezes
- Linhas/colunas montadas dinamicamente a partir de `DATA.volumetria_entregadores` (`entregadores`/`mesesCols` via `[...new Set(...)].sort()`) — cresce sozinho conforme mais meses forem importados, sem precisar tocar no código
- **Só respeita `state.empresas`**, ignora os filtros locais de período da aba (é um painel de controle, não deve esconder um mês por causa do filtro de mês ativo); `display:none` quando não há nenhum dado
- **Card `dlv_vol_card`** ("Entregas Cruzadas com a Volumetria", ago/2026) — painel **separado** do de controle, criado a pedido do usuário justamente pra tirar o volume de dentro da matriz de emissão. Gráfico `ch_dlv_vol` (barras empilhadas por entregador) + linha de resumo (`dlv_vol_qtd`/`dlv_vol_valor`/`dlv_vol_peso`) + tabela `dlv_vol_tbody`. Ignora as linhas sintéticas (`sem_volumetria`), que por definição não têm volume. Mesmo escopo da matriz: histórico completo, só respeita `state.empresas`
  - **Respeita os filtros globais de ano/mês (ago/2026)** — diferente da matriz de controle acima dele. Antes só filtrava por empresa, e o total exibido era sempre o histórico inteiro mesmo com um mês selecionado no topo (usuário viu 3.859 NF-e da Simaura com o filtro de 2026 ativo, quando o ano tinha 1.753). A lista do seletor de entregador também acompanha o período. A matriz de controle continua ignorando o período de propósito — é conferência de emissão de nota, não leitura de volume
  - **Filtro `dlv_vol_sel_ent`** — isola um entregador em gráfico+resumo+tabela ao mesmo tempo. Vale **só pra esse card**: a matriz de controle continua lendo `volAll` (todos) e o painel lê `volVol` (filtrado). A lista de opções é repovoada a cada render conforme o filtro global de empresa, preservando a seleção quando ainda existe no recorte (`_assinatura` no elemento evita recriar os `<option>` à toa)
  - **Paleta `DLV_PAL` + `_dlvSlotMap()`** — ver seção "Cores de série (dataviz)" abaixo. Regra curta: **cor segue o entregador, nunca o rank do filtro**
  - **Eixo de meses contínuo** — `mesesPresentes` (meses com dado) alimenta os totais; `mesesVol` (range do 1º ao último mês, preenchendo os vazios) alimenta labels e datasets. Sem isso a lacuna da Volumetria some e as barras leem como série contínua, sugerindo um histórico que não existe
  - **Tooltip por índice** — `_chartUpdate` reaproveita as `options` do 1º render, então callback que precisa de dado por índice lê de `window._dlvVolVals` (global reescrito a cada render), nunca de variável em closure — senão congela nos valores do primeiro filtro
- **Card "NF-e Entregues — Detalhe" (`dlvdet_tbody`)** — de `DATA.volumetria_detalhe`, com busca (`dlvdet_search`) + filtro de empresa (`dlvdet_sel_emp`) + paginação (`dlvdet_pager`, `PAGE` global) + export (`dlvDetExportXLSX`) — mesmo padrão da tabela "Detalhamento por Entregador" já existente (NFS-e), mas em granularidade de NF-e entregue, não de nota de serviço emitida. **Janela fixa de 6 meses** (limite do backend) — meses mais antigos aparecem no gráfico e na matriz, mas não aqui; é esperado, não é bug

### Cores de série (dataviz) — `DLV_PAL` / `_dlvSlotMap()` (ago/2026)
Usuário reportou que não conseguia diferenciar entregadores no empilhado. Corrigido com a skill `dataviz` (não no olho):
- **`DLV_PAL`** (8 hexes, topo do `index.html`) — ordem validada por `scripts/validate_palette.js` para daltonismo em pares **adjacentes**, que é o caso de barras empilhadas, e com contraste ≥3:1 sobre **as duas** superfícies do app (`#FFFFFF` no tema ocean, `#131315` no escuro). Por isso uma paleta só atende os 2 temas — o que importa porque `toggleTheme()` **não re-renderiza** os gráficos, então paleta por tema ficaria defasada até o próximo filtro
- **`_dlvSlotMap()`** — slot de cor por entregador calculado sobre a base **completa**, nunca sobre o recorte filtrado. Conflitam (não podem dividir cor) quem compartilha unidade ou está no top 8 do grupo; assim a visão sem filtro e as visões de 1 empresa nunca repetem cor. Numa seleção de várias unidades duas faixas ainda podem repetir hue — são 15 entregadores para 8 cores, e **gerar uma 9ª cor deixaria as faixas indistinguíveis para daltônicos**; por isso a tabela do card é a fonte de identidade, nunca a cor sozinha
- **Anti-padrão que isso corrige:** atribuir cor por rank do filtro atual ("recolor-on-filter") — antes 4 entregadores trocavam de cor ao filtrar por empresa
- **Excedente vira "Outros (N)"** em cinza neutro (`DLV_COR_OUTROS`), e no swatch da tabela esses entregadores aparecem **cinza também**, espelhando a faixa do gráfico
- **Ao criar qualquer gráfico novo neste projeto:** carregar a skill `dataviz` e rodar o validador contra as superfícies reais acima; máx. 8 cores categóricas

### Período do módulo Delivery = COMPETÊNCIA da NFS-e, não data de emissão (ago/2026)

Todo filtro de ano/mês da aba Delivery usa `_dlvPer(d)` = `d.competencia || d.data_emissao`. **Não voltar a filtrar por `data_emissao` direto** — o entregador emite a nota depois de fechar o mês, e pela emissão o custo caía num mês diferente do das entregas, que são datadas pela NF-e de mercadoria.

**O sintoma que revelou isso:** com o filtro em ago/2026 o ranking mostrava 1 NFS-e do Simaura (nº 17, R$11.000, emitida 03/08 com competência 31/07) e a tabela "NF-e Entregues — Detalhe" ficava vazia — porque as entregas dela são de julho. Havia ainda uma inconsistência interna: a matriz "Controle de Nota de Serviço" **já** usava competência, enquanto KPIs/ranking/gráfico usavam emissão.

**Pontos convertidos** (todos em `index.html`): `rows` de `renderDelivery`, `dlvGlobalRows` (card Delivery vs. Frete), `nfseGlobal` (custo médio por entrega do card Raio), `_dlvPrevRows` (tendência), gráfico `ch_dlv_mensal`, `_dlvDt` do "Valor Médio/Dia", `nfseByKey` da matriz e `dlvExportXLSX`. Efeito medido: jul/2026 foi de 12 para 14 NFS-e (entram Simaura R$11.000 e Vladimir/Henrique R$1.365, ambas emitidas em 03/08), e o custo médio por entrega passa a bater com o volume do mês (R$58,78 / 885 entregas).

**Fallback e marcação:** nota sem competência entra pela emissão e é marcada com `*` laranja — na coluna Competência (`* nao informada`), ao lado do nome no ranking (com a contagem no `title`) e numa legenda (`dlv_comp_legenda`) que só aparece quando há caso no recorte. O export ganhou a coluna "Mês de Referência" com ` *` no valor. Hoje **nenhuma NFS-e da base está sem competência** — a marcação é preventiva, para o número nunca mudar de mês em silêncio.

### Raio de Entrega — dentro x fora da cidade (ago/2026)

Card `dlv_loc_card` na aba Delivery. Nasceu de uma conferência do usuário: o R$/entrega em torno de R$55 não dizia nada sozinho, porque entrega urbana e entrega para outro município têm custo estruturalmente diferente. Separa as duas coisas e usa o % fora como explicação para um custo médio mais alto.

**Fonte da cidade — e a limitação que precisa continuar visível na tela:** a classificação compara a **cidade do destinatário** da NF-e com a **cidade-sede da unidade emitente**. Não é o local de entrega real. Quando o cliente é cadastrado numa cidade e pede entrega em outra, a NF-e traz um grupo `<entrega>` com endereço próprio — e **esse campo não existe em nenhuma fonte que o projeto tem hoje** (ver "Endereço de entrega — fontes descartadas" abaixo). Caso concreto que originou a investigação: NF-e 30816 (CGR, cliente DANIEL ERASMO GRANDA FILHO) sai como Maracaju/MS porque é a cidade do cadastro; a entrega foi em Campo Grande, conforme o campo de endereço de entrega da nota. Por isso o card tem um aviso permanente (`dlv_loc_aviso`) dizendo que a lista de "fora da cidade" é **pauta de conferência, não número fechado** — não remover esse aviso enquanto a fonte for o endereço do destinatário.

**Cidade-sede é derivada, não cadastrada:** `_sedes_por_empresa()` pega o `emit_cod_cidade`/`emit_cidade` mais frequente por empresa em `volumetria_nfe` — unidade nova ou mudança de endereço se ajusta sozinha, sem hardcode. Publicado em `resumo.sedes_unidades` (`{emp: {cidade, uf}}`), dict global minúsculo. **Não colocar a cidade-sede em cada linha de entrega** — foi a primeira versão e custava ~39 KB só no doc da CGR (mesma string repetida milhares de vezes).

**Comparação por código IBGE, com fallback de nome:** `_classificar_local()` compara `dest_cod_cidade` × `emit_cod_cidade` (exato). Cai no nome normalizado (`_norm_cidade`: maiúsculas, sem acento) quando a linha não tem código — caso das NF-e importadas antes das colunas de cidade existirem, em que a cidade vem de `vw_nf_saida.part_cidade`. Medido com dados reais: 21.826 de 21.828 entregas classificadas (2 indefinidas). `_cidade_exib()` padroniza a grafia para exibição, senão a mesma cidade aparece 2x no ranking ("VOTORANTIM" da Volumetria e "Votorantim" do faturamento).

**Onde cada número vive:**
| Campo | Onde | Granularidade |
|---|---|---|
| `qtd_dentro`/`qtd_fora`/`qtd_local_indef` | linhas de `volumetria_entregadores` | empresa/entregador/ano/mês, **histórico completo** — alimenta KPIs, gráfico e tabela por entregador |
| `local` (`'dentro'`/`'fora'`/`''`) | linhas de `volumetria_detalhe` | por NF-e, **janela de 6 meses** — alimenta o ranking de cidades (único lugar com nome de município), a coluna "Raio" e o filtro `dlvdet_sel_loc` da tabela de detalhe |

**Pitfall — custo médio por entrega distorce ao filtrar 1 unidade:** o numerador (NFS-e) e o denominador (entregas da Volumetria) vêm de fontes diferentes, e entregador que atende mais de uma unidade às vezes fatura numa e entrega pela outra (Vladimir/Henrique: NFS-e em BRU1, entregas em BRU2). Filtrando BRU1/jan-2026 dá R$1.312/entrega. **Não "corrigir" isso escondendo o KPI** — o sub-texto mostra a conta (`R$ X / N entregas`), que expõe a distorção na hora; é o mesmo fenômeno que já afeta a coluna R$/Entrega do ranking.

**Aparar meses vazios só nas pontas:** mês sem nenhuma entrega classificada aparece em `agg` quando só há NFS-e sintética. No meio da série a coluna vazia é informação (lacuna real da Volumetria); nas pontas é só uma barra vazia no começo/fim do gráfico.

### Endereço de entrega — fontes descartadas (ago/2026, não repetir a investigação)

Procurando o local real de entrega (grupo `<entrega>` da NF-e), foram testadas e descartadas:
1. **`vw_nf_saida.part_cidade`** — endereço fiscal do destinatário, é o que gerava o erro relatado.
2. **Relatório de Volumetria do ERP** — `DESTINATARIO_CIDADE`/`DESTINATARIO_CEP` também são do destinatário. Conferido no caso 30816: CEP 79156-026 é de Maracaju (BrasilAPI), concorda com o cadastro, não com a entrega. O ERP não exporta o endereço de entrega nesse relatório.
3. **API Qive/Arquivei** — `POST /v2/dfe/nfe` funciona, mas **só tem 0,3% a 6% das nossas NF-e de saída** (medido: CGR jul/2026 → 7 de 844; BRU1 jul/2026 → 83 de 4.744; UBE mai/2026 → 2 de 600). A Qive captura o que o grupo **recebe**, não o que emite — por isso `buscar_nfe_espelho.py` (NF-e de transferência, em que outra unidade do grupo é destinatária) tem 99,9% de cobertura e o mesmo endpoint é inútil para venda a cliente externo. `GET /v1/nfe/emitted` existe mas tem 67 documentos no total. Um `buscar_nfe_entrega.py` chegou a ser escrito e foi removido por isso.

**Se for necessário o endereço real:** a fonte é o ERP (que gerou a nota) ou os XMLs de saída da empresa — não a API da Qive.

**Pitfall — `/v2/dfe/nfe` responde 404 intermitente:** há nó do balanceador da Qive devolvendo 404 do nginx em ~metade das chamadas (medido ago/2026: a mesma requisição repetida alternava 404/200). `buscar_nfe_espelho.py` trata isso com `RETRY_ATTEMPTS=3` e `raise_for_status`, o que dá ~12% de chance de falhar um grupo inteiro. Se ele começar a falhar na rotina diária, é essa a causa — a correção é tratar 404 como transitório e aumentar as tentativas, não trocar de endpoint.

**Pitfall — `tem_nfse` é por competência, não por total:** um entregador pode ter uma única NFS-e mensal cobrindo várias semanas; se a competência dela bater com o mês da entrega, `tem_nfse=true` mesmo que o valor pareça baixo pra o volume. O alerta serve pra achar meses **sem nenhuma** nota, não pra validar se o valor da nota é proporcional ao volume — isso é o que as colunas R$/Entrega e R$/kg do ranking fazem.

**Fusão Vladimir/Henrique Dezembro (jul/2026):** usuário confirmou que VLADIMIR ROBERTO DEZEMBRO (CNPJ 33.585.276/0001-38) e HENRIQUE PACETTI DEZEMBRO (CNPJ 30.184.082/0001-32) são a mesma operação de entrega faturando por 2 CNPJs diferentes (ambos atendem BRU1+BRU2) — na prática, quando um não emite NFS-e no mês é porque o outro emitiu. Olhar os 2 separadamente gerava falso alerta (✕) num mês em que a operação como um todo tinha faturado, só pela outra CNPJ.
**Fix — no backend, não no frontend (pedido explícito do usuário: "no sistema todo precisa ser feita essa fusão"):** `ENTREGADOR_ALIAS_NOME` (dict `cnpj_entregador → nome combinado`, topo de `processar_frete.py`) aplicado em `_carregar_nfse_entregadores()`, `_carregar_volumetria_entregadores()` (nas 2 fontes: linhas normais + linhas sintéticas de NFS-e-sem-volumetria) e `_carregar_volumetria_detalhe()`. Como o frontend já agrupa tudo por `entregador_nome` (ranking `porEntreg`, matriz `byKey`, detalhe/busca/export), bastou trocar o nome na origem — nenhuma lógica de agregação no `index.html` precisou mudar (o alias que tinha sido colocado só na matriz foi removido, fonte única de verdade agora é o backend). Efeito: ranking (`dlv_rank_tbody`) mostra 1 linha combinada (28 entregas, R$45.420,00, BRU1+BRU2); matriz mostra 1 linha combinada, só 2 meses de ~23 continuam ✕ mesmo somando os dois (gap real). Testado localmente, sem erros de console, publicado.
**Se aparecer outro caso parecido no futuro:** só adicionar as 2 (ou mais) entradas no `ENTREGADOR_ALIAS_NOME` mapeando pro mesmo nome combinado — não precisa tocar em nenhum outro lugar do código.

**ALEXANDRE DE OLIVEIRA CAMPOS (SOR) — trocou de CNPJ pra faturar (ago/2026):** 3º caso do mesmo padrão. **38.157.789/0001-61** é o CNPJ antigo e continua sendo o que a Volumetria registra como quem **entrega** (~200 NF-e/mês desde jan/2025); **65.641.704/0001-99** é o novo e emite as **NFS-e** desde mar/2026 (zero linhas na Volumetria). Cadastrado em `entregadores.xlsx` (SOR) + os 2 em `ENTREGADOR_ALIAS_NOME`. NFS-e da SOR: 2 notas (R$11.650) → **14 notas (R$96.040, fev–jul/2026)**. Como o CNPJ novo não tem volumetria, quem faz o ✓ aparecer é a **linha sintética** de `_carregar_volumetria_entregadores()` — o frontend funde as duas linhas do mês pelo `entregador_nome` (`temNfse = temNfse || v.tem_nfse`). **Lacuna em aberto:** 2025 inteiro (~2.200 NF-e entregues) segue sem nenhuma NFS-e — confirmado que não existe nota sob nenhum dos 2 CNPJs nem sob o CPF 182.809.188-09; perguntar ao usuário como o serviço era pago antes de mar/2026.

**MURALHA ENTREGA RAPIDA / MRP ENTREGAS (CGR) — CNPJ de entrega ≠ CNPJ de faturamento (jul/2026):** MURALHA ENTREGA RAPIDA LTDA (CNPJ 48.361.800/0001-64, "tipo Uber de entregas" em Campo Grande, é quem aparece na Volumetria como transportadora) inicialmente parecia não ter NFS-e nenhuma — mas o usuário descobriu que quem realmente fatura é **MRP ENTREGAS LTDA (CNPJ 60.599.335/0001-08)**, mesmo serviço, razão social de faturamento diferente. Confirmado: 25 NFS-e da MRP (R$1.162,60, jan-jul/2026). Cadastrada como 2ª entrada em `entregadores.xlsx` pra CGR, fundida com a Muralha via `ENTREGADOR_ALIAS_NOME` (mesmo mecanismo do Vladimir/Henrique, ver acima) — nome combinado "MURALHA ENTREGA RAPIDA / MRP ENTREGAS". **Padrão a repetir:** sempre que um entregador identificado pela Volumetria não tiver NFS-e nenhuma, perguntar ao usuário se ele sabe o CNPJ real de faturamento antes de concluir "não fatura" — pode ser só CNPJ errado no cruzamento, não ausência de nota.

**RIBEIRANIA COBRANCAS S/S LTDA (CNPJ 02.470.837/0001-20, RBP) — erro de seleção no ERP, corrigido na fonte (jul/2026):** aparecia na Volumetria como "transportadora" de 187 notas (R$197k) — nome de empresa de cobrança, não faz sentido como transportadora. Usuário identificou: erro de seleção no ERP (endereço de entrega na mesma cidade da unidade RBP) — a entrega real foi da **Valeria Aparecida Beltrami** (CNPJ 40.886.468/0001-40, já cadastrada). **Fix — correção de dado, não de código:** `UPDATE volumetria_nfe SET transp_cnpj/transp_nome = <dados da Valeria> WHERE transp_cnpj='02470837000120'` direto no `cte.db`. Durável porque `importar_volumetria.py` usa `INSERT OR IGNORE` por `chave_acesso` — reimportar o CSV original do ERP no futuro não desfaz a correção. **Padrão a vigiar:** nome de transportadora que não parece nome de transportadora (empresa de cobrança, papelaria etc.) pode ser erro de seleção no ERP — vale perguntar ao usuário antes de tratar como CT-e-gap ou escalar pra Qive.

**TRANSMAZILI TRANSPORTE DE CARGAS E LOGISTICA (CNPJ 14.574.799/0001-34) — operação triangulada, CT-e nunca vai existir (jul/2026):** era o "big fish" encontrado na varredura pós-fix do `buscar_cte_por_nfe.py` (64 de 65 notas ainda sem CT-e, R$5,35M, mas com **2.216 CT-e** dela em outras notas — não era limitação de API). Usuário confirmou: é **operação triangulada com fornecedor** — mercadoria sai direto do fornecedor pro cliente final, nota de venda é da Humana, mas o frete é conta do fornecedor. CT-e nunca vai ser emitido pra Humana nessas notas — não é bug nem lacuna, é o fluxo fiscal correto. Caso encerrado, sem necessidade de escalar pra Qive.

**Limitação conhecida — Henrique Pacetti Dezembro, Eliel de Souza (e futuros casos parecidos):** entregador cadastrado e com NFS-e emitida, mas **zero linhas em `volumetria_nfe`** (o relatório de Volumetria do ERP não o identifica como transportadora em nenhum mês, mesmo em períodos cobertos pelo export). Como a matriz de controle dependia 100% do cruzamento com `volumetria_entregadores`, ele ficava invisível ali mesmo tendo faturado normalmente. **Fix (jul/2026):** `_carregar_volumetria_entregadores()` agora complementa com uma passada extra sobre `nfse_entregadores` — para todo (entregador, empresa, mês) com NFS-e autorizada mas sem nenhuma linha de volumetria correspondente, adiciona uma entrada sintética com `qtd_nfe=0, peso_kg=0, tem_nfse=true, sem_volumetria=true`. Aparece na matriz com ✓ verde, sem volume conhecido — não dá pra mostrar ✕ (entregou sem nota) pra esses casos, porque não há evidência independente de entrega sem o cruzamento de volume real.
**Fix do valor mostrado no tooltip (jul/2026):** o `valor_nf` dessas entradas sintéticas ficava sempre `0.0` — usuário notou que passar o mouse num ✓ verde do Eliel de Souza não mostrava valor nenhum (`R$0,00`). Causa: o valor real da NFS-e nunca era calculado pra essas linhas. Corrigido: `nfse_valor_mes` (dict `(cnpj_entregador, empresa, "YYYY-MM") → soma de valor_servico`) construído a partir do mesmo `nfse_rows` já carregado, e usado no `valor_nf` da entrada sintética em vez de `0.0`. Tooltip agora mostra o valor real faturado com a ressalva "(sem cruzamento de volume na Volumetria)" em vez de sugerir que não há dado.
**Unidade(s) atendida(s) no tooltip (jul/2026):** usuário pediu pra saber, ao passar o mouse na matriz, pra qual unidade o serviço foi prestado — importante pros entregadores fundidos via `ENTREGADOR_ALIAS_NOME` (Vladimir/Henrique, Muralha/MRP) que atendem mais de uma empresa. O `Set` de empresas por célula (`byKey[k].empresas`, já existia pra uso interno) passou a entrar no `title` do tooltip: "Unidade(s): BRU1, BRU2 — ...". Testado: célula com faturamento das 2 unidades no mesmo mês mostra "BRU1, BRU2" corretamente.

## Cobertura de CT-e — busca pela chave da NF-e (jul/2026)

**Contexto:** usuário notou (via casos concretos como a transportadora Logfar Logistica, CNPJ 05.530.576/0019-03, ~R$3,4M em fretes segundo a Volumetria e zero CT-e capturado) que a "Cobertura de Faturamento" baixa (~46% antes deste fix) não era só retirada no depósito — parte real era limitação técnica de captura de CT-e.

**Causa raiz:** `QUIVE/buscar_cte.py` só busca CT-e via `GET /v1/cte/taker?cnpj[]=<nossas 8 empresas>` — funciona quando o CT-e tem um **CNPJ de tomador explícito** no XML. Muitos CT-e usam o **indicador simples** (`<toma3><toma>0</toma></toma3>`, valores 0-3 = tomador é remetente/expedidor/recebedor/destinatário, **sem CNPJ próprio declarado**) — a busca por CNPJ tomador da Arquivei não indexa esses, mesmo quando o indicador aponta pra uma das nossas empresas (ex.: toma=0 com `<rem><CNPJ>` = BRU1).

**Fix:** novo script `QUIVE/buscar_cte_por_nfe.py` usa um endpoint diferente e mais recente, `POST /v1/dfe/cte` (`Filters.Nfes: [chave_nfe,...]`), que busca o CT-e **direto pela chave de acesso da NF-e transportada** — contorna o problema do indicador de tomador por completo. Detalhes técnicos completos (schema do endpoint, integração com `criar_view.py`, resultado da 1ª execução) em `QUIVE/CLAUDE.md`.

**Impacto real (1ª execução, jul/2026, base completa):** NF-e vinculadas a CT-e subiu de 66.765 pra **106.952** (quase dobrou); frete total subiu de R$4,25M pra **R$6,80M**; % Frete/Receita de 1,6% pra **2,5%**. Não é ruído — é frete que sempre existiu mas ficava fora de qualquer relatório porque o CT-e nunca tinha sido baixado. **Se o % Frete/Receita parecer ter "subido" de repente numa auditoria futura, essa é a explicação — não é um bug novo, é dado que passou a existir.**

**Integrado no `atualizar.py`** como Etapa 2b — roda automaticamente em toda atualização, não precisa ser lembrado manualmente.

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

- **RESOLVIDO (jul/2026) — CT-e de "auto-transferência" (origem === destino):** 54 CT-e de BRU1 com `_transfDestino(d)==='BRU1'` no período testado. Causa raiz identificada: NF-e com múltiplos CT-e vinculados (redespacho/subcontratação) — o CT-e da etapa intermediária pode ter a própria empresa como destinatário, mesmo a venda sendo normal para cliente externo. `_transfCategoria(d)` agora trata `destino===d.empresa` como não-transferência (cai em "Venda"). Ver seção "Fix — auto-referência em `_transfCategoria`" no módulo Transferências para detalhes.
- **Limite de 1MB por documento Firestore — BRU1 já opera perto do teto** — o doc principal de cada empresa (tudo exceto `detalhes`, que são chunkados) precisa ficar abaixo de ~1024 KB. Medição mais recente (ago/2026, depois do card Raio de Entrega): BRU1 em **993 KB, ~31 KB de margem** (era 987 KB antes, 978 KB em jul/2026) — a margem encolhe a cada release, então **medir antes de adicionar qualquer campo novo já virou obrigatório, não recomendação**; o próximo campo global de porte exige mover algo para chunk primeiro — a menor entre as 8 empresas por ser a maior filial. O 2º maior é SOR (672 KB). Campos que NÃO são filtrados por empresa (embutidos inteiros em todo doc) são os primeiros suspeitos ao investigar crescimento: `cnpj_nomes` (filtrado desde jul/2026 aos CNPJs de fato usados via `part_cnpj` em `detalhes` — única leitura no frontend é `_cliClientCell` na aba Por Cliente), `nfe_fat_por_emp_ano_mes`, `cte_conc_por_emp_ano_mes`, `separacao_por_emp_ano_mes` (todos pequenos, ok ficarem globais). **Antes de adicionar qualquer novo campo global ao payload, medir o impacto em KB no doc da BRU1** (o maior) com `json.dumps(...).encode('utf-8')` — se for pesado (breakdown por sub-categoria, por dia, etc.), preferir o padrão de `separacao_detalhe`: campo top-level filtrado por empresa em `split_by_empresa`, não dentro de `resumo`.
- **`position:fixed` + `backdrop-filter` no ancestral = containing block trocado** — `header.topbar` tem `backdrop-filter:blur(20px)`, o que o torna o *containing block* de qualquer descendente `position:fixed` (mesma regra de `transform`/`filter`/`will-change`). Definir `left`/`top` de um elemento fixed com coordenadas de `getBoundingClientRect()` (relativas ao viewport) sem descontar a posição do header dá elemento deslocado. Ver `_msPosition()` na seção "Filtros do Topbar — Multiselect". Vale para qualquer novo elemento `position:fixed` criado dentro do `header`.

- **`position:fixed` + `backdrop-filter` no ancestral = containing block trocado** — `header.topbar` tem `backdrop-filter:blur(20px)`, o que o torna o *containing block* de qualquer descendente `position:fixed` (mesma regra de `transform`/`filter`/`will-change`). Definir `left`/`top` de um elemento fixed com coordenadas de `getBoundingClientRect()` (relativas ao viewport) sem descontar a posição do header dá elemento deslocado. Ver `_msPosition()` na seção "Filtros do Topbar — Multiselect". Vale para qualquer novo elemento `position:fixed` criado dentro do `header`.
- **`HTML_TEMPLATE` duplicado em `processar_frete.py`** — gera o `dashboard_frete.html` standalone com HTML/JS quase idêntico ao `index.html`. Mudanças de UI/JS em qualquer aba presente no template (ex.: Marketplace) precisam ser replicadas manualmente nos dois arquivos — ver seção "Módulo Marketplace"
- **SDK Firebase v8** — usar v8.10.1 compat. v10 causa falha no WebChannel
- **Encoding Python** — sempre `$env:PYTHONIOENCODING = "utf-8"` antes de rodar scripts
- **Faturamento período** — NF de Nov/Dez 2024 e Jan 2025 ainda ausentes; exportar do ERP
- **~340 CTe sem vínculo** — não têm NF referenciada, investigação via espelho CT-e na aba Cobertura de Dados
- **`ctes_nao_vinculados` por empresa** — `_split_por_empresa()` usa `_nv_emp(c)` (rem_cnpj → nfe_refs) para filtrar por empresa. CTes sem empresa identificada entram em TODOS os documentos. `ctes_nf_cancelada` filtrado por `empresa_nf`. Antes deste fix, ALL CTes iam para TODOS os documentos.
- **Cobertura de Faturamento — melhorada significativamente (jul/2026)** — ver seção "Busca de CT-e pela chave da NF-e" abaixo. Descrição antiga ("~46%, ~65k Venda de Mercadoria sem CTe são retiradas no depósito") ficou parcialmente desatualizada: parte real do gap era limitação de captura da API (CT-e existia, não era baixado), não retirada no depósito. Não presumir o percentual antigo sem checar o dado atual.
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
