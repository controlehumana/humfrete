# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Como executar

```powershell
# Atualização diária D-1 (sem interação — ideal para Agendador de Tarefas)
py atualizar.py

# Reprocessamento manual com período personalizado
py atualizar.py --interativo

# Período fixo sem perguntas
py atualizar.py --data-inicio 01-01-2025 --data-fim 31-05-2026

# Pular download (XMLs já baixados)
py atualizar.py --pular-download

# Encoding obrigatório no PowerShell antes de rodar só o frete
$env:PYTHONIOENCODING = "utf-8"
py processar_frete.py
```

## Estrutura do projeto

```
ClaudeCode/
  atualizar.py               # Orquestrador: D-1 automático por padrão
  QUIVE/
    buscar_cte.py            # Baixa CTe da API Qive → cte.db
    criar_view.py            # Parseia XMLs → tabelas cte_campos, cte_nf
    cte.db                   # SQLite com CTe (não versionado)
  Frete/
    processar_frete.py       # ETL: cte.db + faturamento → Firestore
    index.html               # Web app GitHub Pages (arquivo único)
    CTe/
      FATURAMENTO.csv        # Exportação do ERP (aceita .csv, .xls, .html)
      Geral/
        Tomador/             # XMLs de CTe (CT-e versão 4.0)
        Eventos de cancelamento/
```

## Fluxo de atualização

```
py atualizar.py
  → QUIVE/buscar_cte.py  (baixa CTe da API Qive para cte.db)
  → QUIVE/criar_view.py  (parseia XMLs → tabelas cte_campos, cte_nf)
  → Frete/processar_frete.py  (cruza com faturamento → Firestore)
```

- `atualizar.py` sem argumentos: D-1 automático, zero interação
- Sem risco de duplicatas: INSERT OR IGNORE, DROP+recreate views, Firestore `.set()` sobrescreve
- Base sincronizada até 27/05/2026; a partir daí roda em D-1 diário

## Arquivo de faturamento

`parse_faturamento()` aceita qualquer arquivo na pasta `CTe/` que:
- Tenha extensão `.xls`, `.csv`, `.html` ou `.htm`
- Contenha `"faturamento"` ou `"listagem"` no nome

O arquivo `FATURAMENTO.csv` é válido — sem prefixo de empresa (`BRU1_`, `BRU2_` etc.), vai para `generic_files` e a empresa é derivada da coluna `Empresa` dentro do arquivo.

Detecção automática de separador CSV (`;` ou `,`). Encoding UTF-8 com `errors="replace"`.

## Arquitetura do processar_frete.py

1. **`parse_faturamento()`** — lê CSV/XLS do ERP. Agrupa por chave NF-e (44 dígitos), soma itens da mesma nota. Detecta linha de produto por "LINHAHUM" na coluna `DESCRICAO Item`.

2. **`parse_ctes_from_db()`** — lê `../QUIVE/cte.db` (tabelas `cte_campos` e `cte_nf`). Fallback automático para `parse_ctes()` (XMLs) se banco não encontrado.

3. **`cruzar()`** — join por chave NF-e de 44 dígitos. Calcula frete rateado proporcionalmente ao valor de cada NF-e quando um CTe cobre múltiplas notas. Produz `ctes_nao_vinculados` com campo `nfe_refs` (chaves NF-e referenciadas pelo CTe).

4. **Upload Firestore** — chunked: doc principal sem `detalhes` + docs `{emp}_det_000..N` com 800 itens cada (limite 1MB por doc).

## Empresas / CNPJs

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

**Derivar empresa a partir de chave NF-e (JS):**
```javascript
const emp = CNPJ_EMPRESA[chave.slice(6, 20)];  // posições 6–19 = CNPJ emitente
```

**Derivar número da NF a partir de chave NF-e (JS):**
```javascript
const num = parseInt(ch.slice(25, 34));  // posições 25–33 = nNF (sem zeros à esquerda)
```

## Arquitetura web (index.html)

- **GitHub Pages** serve `index.html` estático
- **Firebase Auth v8.10.1 compat** (email/senha) — v10 causava falha no WebChannel
- **Firestore `/users/{uid}`**: `email`, `displayName`, `isAdmin`, `empresas[]`, `tabs[]`
- **Firestore `/dados/{empresa}`**: payload sem detalhes + `det_chunks` chunks
- `_loadData()` carrega chunks em paralelo e remonta `DATA.detalhes`

## Layout e componentes do index.html

### Sidebar
- Expandido: 224px (`--sb-w`). Colapsado: 60px.
- Botão de colapso: `id="sb-collapse"`, 26px, borda visível.
- **Colapsado**: logo oculto, botão centralizado, `overflow:visible` no sidebar para os tooltips escaparem.
- **Tooltips CSS-only**: `.sb-label` vira `position:absolute` flutuando à direita no hover quando colapsado.
- **Mobile (≤580px)**: sidebar oculto. Barra de navegação fixa no rodapé (`.mob-nav`) com 8 abas.

