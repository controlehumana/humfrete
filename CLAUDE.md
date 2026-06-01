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
  ├── Frete de Venda           → NF em nf_saida_items → 'detalhes'
  ├── Frete de Compra (NF Entrada) → vw_cte_nf_entrada → 'compras'
  ├── Frete de Compra (dest CNPJ_MAP) → dest_cnpj Humana → 'compras'
  ├── Frete de Compra (tomador Humana) → rem_cnpj Humana + NF externa → 'compras'
  ├── Dev. Marketplace         → transportadora Shopee/ML → 'devolucoes_mkt'
  ├── CTe c/ NF Cancelada      → NF de CNPJ Humana ausente do fat → 'ctes_nf_cancelada'
  └── Sem Vínculo (~338)       → resto → 'ctes_nao_vinculados'
```

## KPIs principais (index.html)

### Cobertura de Faturamento
- **Fórmula:** `nfe_com_cte / nfe_fat_periodo`
- **Denominador (`nfe_fat_periodo`):** NF-e do período CTe (2025+) **excluindo** nat. ops sem frete
- **Nat. ops excluídas:** devoluções (qualquer tipo), entradas (qualquer tipo), perdas/roubo, saldo ICMS, imobilizado, NF consumidor, simples remessa, retorno de locação
- **TRANSFERÊNCIA SAÍDA é mantida** — pode ter CTe associado
- Threshold: verde ≥80%, amarelo ≥65%, vermelho <65%

### CTe Conciliados
- **Fórmula:** `(qtdTotal - qtdSV) / qtdTotal` — calculado dentro do IIFE do Custo Logístico
- Respeita todos os filtros ativos (ano, mês, empresa, transportadora, etc.)
- `qtdSV` = CTes sem vínculo nenhum (`ctes_nao_vinculados`)
- Threshold: verde ≥98%, amarelo ≥90%, vermelho <90%

### % Frete / Venda — Mapa de Transportadoras
- **Denominador:** faturamento das NF-e **transportadas por aquela carrier** (não o total da empresa)
- Mede eficiência: quanto custa transportar R$100 de mercadoria com cada parceiro
- Carriers com clientes de alto ticket médio têm % menor naturalmente

## Arquitetura web (index.html)

- **GitHub Pages:** https://controlehumana.github.io/humfrete/
- **Firebase Auth v8.10.1 compat** (v10 causa falha no WebChannel)
- **Firestore `/dados/{empresa}`:** payload sem detalhes + N chunks de 800 itens
- `_mergeData()` combina dados de todas as empresas autorizadas, somando corretamente `total_cte` e `ctes_nao_vinculados_count`
- **CDN Chart.js:** primário cdnjs, fallback jsdelivr via `onerror`
- **CDN Font Awesome:** primário cdnjs, fallback fontawesome.com via `onerror`
- **Firebase SDK:** guard `typeof firebase !== 'undefined'` antes de inicializar

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
8. **Tooltip geo** — cores via variáveis `tipText`, `tipLabel`, `tipBorder`, `tipAccent`, `tipGold` (tema-aware)
9. **Insight body** — `.ok`/`.hi`/`.bad` têm override para ocean em CSS (`html.ocean .insight-body .ok` etc.)

## Globals críticos (ordem importa)

Declarar no bloco de globals (antes de `onAuthStateChanged`) para evitar TDZ:
- `let DATA = null`
- `let _currentUser = null`
- `let nvBase = [], nvPage = 0, nvRows = []`
- `let CNPJ_EMPRESA = {}`  ← Firebase v8 pode invocar onAuthStateChanged sincronamente

## Erros de carregamento (catch no onAuthStateChanged)

O catch exibe mensagem amigável ao usuário e loga erro técnico no console:
- "Nenhuma empresa" → "Seu acesso não está configurado..."
- "nao encontrados" → "Os dados ainda não foram processados..."
- `permission-denied` → "Sem permissão..."
- `network/failed to fetch` → "Sem conexão..."
- Outros → "Não foi possível carregar o dashboard..."

## Pitfalls conhecidos

- **SDK Firebase v8** — usar v8.10.1 compat. v10 causa falha no WebChannel
- **Encoding Python** — sempre `$env:PYTHONIOENCODING = "utf-8"` antes de rodar scripts
- **Faturamento período** — NF de Nov/Dez 2024 e Jan 2025 ainda ausentes; exportar do ERP
- **~338 CTe sem vínculo** — não têm NF referenciada, investigação manual necessária
- **Cobertura de Faturamento baixa (~46%)** — ~65k "Venda de Mercadoria" sem CTe são provavelmente retiradas no depósito pelo cliente (Caminho B: identificar flag de retirada no ERP para excluir do denominador)
- **Conflito de push git** — uploads via interface web do GitHub divergem do local; usar `git fetch && git reset --soft origin/main`
- **Duplicatas nos filtros** — `initApp()` usa `_initAppDone` para não re-adicionar opções; selects limpos com `clr()` antes de popular
- **`input()` no processar_frete.py** — envolvido em `try/except EOFError` para não travar execução automática
- **Chart.js linha 1347** — `if(typeof Chart!=='undefined')` obrigatório; sem isso, falha de CDN derruba o script inteiro por TDZ em cascata