### Topbar
- `topbar-row1`: breadcrumb, data geração, tema, avatar.
- `topbar-row2`: pills Todos/B2B/Online (`.tb-cat-pill`) + separador + filtros Ano/Mês/Empresa/Mais filtros.
- `hd-adv` (Mais filtros): linha separada abaixo do topbar com `display:flex;flex-wrap:wrap` — nunca inline no row2.

### Filtros
- **Todos/B2B/Online**: `.tb-cat-pill` no topbar-row2, IDs `cat_all`, `cat_b2b`, `cat_online`.
- **Nat. Operação multiselect**: IDs `ms_natop_btn`, `ms_natop_drop`, `ms_natop_wrap`. Posicionado via `getBoundingClientRect()`. Estado: `state.natop` (array de valores incluídos; vazio = sem filtro).
- **state**: `{ano, mes, empresa, linha, natop[], estado, transp, canal, q, categoria}`

### Tabelas — regra obrigatória
**Toda tabela de dados deve usar `class="tw dtbl"` + `style="max-height:70vh;overflow-y:auto"`.**

- `.tw`: `overflow-x:auto`, estilos padrão thead/tbody.
- `.dtbl`: primeiras 3 colunas sticky (left: 0, 58px, 128px), thead sticky no topo.
- Exceção: tabela CTe Cancelados usa `max-height:400px` (menor volume).

### Heatmap % Frete/Venda
- Tema escuro: `hsl(hue, 72%, 30%)` com texto `rgba(255,255,255,.92)` — verde/vermelho vívidos.
- Tema claro (ocean): `hsl(hue, 65%, 87%)` com texto `hsl(hue, 60%, 22%)`.
- Detecta tema via `document.documentElement.classList.contains('ocean')`.

### Cobertura de Dados (CTe não vinculados)
- Campo `nfe_refs`: array de chaves NF-e referenciadas no CTe (44 dígitos cada).
- Coluna **NF-e(s)**: mostra `parseInt(ch.slice(25,34))` em chips azuis.
- Coluna **Empresa**: derivada de `CNPJ_EMPRESA[ch.slice(6,20)]` da primeira ref com match.
- Busca inclui número de NF e código de empresa.

### Login
- Botão olho para mostrar/ocultar senha: `id="login-toggle-pass"`, função `togglePassVisibility()`.
- Erros Firebase humanizados via `_authMsg(code)` — nunca expor `e.message` bruto.
- Cobre: `auth/invalid-credential`, `auth/wrong-password`, `auth/user-not-found`, `auth/too-many-requests`, `auth/network-request-failed`, `auth/user-disabled`, e outros.

### Responsivo
- **≥1600px**: sem `max-width` — ocupa tela inteira.
- **≤900px**: sidebar colapsado automaticamente (60px), sem labels.
- **≤580px**: sidebar oculto, mob-nav no rodapé, `padding-bottom:64px` no main-wrap.

### Marketplace — filtros de canal
- Wrapper: `background:var(--input-bg);border:1px solid var(--bd2)` — nunca `#EAEEF3`.
- Botões `.cat-btn`: sem background por padrão, ativo em `rgba(94,106,210,.2)`.
- Indicadores de cor: `●` laranja para Shopee, `●` amarelo para ML.

## Regras obrigatórias

1. **Tooltips em todos os cards** — `<div class="kpi-tooltip">` em todo card com valor numérico. Cards de gráfico usam `<span class="card-tip">`. Lógica CSS-only via `:hover`. Nunca adicionar card sem tooltip.

2. **Tabelas com dtbl** — toda tabela de listagem usa `.tw.dtbl` + `max-height:70vh;overflow-y:auto`.

3. **Erros Firebase** — sempre usar `_authMsg(e.code)` no catch de auth. Nunca expor `e.message`.

4. **Cores do heatmap** — sempre tema-aware via `_isOcean()`. Nunca hardcode de cor única.

5. **IDs únicos** — cada elemento com ID aparece exatamente uma vez. Ao mover componentes entre sidebar e topbar, remover do local original.

## Pitfalls conhecidos

- **SDK Firebase v8** — usar v8.10.1 compat. v10 causava falha no WebChannel no GitHub Pages.
- **Tamanho do HTML/JSON** — não embutir arrays com 100k+ registros. `nfe_sem_cte` foi removido; só o count fica em `resumo.nfe_sem_cte`.
- **Python 3.13 + ElementTree** — nunca `elem1 or elem2` com elementos XML (sempre truthy). Usar `if el is None`.
- **Encoding** — sempre `$env:PYTHONIOENCODING = "utf-8"` no PowerShell antes de rodar scripts Python.
- **Período do faturamento** — o CSV/XLS deve cobrir o mesmo período dos CTe, senão cruzamento retorna zero vínculos.
- **Conflito de push** — uploads via interface web do GitHub criam commits que divergem do local. Ao receber "rejected: non-fast-forward", usar `git fetch origin && git reset --soft origin/main` para realinhar sem perder mudanças.
