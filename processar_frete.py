#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Processa Faturamento HTML + CTe XMLs e gera dashboard_frete.html autocontido.
Uso: py processar_frete.py
"""

import os
import sys
import json
import re
import csv
from html.parser import HTMLParser
from xml.etree import ElementTree as ET
from collections import defaultdict
from datetime import datetime

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
CTE_DIR     = os.path.join(BASE_DIR, "CTe")
CTE_XML_DIR = os.path.join(CTE_DIR, "Geral", "Tomador")
OUTPUT_HTML = os.path.join(BASE_DIR, "dashboard_frete.html")

NS = "http://www.portalfiscal.inf.br/cte"

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

def br_float(s):
    s = str(s).strip().replace(".", "").replace(",", ".")
    try: return float(s)
    except ValueError: return 0.0

def ns(tag): return f"{{{NS}}}{tag}"

class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.headers=[]; self.rows=[]
        self._in_thead=self._in_tbody=False
        self._in_cell=False; self._is_header=False
        self._cur_row=[]; self._cur_cell=[]
    def handle_starttag(self,tag,attrs):
        if tag=="thead": self._in_thead=True
        elif tag=="tbody": self._in_tbody=True
        elif tag=="tr": self._cur_row=[]
        elif tag in("th","td"):
            self._in_cell=True; self._is_header=self._in_thead; self._cur_cell=[]
    def handle_endtag(self,tag):
        if tag=="thead": self._in_thead=False
        elif tag=="tbody": self._in_tbody=False
        elif tag in("th","td"):
            if self._in_cell:
                t="".join(self._cur_cell).strip()
                if self._is_header: self.headers.append(t)
                elif self._in_tbody: self._cur_row.append(t)
                self._in_cell=False
        elif tag=="tr":
            if self._in_tbody and self._cur_row: self.rows.append(self._cur_row[:])
    def handle_data(self,data):
        if self._in_cell: self._cur_cell.append(data)

def _read_fat_file(fat_file):
    low=fat_file.lower()
    if low.endswith(".csv"):
        with open(fat_file,"r",encoding="utf-8",errors="replace") as f: sample=f.read(4096)
        sep=";" if sample.count(";")>=sample.count(",") else ","
        with open(fat_file,"r",encoding="utf-8",errors="replace",newline="") as f:
            rows_raw=list(csv.reader(f,delimiter=sep))
        if not rows_raw: return [],[]
        return [h.strip() for h in rows_raw[0]], rows_raw[1:]
    else:
        with open(fat_file,"r",encoding="utf-8",errors="replace") as f: content=f.read()
        p=TableParser(); p.feed(content)
        return p.headers, p.rows

def _parse_single_fat(fat_file, nfe_map, force_empresa=None):
    headers, rows_data = _read_fat_file(fat_file)
    if not headers:
        print(f"   [ERRO] Cabecalhos nao encontrados em {os.path.basename(fat_file)}")
        return 0
    col={h.strip():i for i,h in enumerate(headers)}
    def get(row,*names):
        for name in names:
            i=col.get(name,-1)
            if 0<=i<len(row):
                v=row[i]; v=re.sub(r'^="(.*)"$',r'\1',v); return v.strip()
        return ""
    novas=0
    for row in rows_data:
        if not row: continue
        chave=get(row,"Chave")
        if not chave or len(chave)!=44: continue
        if chave not in nfe_map:
            empresa=get(row,"Empresa")
            if not empresa: empresa=CNPJ_MAP.get(chave[6:20],"")
            if not empresa and force_empresa: empresa=force_empresa
            if not empresa: empresa=chave[6:20]
            nfe_map[chave]={
                "chave":chave,"empresa":empresa,"numero":get(row,"NUMERO"),
                "canal":get(row,"Canal"),"data_emissao":get(row,"Data Emissao"),
                "participante":get(row,"Participante"),"cidade":get(row,"Participante Cidade"),
                "estado":get(row,"Participante Estado"),"part_cnpj":get(row,"CPF_CNPJ Participante"),
                "nat_operacao":get(row,"Nat. OPERACAO"),"cod_nat_operacao":get(row,"Cod. Nat OPER"),
                "total_nf":0.0,"custo_total":0.0,"vlr_frete_nf":0.0,
                "margem_bruta":0.0,"linhahum_total":0.0,"humana_total":0.0,
            }
            novas+=1
        nf=nfe_map[chave]
        total_item=br_float(get(row,"Total Item"))
        desc=get(row,"DESCRICAO Item").upper()
        is_linhahum="LINHAHUM" in desc
        nf["total_nf"]+=total_item
        nf["custo_total"]+=br_float(get(row,"Custo Total"))
        nf["vlr_frete_nf"]+=br_float(get(row,"Vlr Frete"))
        nf["margem_bruta"]+=br_float(get(row,"R$ Margem Bruta"))
        if is_linhahum: nf["linhahum_total"]+=total_item
        else: nf["humana_total"]+=total_item
    return novas

def parse_faturamento(base_dir):
    cte_folder=os.path.join(base_dir,"CTe")
    company_files={}; generic_files=[]
    for fname in sorted(os.listdir(cte_folder)):
        low=fname.lower()
        if not(low.endswith(".xls") or low.endswith(".csv") or low.endswith(".html") or low.endswith(".htm")): continue
        if "listagem" not in low and "faturamento" not in low: continue
        parts=fname.split("_",1); prefix=parts[0].upper()
        if len(parts)>=2 and prefix.isalnum() and 2<=len(prefix)<=5:
            company_files[prefix]=os.path.join(cte_folder,fname)
        else:
            generic_files.append(os.path.join(cte_folder,fname))
    nfe_map={}
    all_files=list(company_files.items()) if company_files else []
    generic=[(None,f) for f in generic_files]
    if not all_files and not generic:
        print("[ERRO] Nenhum arquivo de faturamento encontrado."); return {}
    if company_files:
        print(f"[FAT] {len(company_files)} arquivo(s): {', '.join(sorted(company_files))}")
    seen_sizes=set(); unique_files=[]
    for emp,path in all_files+generic:
        size=os.path.getsize(path)
        if size not in seen_sizes:
            seen_sizes.add(size); unique_files.append((emp,path))
        else:
            print(f"   [SKIP] {os.path.basename(path)} — duplicado, ignorado")
    for emp,fat_file in unique_files:
        n=_parse_single_fat(fat_file,nfe_map,force_empresa=emp)
        lbl=f"{emp}: " if emp else ""
        print(f"   {lbl}{n} NF-e ({os.path.basename(fat_file)})")
    print(f"   NF-e unicas totais: {len(nfe_map)}")
    return nfe_map

def parse_cancelamentos():
    """Lê eventos de cancelamento e retorna set com chaves CTe cancelados."""
    cancel_dir = os.path.join(CTE_DIR, "Geral", "Eventos de cancelamento")
    chaves = set()
    if not os.path.isdir(cancel_dir):
        return chaves
    for fname in os.listdir(cancel_dir):
        if not fname.lower().endswith(".xml"):
            continue
        try:
            root = ET.parse(os.path.join(cancel_dir, fname)).getroot()
            for tag in [f"{{{NS}}}chCTe", "chCTe"]:
                el = root.find(f".//{tag}")
                if el is not None and el.text:
                    chaves.add(el.text.strip()); break
        except Exception:
            pass
    print(f"\n[CANCEL] {len(chaves)} CTe cancelados encontrados")
    return chaves

def parse_ctes(cte_xml_dir, chaves_canceladas=None):
    if not os.path.isdir(cte_xml_dir):
        print(f"[ERRO] Pasta CTe XML nao encontrada: {cte_xml_dir}"); return [],[],0
    xml_files=sorted(f for f in os.listdir(cte_xml_dir) if f.lower().endswith(".xml"))
    total=len(xml_files)
    print(f"\n[CTE] {total} arquivos em {os.path.relpath(cte_xml_dir)}")
    cte_list=[]; nfe_to_cte=defaultdict(list); erros=0; n_cancelados_skip=0; cancelados_lista=[]

    def _find(node, tag):
        el = node.find(ns(tag))
        if el is None:
            el = node.find(tag)
        return el

    def _find_deep(node, tag):
        el = node.find(f".//{ns(tag)}")
        if el is None:
            el = node.find(f".//{tag}")
        return el

    def _txt(el):
        return el.text.strip() if el is not None and el.text else ""

    for i,fname in enumerate(xml_files,1):
        if i%1000==0 or i==total: print(f"   {i}/{total} ({i/total*100:.0f}%)...",end="\r")
        fpath=os.path.join(cte_xml_dir,fname)
        try: tree=ET.parse(fpath); root=tree.getroot()
        except Exception: erros+=1; continue
        infcte = root.find(f".//{ns('infCte')}")
        if infcte is None:
            infcte = root.find(".//infCte")
        if infcte is None: erros+=1; continue
        cte_chave=infcte.get("Id","").replace("CTe","").strip()
        if chaves_canceladas and cte_chave in chaves_canceladas:
            _vp=_find_deep(infcte,"vPrest"); _v=0.0
            if _vp is not None:
                _vt=_find(_vp,"vTPrest")
                if _vt is not None and _vt.text:
                    try: _v=float(_vt.text.strip())
                    except ValueError: pass
            _em=_find(infcte,"emit"); _tr=""
            if _em is not None:
                _xn=_find(_em,"xNome")
                if _xn is not None and _xn.text: _tr=_xn.text.strip()
            cancelados_lista.append({"cte_chave":cte_chave,"valor_frete":round(_v,2),"transportadora":_tr})
            n_cancelados_skip+=1; continue
        transportadora=""
        emit_el = _find(infcte, "emit")
        if emit_el is not None:
            xn = _find(emit_el, "xNome")
            if xn is not None and xn.text: transportadora=xn.text.strip()
        ide = _find(infcte, "ide")
        def ide_txt(tag):
            if ide is None: return ""
            el = _find(ide, tag)
            return _txt(el)
        data_emissao=ide_txt("dhEmi"); origem_cidade=ide_txt("xMunIni"); origem_uf=ide_txt("UFIni")
        destino_cidade=ide_txt("xMunFim"); destino_uf=ide_txt("UFFim")
        dest_cnpj=""
        dest_el=_find(infcte,"dest")
        if dest_el is not None:
            cnpj_el=_find(dest_el,"CNPJ")
            if cnpj_el is not None and cnpj_el.text: dest_cnpj=cnpj_el.text.strip()
        rem_nome=""
        rem_el=_find(infcte,"rem")
        if rem_el is not None:
            xn=_find(rem_el,"xNome")
            if xn is not None and xn.text: rem_nome=xn.text.strip()
        vprest = _find_deep(infcte, "vPrest")
        vTPrest=0.0
        if vprest is not None:
            vtot = _find(vprest, "vTPrest")
            if vtot is not None and vtot.text:
                try: vTPrest=float(vtot.text.strip())
                except ValueError: pass
        peso_kg=0.0; volume_m3=0.0
        infcarga_el=_find_deep(infcte,"infCarga")
        if infcarga_el is not None:
            for infq_el in list(infcarga_el.findall(ns("infQ")))+list(infcarga_el.findall("infQ")):
                cunid=_txt(_find(infq_el,"cUnid"))
                qcarga=_find(infq_el,"qCarga")
                if qcarga is not None and qcarga.text:
                    try:
                        q=float(qcarga.text.strip())
                        if cunid in ("01","02",""): peso_kg+=q
                        elif cunid=="03": volume_m3+=q
                    except ValueError: pass
        nfe_chaves=[]
        for tag in(ns("infNFe"),ns("infDCe"),"infNFe","infDCe"):
            for el in root.findall(f".//{tag}"):
                ch = el.find(ns("chave"))
                if ch is None:
                    ch = el.find("chave")
                if ch is not None and ch.text: nfe_chaves.append(ch.text.strip())
        cte_data={"cte_chave":cte_chave,"transportadora":transportadora,"data_emissao":data_emissao,
            "origem_cidade":origem_cidade,"origem_uf":origem_uf,"destino_cidade":destino_cidade,
            "destino_uf":destino_uf,"dest_cnpj":dest_cnpj,"rem_nome":rem_nome,"valor_frete":vTPrest,
            "nfe_chaves":nfe_chaves,"peso_kg":round(peso_kg,2),"volume_m3":round(volume_m3,3),
            "qtd_nfe":len(nfe_chaves)}
        cte_list.append(cte_data)
        for ch in nfe_chaves: nfe_to_cte[ch].append(cte_data)
    print(f"\n   Processados: {len(cte_list)}  |  Cancelados ignorados: {n_cancelados_skip}  |  Erros: {erros}")
    print(f"   NF-e unicas referenciadas: {len(nfe_to_cte)}")
    return cte_list,nfe_to_cte,n_cancelados_skip,cancelados_lista

def cruzar(nfe_map, cte_list, nfe_to_cte):
    print("\n[OK] Cruzando dados...")
    # Marketplace detectado pelo nome da transportadora OU pelo canal de venda
    SHOPEE_TR  = {"SHPS TECNOLOGIA E SERVIÇO LTDA","SHPS TECNOLOGIA E SERVICO LTDA","SHOPEE"}
    ML_TR      = {"EBAZARCOMBR LTDA","MERCADO LIVRE"}
    SHOPEE_CH  = {"SHOPPE","SHOPEE"}
    ML_CH      = {"MERCADO LIVRE"}
    def _marketplace_type(tr, canal):
        tr_up = (tr or "").upper().strip()
        ch_up = (canal or "").upper().strip()
        if any(s in tr_up for s in ["SHPS","SHOPEE"]) or ch_up in SHOPEE_CH:
            return "shopee"
        if any(s in tr_up for s in ["EBAZAR","MERCADO LIVRE"]) or ch_up in ML_CH:
            return "ml"
        return None
    def _is_marketplace(tr, canal):
        return _marketplace_type(tr, canal) is not None
    # Pré-calcula fração de rateio por CTe: quando um CTe cobre múltiplas NF-e
    # do faturamento, o frete é dividido proporcionalmente ao valor de cada NF-e
    cte_rateio = {}  # cte_chave -> {nfe_chave: fração}
    for cte in cte_list:
        nfes_em_fat = [(ch, nfe_map[ch]) for ch in cte["nfe_chaves"] if ch in nfe_map]
        if not nfes_em_fat: continue
        if len(nfes_em_fat) == 1:
            cte_rateio[cte["cte_chave"]] = {nfes_em_fat[0][0]: 1.0}
        else:
            total_val = sum(nfe["total_nf"] or 1 for _, nfe in nfes_em_fat) or 1
            cte_rateio[cte["cte_chave"]] = {
                ch: round((nfe["total_nf"] or 1) / total_val, 6)
                for ch, nfe in nfes_em_fat
            }
    detalhes=[]; nfe_sem_cte=[]
    for chave,nfe in nfe_map.items():
        ctes=nfe_to_cte.get(chave,[])
        if ctes:
            for cte in ctes:
                total_nf=nfe["total_nf"] or 1
                lh_pct=nfe["linhahum_total"]/total_nf; hu_pct=nfe["humana_total"]/total_nf
                # Rateio: fração proporcional do frete deste CTe para esta NF-e
                frac=cte_rateio.get(cte["cte_chave"],{}).get(chave,1.0)
                qtd_nfes_fat=len(cte_rateio.get(cte["cte_chave"],{}))
                is_rateio=qtd_nfes_fat>1
                frete_rateado=round(cte["valor_frete"]*frac,2)
                frete_linhahum=round(frete_rateado*lh_pct,2); frete_humana=round(frete_rateado*hu_pct,2)
                if nfe["linhahum_total"]>0 and nfe["humana_total"]==0: linha="Linhahum"
                elif nfe["humana_total"]>0 and nfe["linhahum_total"]==0: linha="Humana Alimentar"
                else: linha="Misto"
                frete_cobrado=round(nfe["vlr_frete_nf"],2)
                diferenca=round(frete_cobrado-frete_rateado,2)
                detalhes.append({
                    "chave_nfe":nfe["chave"],"empresa":nfe["empresa"],"numero":nfe["numero"],
                    "data":nfe["data_emissao"],"canal":nfe["canal"],"nat_operacao":nfe["nat_operacao"],
                    "cliente":nfe["participante"],"cidade":nfe["cidade"],"estado":nfe["estado"],
                    "part_cnpj":nfe["part_cnpj"],"cod_nat_operacao":nfe["cod_nat_operacao"],
                    "total_nf":round(nfe["total_nf"],2),"linhahum_total":round(nfe["linhahum_total"],2),
                    "humana_total":round(nfe["humana_total"],2),"custo_total":round(nfe["custo_total"],2),
                    "margem_bruta":round(nfe["margem_bruta"],2),"linha":linha,
                    "cte_chave":cte["cte_chave"],"transportadora":cte["transportadora"],
                    "origem_cidade":cte["origem_cidade"],"origem_uf":cte["origem_uf"],
                    "destino_cidade":cte["destino_cidade"],"destino_uf":cte["destino_uf"],"dest_cnpj":cte["dest_cnpj"],
                    "valor_frete":frete_rateado,"valor_frete_cte":cte["valor_frete"],
                    "frete_cobrado":frete_cobrado,"diferenca_frete":diferenca,
                    "frete_linhahum":frete_linhahum,"frete_humana":frete_humana,
                    "peso_kg":round(cte["peso_kg"],2),"qtd_nf_cte":cte["qtd_nfe"],
                    "is_rateio":is_rateio,"pct_rateio":round(frac*100,1),
                    "qtd_nfes_fat":qtd_nfes_fat,
                    "is_marketplace":_is_marketplace(cte["transportadora"],nfe["canal"]),
                    "marketplace_type":_marketplace_type(cte["transportadora"],nfe["canal"]),
                })
        else:
            nfe_sem_cte.append({"chave_nfe":nfe["chave"],"numero":nfe["numero"],"data":nfe["data_emissao"],
                "canal":nfe["canal"],"cliente":nfe["participante"],"estado":nfe["estado"],
                "total_nf":round(nfe["total_nf"],2)})
    print(f"   NF-e com CTe: {len(detalhes)}")
    print(f"   NF-e sem CTe: {len(nfe_sem_cte)}")
    cte_nfe_keys=set(nfe_to_cte.keys()); fat_keys=set(nfe_map.keys())
    cte_sem_fat=len(cte_nfe_keys-fat_keys)
    print(f"   CTe sem NF-e no faturamento: {cte_sem_fat}")
    linked_cte_chaves=set(d["cte_chave"] for d in detalhes)
    def _motivo_sem_vinculo(cte):
        if not cte["nfe_chaves"]:
            return "CTe não informou nota fiscal de origem"
        n=len(cte["nfe_chaves"])
        return f"Nota fiscal não encontrada no faturamento ({n} NF referenciada{'s' if n>1 else ''})"
    ctes_nao_vinculados=[{
        "cte_chave":cte["cte_chave"],"transportadora":cte["transportadora"],
        "data_emissao":cte["data_emissao"][:10] if cte["data_emissao"] else "",
        "origem_cidade":cte["origem_cidade"],"origem_uf":cte["origem_uf"],
        "destino_cidade":cte["destino_cidade"],"destino_uf":cte["destino_uf"],
        "valor_frete":cte["valor_frete"],"nfe_refs":cte["nfe_chaves"],
        "motivo":_motivo_sem_vinculo(cte),
    } for cte in cte_list if cte["cte_chave"] not in linked_cte_chaves]
    print(f"   CTe sem vinculo no dashboard: {len(ctes_nao_vinculados)}")
    # CTe de compra/devolução: destinatário é empresa Humana e não está vinculado ao faturamento de vendas
    def _mkt_type_tr(tr):
        t=(tr or "").upper()
        if any(s in t for s in ["SHPS","SHOPEE"]): return "shopee"
        if any(s in t for s in ["EBAZAR","MERCADO LIVRE"]): return "ml"
        return None
    compras=[]; devolucoes_mkt=[]
    for cte in cte_list:
        if cte["cte_chave"] in linked_cte_chaves or cte["dest_cnpj"] not in CNPJ_MAP: continue
        mkt=_mkt_type_tr(cte["transportadora"])
        row={"cte_chave":cte["cte_chave"],"transportadora":cte["transportadora"],
             "data_emissao":cte["data_emissao"][:10] if cte["data_emissao"] else "",
             "rem_nome":cte["rem_nome"],"origem_cidade":cte["origem_cidade"],"origem_uf":cte["origem_uf"],
             "destino_cidade":cte["destino_cidade"],"destino_uf":cte["destino_uf"],
             "empresa_dest":CNPJ_MAP.get(cte["dest_cnpj"],""),
             "valor_frete":cte["valor_frete"],"nfe_refs":cte["nfe_chaves"],
             "peso_kg":cte["peso_kg"],"volume_m3":cte["volume_m3"]}
        if mkt:
            devolucoes_mkt.append({**row,"mkt_type":mkt})
        else:
            compras.append(row)
    print(f"   CTe de compra (frete entrada): {len(compras)}")
    print(f"   CTe devolução marketplace: {len(devolucoes_mkt)}")
    # Diagnóstico: nat_operacao + cod_nat por empresa — de detalhes (NF-e com CTe)
    _diag=defaultdict(lambda:defaultdict(int))
    for d in detalhes:
        chave_nat=f"{d['nat_operacao'] or 'N/A'} | cod={d['cod_nat_operacao'] or '-'}"
        _diag[d["empresa"]][chave_nat]+=1
    print("   [DIAG CTe] Nat. Operação+Cod por empresa (NF-e com CTe):")
    for emp in sorted(_diag): print(f"      {emp}: "+", ".join(f"{k}({v})" for k,v in sorted(_diag[emp].items(),key=lambda x:-x[1])[:6]))
    # Diagnóstico: do faturamento completo (inclui NF-e sem CTe)
    _diag2=defaultdict(lambda:defaultdict(int))
    for nf in nfe_map.values():
        chave_nat=f"{nf.get('nat_operacao') or 'N/A'} | cod={nf.get('cod_nat_operacao') or '-'}"
        _diag2[nf.get('empresa') or 'N/A'][chave_nat]+=1
    print("   [DIAG FAT] Nat. Operação+Cod por empresa (TODO o faturamento):")
    for emp in sorted(_diag2): print(f"      {emp}: "+", ".join(f"{k}({v})" for k,v in sorted(_diag2[emp].items(),key=lambda x:-x[1])[:6]))
    por_nat_op=defaultdict(lambda:{"qtd":0,"frete":0.0,"cobrado":0.0,"diferenca":0.0,"nf":0.0})
    total_frete=0.0
    for d in detalhes:
        nat=d["nat_operacao"] or "N/A"; fr=d["valor_frete"]
        por_nat_op[nat]["qtd"]+=1; por_nat_op[nat]["frete"]+=fr
        por_nat_op[nat]["cobrado"]+=d["frete_cobrado"]; por_nat_op[nat]["diferenca"]+=d["diferenca_frete"]
        por_nat_op[nat]["nf"]+=d["total_nf"]; total_frete+=fr
    qtd_com=len(detalhes)
    total_faturamento=round(sum(nf["total_nf"] for nf in nfe_map.values()),2)
    # Mapa de transferências do faturamento (todas, com ou sem CTe) agrupado por empresa|ano|mes
    _nat_transf_py=re.compile(r'TRANSFER|1-00005-0000002',re.IGNORECASE)
    transf_fat={}
    for nf in nfe_map.values():
        _nat=nf.get("nat_operacao") or ""; _cod=nf.get("cod_nat_operacao") or ""
        if not(_nat_transf_py.search(_nat) or _nat_transf_py.search(_cod)): continue
        data=nf.get("data_emissao","") or ""
        mes=data[3:5] if len(data)>=5 else ""; ano=data[6:10] if len(data)>=10 else ""
        key=f"{nf.get('empresa','') or 'N/A'}||{ano}||{mes}"
        transf_fat[key]=transf_fat.get(key,0)+1
    # NF-e de transferência do faturamento sem CTe vinculado
    linked_nfe_chaves=set(d["chave_nfe"] for d in detalhes)
    transf_sem_cte_list=[]
    for chave,nf in nfe_map.items():
        if chave in linked_nfe_chaves: continue
        _nat=nf.get("nat_operacao") or ""; _cod=nf.get("cod_nat_operacao") or ""
        if not(_nat_transf_py.search(_nat) or _nat_transf_py.search(_cod)): continue
        transf_sem_cte_list.append({
            "chave":chave,"empresa":nf.get("empresa") or "","numero":nf.get("numero") or "",
            "data":nf.get("data_emissao") or "","cliente":nf.get("participante") or "",
            "cidade":nf.get("cidade") or "","estado":nf.get("estado") or "",
            "part_cnpj":nf.get("part_cnpj") or "","nat_operacao":_nat,
            "total_nf":round(nf.get("total_nf") or 0,2),
        })
    def make_list(d,key="frete"):
        return sorted([{"label":k,**v} for k,v in d.items()],key=lambda x:-x[key])
    return {
        "gerado_em":datetime.now().strftime("%d/%m/%Y %H:%M"),
        "resumo":{"total_cte":len(cte_list),"total_nfe_fat":len(nfe_map),"nfe_com_cte":qtd_com,
            "nfe_sem_cte":len(nfe_sem_cte),"cte_sem_fat":cte_sem_fat,
            "valor_total_frete":round(total_frete,2),"media_frete":round(total_frete/qtd_com,2) if qtd_com else 0,
            "total_faturamento":total_faturamento},
        "transf_fat":transf_fat,"transf_sem_cte":transf_sem_cte_list,"cnpj_map":CNPJ_MAP,
        "por_nat_op":make_list(por_nat_op),"detalhes":detalhes,"ctes_nao_vinculados":ctes_nao_vinculados,
        "compras":compras,"devolucoes_mkt":devolucoes_mkt,
    }


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Gestão de Fretes - Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
<style>
:root{
  --bg:#0B0F14;--s1:#111827;--s2:#1C2638;--s3:#243348;
  --bd:#1E2D42;--bd2:#2A3F58;
  --blue:#3B82F6;--blue2:#60A5FA;--cyan:#22D3EE;
  --green:#10B981;--green2:#34D399;
  --yellow:#F59E0B;--amber:#FCD34D;
  --red:#EF4444;--red2:#F87171;--purple:#7C3AED;--purple2:#A78BFA;
  --text:#F1F5F9;--text2:#94A3B8;--text3:#4E6880;
  --r:10px;--rL:14px;
  --shadow:0 4px 24px rgba(0,0,0,.5);
  --shadow-md:0 8px 40px rgba(0,0,0,.65);
  --card-bg:#111827;--header-bg:#0D1320;--input-bg:#1C2638;
  --pill-bg:#1C2638;--sticky-bg:#111827;--row-border:#0F172A;
  --hero-blue:#0F1D32;--hero-green:#0A1F18;--hero-amber:#1A1500;--hero-dyn:#120E28;
  --tooltip-bg:#1E2D42;--heatmap-empty:#0A1628;
}
/* TEMA OCEAN — alternativo colorido */
html.ocean{
  --bg:#071B2E;--s1:#0D2744;--s2:#102F52;--s3:#143860;
  --bd:#1A4A78;--bd2:#235E96;
  --text:#E8F4FD;--text2:#7EC8E3;--text3:#4A90B8;
  --shadow:0 4px 24px rgba(0,0,0,.6);--shadow-md:0 8px 40px rgba(0,0,0,.7);
  --card-bg:#0D2744;--header-bg:#040F1C;--input-bg:#091D30;
  --pill-bg:#091D30;--sticky-bg:#0D2744;--row-border:#071525;
  --hero-blue:#091E3A;--hero-green:#071E24;--hero-amber:#1A1204;--hero-dyn:#0C0A28;
  --tooltip-bg:#0D2744;--heatmap-empty:#040F1C;
}
html.ocean body{
  background:var(--bg);
  background-image:
    radial-gradient(ellipse 900px 600px at 10% 0%,rgba(0,180,255,.10) 0%,transparent 65%),
    radial-gradient(ellipse 700px 500px at 90% 100%,rgba(0,80,180,.08) 0%,transparent 65%);
}
html.ocean header{background:var(--header-bg);border-color:var(--bd)}
html.ocean .tabs{background:var(--header-bg);border-color:var(--bd)}
html.ocean .kpi-card:hover{border-color:var(--blue2)}
html.ocean .cat-pill{background:var(--pill-bg)}
html.ocean .hd-filter-item{background:var(--input-bg)}
*{box-sizing:border-box;margin:0;padding:0}
html{scrollbar-color:#1E3A52 #0B0F14;scrollbar-width:thin}
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:#0B0F14}
::-webkit-scrollbar-thumb{background:#1E3A52;border-radius:3px}
::-webkit-scrollbar-thumb:hover{background:#2D5070}
body{
  background:var(--bg);color:var(--text);
  font-family:'Inter','Segoe UI',system-ui,sans-serif;font-size:13px;line-height:1.5;
  background-image:
    radial-gradient(ellipse 900px 600px at 10% 0%,rgba(0,212,255,.06) 0%,transparent 65%),
    radial-gradient(ellipse 700px 500px at 90% 100%,rgba(124,58,237,.05) 0%,transparent 65%);
}

/* HEADER — 2 linhas: topo (identidade+cat) + filtros (barra própria) */
header{
  background:var(--header-bg);
  border-bottom:1px solid var(--bd);
  padding:0;
  display:flex;flex-direction:column;
  position:sticky;top:0;z-index:200;
  box-shadow:0 2px 12px rgba(0,0,0,.5);
}
.hd-row1{
  display:flex;align-items:center;gap:10px;padding:0 16px;height:44px;
  border-bottom:1px solid var(--bd);flex-shrink:0;
}
.hd-row2{
  display:flex;align-items:center;gap:6px;padding:0 16px;height:38px;
  overflow-x:auto;overflow-y:hidden;flex-shrink:0;
  scrollbar-width:none;
}
.hd-row2::-webkit-scrollbar{display:none}
.hd-adv{display:contents}
.hd-adv.hidden{display:none}
.hd-adv-btn{gap:4px;display:flex;align-items:center}
.hd-logo{
  width:28px;height:28px;flex-shrink:0;border-radius:7px;
  background:linear-gradient(135deg,#3B82F6,#7C3AED);
  display:flex;align-items:center;justify-content:center;
  font-size:11px;font-weight:900;color:#fff;letter-spacing:-.5px;
}
.hd-title{font-size:13px;font-weight:700;letter-spacing:-.2px;white-space:nowrap;color:var(--text)}
.hd-sep{width:1px;height:20px;background:var(--bd2);flex-shrink:0;margin:0 2px}
.hd-stamp{font-size:10px;color:var(--text3);white-space:nowrap;flex-shrink:0;margin-left:auto}
/* Filters na linha 2 — todos na mesma linha com scroll horizontal */
.hd-filters{display:contents}
.hd-filter-item{
  background:var(--input-bg);border:1px solid var(--bd2);border-radius:6px;
  padding:3px 7px;color:var(--text);font-size:11px;font-family:inherit;outline:none;cursor:pointer;
  transition:border-color .15s;white-space:nowrap;flex-shrink:0;height:28px;
}
.hd-filter-item:focus{border-color:var(--blue2)}

/* CATEGORIA PILLS */
.cat-pills{display:flex;gap:3px;flex-shrink:0}
.cat-pill-wrap{position:relative;display:inline-block}
.cat-pill{
  padding:4px 11px;border-radius:20px;font-size:11px;font-weight:600;cursor:pointer;
  border:1px solid var(--bd2);background:var(--pill-bg);color:var(--text2);transition:all .15s;
}
.cat-pill.active{background:var(--blue);border-color:var(--blue);color:#fff}
.cat-pill:hover:not(.active){border-color:var(--blue2);color:var(--blue2)}
.cat-pill-tip{
  display:none;position:absolute;top:calc(100% + 8px);left:0;
  background:var(--tooltip-bg);color:#CBD5E1;font-size:10px;line-height:1.7;
  padding:10px 14px;border-radius:8px;min-width:260px;z-index:9999;
  border:1px solid var(--bd2);box-shadow:0 8px 24px rgba(0,0,0,.7);
  pointer-events:none;white-space:normal;
}
.cat-pill-tip::before{content:'';position:absolute;bottom:100%;left:18px;
  border:5px solid transparent;border-bottom-color:var(--bd2)}
.cat-pill-tip strong{color:var(--text);display:block;margin-bottom:4px}
.cat-pill-tip span{color:#8AA4C8;font-size:9px}
.cat-pill-wrap:hover .cat-pill-tip{display:block}

/* ACTIVE FILTERS */
#active-filters{display:flex;gap:5px;flex-wrap:wrap;padding:6px 20px 0;min-height:0}
.ftag{
  display:inline-flex;align-items:center;gap:4px;
  background:rgba(0,212,255,.08);border:1px solid rgba(0,212,255,.2);
  color:var(--blue);padding:2px 9px;border-radius:20px;font-size:10px;font-weight:600;
}
.ftag .rm{cursor:pointer;opacity:.6;font-size:12px}
.ftag .rm:hover{opacity:1;color:var(--red2)}

/* TABS */
.tabs{
  display:flex;padding:0 20px;
  background:var(--header-bg);
  border-bottom:1px solid var(--bd);margin-top:0;overflow-x:auto;
}
.tab-btn{
  padding:10px 16px;background:none;border:none;border-bottom:2px solid transparent;
  color:var(--text3);font-size:12px;font-weight:600;font-family:inherit;
  cursor:pointer;transition:all .2s;white-space:nowrap;
}
.tab-btn:hover{color:var(--text2)}
.tab-btn.active{color:var(--blue2);border-bottom-color:var(--blue)}
.tab-badge{
  display:inline-block;background:rgba(255,255,255,.06);color:var(--text3);
  padding:1px 6px;border-radius:10px;font-size:9px;font-weight:700;margin-left:4px;
}
.tab-btn.active .tab-badge{background:rgba(0,212,255,.15);color:var(--blue)}
.tab-highlight{
  border-top:2px solid rgba(0,212,255,.45);
  border-left:1px solid rgba(0,212,255,.2);
  border-right:1px solid rgba(0,212,255,.2);
  border-radius:5px 5px 0 0;
  background:rgba(0,212,255,.04);
  color:var(--text2)!important;
  margin-top:3px;
}
.tab-highlight.active{
  border-top-color:var(--blue);
  border-left-color:rgba(0,212,255,.35);
  border-right-color:rgba(0,212,255,.35);
  background:rgba(0,212,255,.07);
}
.tab-panel{display:none}
.tab-panel.active{display:flex;flex-direction:column;gap:16px;padding:18px 20px 32px}

/* CARDS */
.card{
  background:var(--card-bg);
  border:1px solid var(--bd);border-radius:var(--rL);padding:18px;
  box-shadow:var(--shadow);
}
.card-title{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:var(--text3);margin-bottom:14px}

/* HERO KPIs */
.hero-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
@media(max-width:1200px){.hero-grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:580px){.hero-grid{grid-template-columns:1fr}}
.hero-card{
  border:1px solid var(--bd);border-radius:var(--rL);padding:22px 20px;
  position:relative;overflow:visible;cursor:default;
  transition:transform .2s,box-shadow .2s;
}
.hero-card:hover{transform:translateY(-2px);box-shadow:var(--shadow-md);z-index:10}
.hero-card.c-blue{background:var(--hero-blue);border-color:#1E3A5A}
.hero-card.c-blue::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;
  background:linear-gradient(90deg,#3B82F6,#7C3AED);border-radius:var(--rL) var(--rL) 0 0;}
.hero-card.c-green{background:var(--hero-green);border-color:#1A3D2B}
.hero-card.c-green::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;
  background:linear-gradient(90deg,#10B981,#3B82F6);border-radius:var(--rL) var(--rL) 0 0;}
.hero-card.c-amber{background:var(--hero-amber);border-color:#3D3000}
.hero-card.c-amber::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;
  background:linear-gradient(90deg,#F59E0B,#EF4444);border-radius:var(--rL) var(--rL) 0 0;}
.hero-card.c-dynamic{background:var(--hero-dyn);border-color:#2A1F50}
.hero-card.c-dynamic::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;
  background:linear-gradient(90deg,#7C3AED,#3B82F6,#10B981);border-radius:var(--rL) var(--rL) 0 0;}
.hero-icon{width:36px;height:36px;border-radius:9px;display:flex;align-items:center;justify-content:center;font-size:16px;margin-bottom:12px}
.hero-icon.ib{background:#1E3A5A}
.hero-icon.ig{background:#1A3D2B}
.hero-icon.ia{background:#3D3000}
.hero-icon.ip{background:#2A1F50}
.hero-lbl{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.7px;color:var(--text2);margin-bottom:6px}
.hero-val{font-size:30px;font-weight:900;color:var(--text);line-height:1;margin-bottom:8px;letter-spacing:-1px}
.hero-sub{font-size:11px;color:var(--text2);display:flex;align-items:center;gap:5px;flex-wrap:wrap}

/* TOOLTIP */
.hero-card{position:relative}
.kpi-tooltip{
  display:none;position:absolute;top:calc(100% + 10px);left:50%;transform:translateX(-50%);
  background:var(--tooltip-bg);color:var(--text2);font-size:11px;line-height:1.6;
  padding:10px 14px;border-radius:10px;width:260px;z-index:9999;pointer-events:none;
  border:1px solid var(--bd2);
  box-shadow:0 12px 40px rgba(0,0,0,.8);
}
.kpi-tooltip::after{content:'';position:absolute;bottom:100%;left:50%;transform:translateX(-50%);
  border:5px solid transparent;border-bottom-color:#1E2D42}
.hero-card:hover{z-index:100}
.hero-card:hover .kpi-tooltip{display:block}
.kpi-card:hover{z-index:100}
.kpi-card:hover .kpi-tooltip{display:block}
.insight-card:hover .kpi-tooltip{display:block}
.kpi-card{position:relative}

/* CHIPS */
.chip{padding:2px 8px;border-radius:4px;font-size:10px;font-weight:700;display:inline-block;letter-spacing:.2px}
.chip-green{background:#1A3D2B;color:var(--green2);border:1px solid #2A5C3F}
.chip-red  {background:#3D1515;color:var(--red2);border:1px solid #6B2020}
.chip-amber{background:#3D2E00;color:var(--amber);border:1px solid #6B4F00}
.chip-blue {background:#1A2D4A;color:var(--blue2);border:1px solid #2A4A7A}
.chip-gray {background:#1C2638;color:var(--text2);border:1px solid var(--bd2)}

/* SECONDARY KPIs */
.kpi-row{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}
@media(max-width:1200px){.kpi-row{grid-template-columns:repeat(3,1fr)}}
@media(max-width:700px){.kpi-row{grid-template-columns:repeat(2,1fr)}}
@media(max-width:400px){.kpi-row{grid-template-columns:1fr}}
.kpi-card{
  background:var(--card-bg);
  border:1px solid var(--bd);border-radius:var(--r);padding:14px 15px;
  display:flex;flex-direction:column;gap:3px;
  transition:border-color .2s,box-shadow .2s;
}
.kpi-card:hover{border-color:var(--bd2);box-shadow:var(--shadow)}
.kpi-lbl{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.7px;color:var(--text2)}
.kpi-val{font-size:20px;font-weight:800;color:var(--text);letter-spacing:-.5px}
.kpi-sub{font-size:10px;color:var(--text2);margin-top:1px}

/* LINHA PRODUTO CARD */
.lp-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}
@media(max-width:1200px){.lp-grid{grid-template-columns:repeat(3,1fr)}}
@media(max-width:700px){.lp-grid{grid-template-columns:repeat(2,1fr)}}
.lp-card-lh{border-color:#2A5C3F!important}
.lp-card-hu{border-color:#2A4A7A!important}

/* ALERTS */
#alerts-row{display:flex;flex-direction:column;gap:6px}
.alert{display:flex;align-items:flex-start;gap:10px;padding:10px 14px;border-radius:var(--r);font-size:12px}
.alert.a-red   {background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.3);color:var(--red2)}
.alert.a-yellow{background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.25);color:var(--amber)}
.alert.a-green {background:rgba(16,185,129,.08);border:1px solid rgba(16,185,129,.25);color:var(--green2)}
.alert-icon{font-size:14px;flex-shrink:0;margin-top:1px}
.alert-text strong{font-weight:700}

/* SECTION DIVIDER */
.sdiv{display:flex;align-items:center;gap:10px;font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:1.2px;color:var(--text3)}
.sdiv::after{content:'';flex:1;height:1px;background:linear-gradient(90deg,rgba(0,212,255,.2),transparent)}

/* CHARTS */
.ch2{display:grid;grid-template-columns:3fr 2fr;gap:12px}
.ch2eq{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:1000px){.ch2,.ch2eq{grid-template-columns:1fr}}
.ch-wrap{position:relative;height:250px}
.ch-wrap-lg{position:relative;height:300px}
.ch-wrap-xl{position:relative;height:320px}

/* TABLE */
.sr{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
.sr input,.sr select{
  background:var(--input-bg);border:1px solid var(--bd2);border-radius:6px;
  padding:6px 11px;color:var(--text);font-size:12px;font-family:inherit;outline:none;
  transition:border-color .15s;
}
.sr input{flex:1;min-width:180px}
.sr input:focus,.sr select:focus{border-color:var(--blue);box-shadow:0 0 0 2px rgba(0,212,255,.12)}
.tw{overflow-x:auto}
.tw table{width:100%;border-collapse:collapse;font-size:12px}
.tw thead th{
  background:#0D1525;padding:8px 11px;text-align:left;
  color:#E2E8F0;font-size:9px;font-weight:700;text-transform:uppercase;
  letter-spacing:.6px;border-bottom:1px solid rgba(0,212,255,.15);white-space:nowrap;
}
.tw tbody tr{transition:background .12s}
.tw tbody tr:hover td{background:var(--s2)!important}
.tw tbody td{padding:7px 11px;border-bottom:1px solid var(--bd);white-space:nowrap;color:var(--text2);background:var(--card-bg)}
.tw tbody td strong{color:var(--text)}
.tag{display:inline-block;padding:2px 7px;border-radius:4px;font-size:10px;font-weight:700}
.tg{background:#1A3D2B;color:var(--green2);border:1px solid #2A5C3F}
.ty{background:#3D2E00;color:var(--amber);border:1px solid #6B4F00}
.tr{background:#3D1515;color:var(--red2);border:1px solid #6B2020}
.tb{background:#1A2D4A;color:var(--blue2);border:1px solid #2A4A7A}

/* ROW ALERT — linha toda quando % frete > 10% */
.row-alert td{background:#2A1515!important;color:var(--red2)!important}
.row-alert:hover td{background:#3D1515!important}

/* PAGINATION */
.pager{display:flex;gap:4px;align-items:center;margin-top:12px;justify-content:flex-end}
.pager button{
  background:rgba(28,38,56,.9);border:1px solid var(--bd2);border-radius:5px;
  padding:4px 9px;color:var(--text2);cursor:pointer;font-size:10px;font-family:inherit;transition:all .15s;
}
.pager button:hover{border-color:var(--blue);color:var(--blue)}
.pager button.active{background:var(--blue);border-color:var(--blue);color:#fff;font-weight:700}
.pager button:disabled{opacity:.3;cursor:default}
.pager .pinfo{font-size:10px;color:var(--text3);margin-right:4px}

/* STICKY COLS + STICKY THEAD */
.dtbl{overflow-x:auto}
.dtbl th:nth-child(1),.dtbl td:nth-child(1){position:sticky;left:0;z-index:3;min-width:58px}
.dtbl th:nth-child(2),.dtbl td:nth-child(2){position:sticky;left:58px;z-index:3;min-width:70px}
.dtbl th:nth-child(3),.dtbl td:nth-child(3){position:sticky;left:128px;z-index:3;min-width:60px;border-right:1px solid rgba(0,212,255,.15)}
/* Sticky thead — congela cabeçalho dentro do container de scroll */
.dtbl thead th{
  position:sticky;top:0;z-index:4;
  background:#0A1220;
  border-bottom:1px solid #2A3F58;
}
.dtbl thead th:nth-child(1),.dtbl thead th:nth-child(2),.dtbl thead th:nth-child(3){z-index:5}
.dtbl thead th:nth-child(1),.dtbl thead th:nth-child(2),.dtbl thead th:nth-child(3){z-index:5}
.dtbl tbody td:nth-child(1),.dtbl tbody td:nth-child(2),.dtbl tbody td:nth-child(3){background:#0D1525}
.dtbl tbody tr:hover td:nth-child(1),.dtbl tbody tr:hover td:nth-child(2),.dtbl tbody tr:hover td:nth-child(3){background:#0F1E35}

/* RESPONSIVE */
/* Tela grande (> 1600px): centraliza e limita largura */
@media(min-width:1600px){
  header,.tabs,#active-filters,.tab-panel.active{max-width:1600px;margin-left:auto;margin-right:auto}
  .hero-val{font-size:32px}
}
/* Tablet (< 900px) */
@media(max-width:900px){
  header{padding:8px 12px;min-height:auto;flex-wrap:wrap;gap:8px}
  .hd-sep{display:none}
  .hd-filter-item{font-size:10px;padding:2px 5px;height:26px}
  .tabs{padding:0 10px;overflow-x:auto}
  .tab-panel.active{padding:14px 12px 24px}
  #active-filters{padding:5px 12px 0}
  .ch-wrap{height:200px}
  .ch-wrap-lg{height:240px}
  .ch-wrap-xl{height:260px}
  .hero-val{font-size:24px}
  .kpi-val{font-size:18px}
}
/* Mobile (< 580px) */
@media(max-width:580px){
  header{padding:8px 10px}
  .hd-stamp{display:none}
  .hd-row1{padding:0 10px}
  .hd-row2{padding:0 10px}
  .cat-pills{flex-shrink:0}
  .tab-panel.active{padding:10px 8px 20px;gap:12px}
  #active-filters{padding:4px 8px 0}
  .card{padding:12px}
  .hero-card{padding:14px 12px}
  .hero-val{font-size:22px;letter-spacing:-0.5px}
  .hero-lbl{font-size:9px}
  .kpi-val{font-size:16px}
  .kpi-lbl{font-size:8px}
  .kpi-card{padding:10px 12px}
  .ch-wrap,.ch-wrap-lg,.ch-wrap-xl{height:180px}
  .sr{flex-direction:column;align-items:stretch}
  .sr input{min-width:0}
  /* Desabilita sticky em mobile para melhor UX de scroll horizontal */
  .dtbl th:nth-child(1),.dtbl td:nth-child(1),
  .dtbl th:nth-child(2),.dtbl td:nth-child(2),
  .dtbl th:nth-child(3),.dtbl td:nth-child(3){position:static}
  .dtbl th:nth-child(3),.dtbl td:nth-child(3){border-right:none}
  .tab-badge{display:none}
}

/* FLOATING SCROLL */
#float-hscroll{
  display:none;position:fixed;bottom:0;height:12px;
  overflow-x:auto;overflow-y:hidden;z-index:600;
  background:#0A1220;border-top:1px solid rgba(0,212,255,.15);
  scrollbar-width:thin;scrollbar-color:#1E3A52 #0A1220;
}
#float-hscroll::-webkit-scrollbar{height:6px}
#float-hscroll::-webkit-scrollbar-track{background:#0A1220}
#float-hscroll::-webkit-scrollbar-thumb{background:#1E3A52;border-radius:3px}
#float-hscroll::-webkit-scrollbar-thumb:hover{background:#00D4FF55}
#float-hscroll-inner{height:1px}

/* MULTI-SELECT NAT OP */
.ms-wrap{position:relative}
.ms-btn{
  background:#1C2638;border:1px solid var(--bd2);border-radius:6px;
  padding:4px 8px;color:var(--text);font-size:11px;font-family:inherit;
  cursor:pointer;white-space:nowrap;display:flex;align-items:center;gap:6px;
  transition:border-color .15s;min-width:88px;
}
.ms-btn.open,.ms-btn:focus{border-color:var(--blue2);outline:none}
.ms-arrow{font-size:9px;color:var(--text3);margin-left:auto}
.ms-count{background:var(--blue);color:#fff;border-radius:10px;padding:0 6px;font-size:9px;font-weight:700}
.ms-dropdown{
  display:none;position:fixed;top:0;right:0;
  background:var(--card-bg);border:1px solid var(--bd2);border-radius:10px;
  min-width:270px;max-height:260px;overflow-y:auto;z-index:300;
  box-shadow:0 16px 40px rgba(0,0,0,.7),0 0 20px rgba(0,212,255,.05);padding:6px 0;
}
.ms-dropdown.open{display:block}
.ms-opt{display:flex;align-items:center;gap:9px;padding:6px 14px;cursor:pointer;font-size:12px;transition:background .1s}
.ms-opt:hover{background:rgba(0,212,255,.06)}
.ms-opt input[type=checkbox]{width:13px;height:13px;accent-color:var(--blue);cursor:pointer;flex-shrink:0}
.ms-opt label{cursor:pointer;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--text2)}
.ms-all{border-bottom:1px solid var(--bd);margin-bottom:4px;font-weight:600}
.ms-all label{color:var(--text)}


/* INSIGHTS */
.insights-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
@media(max-width:1100px){.insights-grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:600px){.insights-grid{grid-template-columns:1fr}}
.insight-card{
  background:var(--card-bg);
  border:1px solid var(--bd);border-radius:var(--r);padding:16px;
  display:flex;flex-direction:column;gap:7px;transition:border-color .2s,box-shadow .2s;
}
.insight-card:hover{border-color:var(--bd2);box-shadow:var(--shadow)}
.insight-icon{font-size:18px}
.insight-title{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:var(--text3)}
.insight-body{font-size:12px;color:var(--text2);line-height:1.6}
.insight-body strong{color:var(--text);font-weight:600}
.insight-body .ok{color:var(--green2);font-weight:600}
.insight-body .hi{color:var(--yellow);font-weight:600}
.insight-body .bad{color:var(--red);font-weight:600}

/* WARN */
.warn-box{background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.2);border-radius:var(--r);padding:10px 14px;color:var(--amber);font-size:12px}
.footer{font-size:10px;color:var(--text3);text-align:center;padding:4px 0 6px}

/* SORT */
.sort-th{cursor:pointer;user-select:none}
.sort-th:hover{color:var(--text)!important}
.sort-th.sort-asc::after{content:' ↑';color:var(--blue);font-size:9px;font-weight:900}
.sort-th.sort-desc::after{content:' ↓';color:var(--blue);font-size:9px;font-weight:900}

/* PCT BAR */
.pct-bar-wrap{display:flex;align-items:center;gap:5px;min-width:92px}
.pct-bar-bg{flex:1;height:3px;background:#1C2638;border-radius:2px;min-width:38px}
.pct-bar-fill{height:100%;border-radius:2px}

/* MARKETPLACE */
.mkt-kpi-row{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:4px}
.mkt-card{
  background:rgba(17,24,39,.9);backdrop-filter:blur(8px);
  border:1px solid var(--bd);border-radius:var(--r);padding:16px;
  transition:border-color .2s;position:relative;
}
.mkt-card:hover{border-color:var(--bd2);z-index:100}
.mkt-card:hover .kpi-tooltip{display:block}
.mkt-lbl{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.7px;color:var(--text2);margin-bottom:4px}
.mkt-val{font-size:22px;font-weight:800;color:var(--text);letter-spacing:-.5px}
.mkt-sub{font-size:10px;color:var(--text2);margin-top:2px}

/* CLIENTES */
.conso-banner{
  background:linear-gradient(135deg,rgba(0,212,255,.08),rgba(16,185,129,.06));
  border:1px solid rgba(0,212,255,.15);border-radius:var(--r);
  padding:14px 18px;display:flex;align-items:center;gap:16px;
}
.conso-num{font-size:32px;font-weight:900;color:var(--blue)}
.conso-txt{font-size:12px;color:var(--text2);line-height:1.6}
.conso-txt strong{color:var(--text)}
</style>
</head>
<body>

<header>
  <!-- Linha 1: identidade + categoria -->
  <div class="hd-row1">
    <div class="hd-logo">FR</div>
    <div class="hd-sep"></div>
    <span class="hd-title">Gestão de Fretes</span>
    <div class="hd-sep"></div>
    <div class="cat-pills">
      <div class="cat-pill-wrap" title="Exibe todos os canais sem filtro de categoria">
        <button class="cat-pill active" id="cat_all" onclick="setCategoria('')">Todos</button>
      </div>
      <div class="cat-pill-wrap" title="B2B — distribuidores, revendas e atacado. Exclui os canais Online.">
        <button class="cat-pill" id="cat_b2b" onclick="setCategoria('B2B')">B2B</button>
      </div>
      <div class="cat-pill-wrap" title="Online — AMAZON · ECOMMERCE · ECOMMERCE_TELEVENDAS · MAGALU · MERCADO LIVRE · RAIA DROGASIL · SHOPPE · SITE LINHAHUM · TIKTOSHOP · BELEZA WEB">
        <button class="cat-pill" id="cat_online" onclick="setCategoria('Online')">Online</button>
      </div>
    </div>
    <span class="hd-stamp" id="hd_gen"></span>
    <button id="theme-toggle" title="Alternar tema claro/escuro" onclick="toggleTheme()" style="
      margin-left:8px;background:none;border:1px solid var(--bd2);border-radius:7px;
      color:var(--text2);cursor:pointer;font-size:14px;width:30px;height:30px;
      display:flex;align-items:center;justify-content:center;flex-shrink:0;
      transition:border-color .15s,color .15s;padding:0;
    ">🌙</button>
  </div>
  <!-- Linha 2: filtros (scroll horizontal se necessário) -->
  <div class="hd-row2">
    <select id="filter_ano" class="hd-filter-item"><option value="">Ano</option></select>
    <select id="filter_mes" class="hd-filter-item"><option value="">Mes</option></select>
    <select id="filter_empresa_h" class="hd-filter-item"><option value="">Empresa</option></select>
    <button class="hd-filter-item hd-adv-btn" id="hd_adv_btn" type="button" onclick="toggleAdvFilters()" style="cursor:pointer;font-weight:600">Mais filtros <span id="hd_adv_arrow" style="font-size:9px">▼</span></button>
    <div class="hd-adv hidden" id="hd_adv_wrap">
      <select id="filter_linha_h" class="hd-filter-item">
        <option value="">Linha</option>
        <option value="Linhahum">Linhahum</option>
        <option value="Humana Alimentar">Humana Alimentar</option>
        <option value="Misto">Misto</option>
      </select>
      <div class="ms-wrap" id="ms_natop_wrap">
        <button class="ms-btn" id="ms_natop_btn" type="button" style="height:28px">Nat. Op. <span class="ms-arrow">v</span></button>
        <div class="ms-dropdown" id="ms_natop_drop"></div>
      </div>
      <select id="filter_estado" class="hd-filter-item"><option value="">Estado</option></select>
      <select id="filter_transp" class="hd-filter-item"><option value="">Transportadora</option></select>
      <select id="filter_canal" class="hd-filter-item"><option value="">Canal</option></select>
      <input type="text" id="hd_search" placeholder="Buscar cliente, NF..." class="hd-filter-item" style="width:140px;cursor:text">
    </div>
  </div>
</header>

<div id="active-filters"></div>

<div class="tabs">
  <button class="tab-btn tab-highlight active" data-tab="visao-geral">Visão Geral <span class="tab-badge" id="tb_vinc">-</span></button>
  <button class="tab-btn tab-highlight" data-tab="marketplace">Marketplace <span class="tab-badge" id="tb_mkt">-</span></button>
  <button class="tab-btn tab-highlight" data-tab="compras">Frete Compras <span class="tab-badge" id="tb_comp">-</span></button>
  <button class="tab-btn tab-highlight" data-tab="dev-mkt">Dev. Marketplace <span class="tab-badge" id="tb_devmkt">-</span></button>
  <button class="tab-btn tab-highlight" data-tab="empresa">Por Empresa <span class="tab-badge" id="tb_emp">-</span></button>
  <button class="tab-btn tab-highlight" data-tab="operacional">Operacional <span class="tab-badge" id="tb_op">-</span></button>
  <button class="tab-btn tab-highlight" data-tab="clientes">Consolidação Frete <span class="tab-badge" id="tb_cli">-</span></button>
  <button class="tab-btn tab-highlight" data-tab="nao-vinculados">Cobertura de Dados <span class="tab-badge" id="tb_naov">-</span></button>
</div>

<!-- TAB VISÃO GERAL -->
<div id="tab-visao-geral" class="tab-panel active">

  <div class="hero-grid">
    <div class="hero-card c-blue">
      <div class="kpi-tooltip">Quanto a empresa gastou para pagar transportadoras no período (exceto Shopee e Mercado Livre, que ficam na aba Marketplace). Quanto menor esse valor em relação ao faturamento, mais eficiente é a operação logística.</div>
      <div class="hero-icon ib"><i class="fa-solid fa-coins"></i></div>
      <div class="hero-lbl">Custo Total de Frete</div>
      <div class="hero-val" id="h_total">-</div>
      <div class="hero-sub"><span id="h_pct_fat_chip" class="chip chip-gray">-</span><span style="color:var(--text3)">do faturamento</span></div>
      <div class="hero-sub" id="h_total_vs" style="margin-top:4px;font-size:10px;min-height:18px"></div>
    </div>
    <div class="hero-card c-dynamic">
      <div class="kpi-tooltip">Diferença entre o que a empresa cobrou de frete do cliente na nota fiscal e o que efetivamente pagou a transportadora. Positivo = cliente cobriu o custo. Negativo = empresa arcou com parte do frete (reduz margem).</div>
      <div class="hero-icon ip"><i class="fa-solid fa-scale-balanced"></i></div>
      <div class="hero-lbl">Repasse de Frete ao Cliente</div>
      <div class="hero-val" id="h_saldo">-</div>
      <div class="hero-sub" id="h_saldo_sub">-</div>
      <div class="hero-sub" id="h_saldo_vs" style="margin-top:4px;font-size:10px;min-height:18px"></div>
    </div>
    <div class="hero-card c-green">
      <div class="kpi-tooltip">De cada R$ 100 vendidos, quanto foi gasto com frete. Referência do mercado: acima de 5% é motivo de atenção; acima de 8% indica custo elevado que comprime a margem. Quanto menor, melhor para o resultado da empresa.</div>
      <div class="hero-icon ig"><i class="fa-solid fa-chart-line"></i></div>
      <div class="hero-lbl">% Frete / Receita</div>
      <div class="hero-val" id="h_pct_rec">-</div>
      <div class="hero-sub" id="h_pct_rec_sub">-</div>
      <div class="hero-sub" id="h_pct_vs" style="margin-top:4px;font-size:10px;min-height:18px"></div>
    </div>
    <div class="hero-card c-amber">
      <div class="kpi-tooltip">Custo médio por entrega vinculada a CTe. Calculado dividindo o total de frete pelo número de NF-e com transporte. Útil para comparar eficiência entre períodos e empresas. Referência: valores menores indicam melhor aproveitamento de carga.</div>
      <div class="hero-icon ia"><i class="fa-solid fa-bullseye"></i></div>
      <div class="hero-lbl">Frete Médio por Entrega</div>
      <div class="hero-val" id="h_ticket">-</div>
      <div class="hero-sub" id="h_ticket_sub">-</div>
      <div class="hero-sub" id="h_ticket_vs" style="margin-top:4px;font-size:10px;min-height:18px"></div>
    </div>
  </div>

  <div class="kpi-row">
    <div class="kpi-card">
      <div class="kpi-tooltip">Quantidade de notas fiscais para as quais foi encontrado um documento de transporte (conhecimento de frete) correspondente. Notas sem esse vínculo não entram nos cálculos de custo.</div>
      <div class="kpi-lbl">NF-e Vinculadas</div>
      <div class="kpi-val" id="k_vinc">-</div>
      <div class="kpi-sub" id="k_vinc_sub">-</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-tooltip">Percentual das notas fiscais emitidas que possuem documento de transporte. Quanto mais próximo de 100%, mais completa é a análise de frete. Valores baixos indicam que muitas entregas não estão sendo monitoradas.</div>
      <div class="kpi-lbl">Cobertura de Documentos</div>
      <div class="kpi-val" id="k_cobertura">-</div>
      <div class="kpi-sub">As demais sao retiradas ou ex-works — sem custo de frete para a empresa</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-tooltip">Número de transportadoras diferentes utilizadas no período. Alta diversificação pode indicar falta de padronização; baixa diversificação aumenta o risco de dependência de um único parceiro.</div>
      <div class="kpi-lbl">Transportadoras Ativas</div>
      <div class="kpi-val" id="k_ntransp">-</div>
      <div class="kpi-sub" id="k_ntransp_sub">-</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-tooltip">Percentual do custo de frete concentrado na transportadora mais utilizada. Acima de 70% indica dependência excessiva — qualquer problema com esse parceiro impacta toda a operação logística.</div>
      <div class="kpi-lbl">Concentração Top 1</div>
      <div class="kpi-val" id="k_conc">-</div>
      <div class="kpi-sub" id="k_conc_sub">-</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-tooltip">Quantidade de entregas em que nenhum valor de frete foi cobrado do cliente na nota fiscal. Pode indicar política comercial de frete grátis ou falta de repasse do custo, o que reduz a margem de contribuição.</div>
      <div class="kpi-lbl">Frete Grátis (Entregas)</div>
      <div class="kpi-val" id="k_gratis">-</div>
      <div class="kpi-sub" id="k_gratis_sub">-</div>
    </div>
  </div>

  <div class="card" style="padding:16px 18px">
    <div class="card-title">Frete por Linha de Produto</div>
    <div class="lp-grid">
      <div class="kpi-card lp-card-lh">
        <div class="kpi-tooltip">Valor total pago a transportadoras para entregas de produtos Linhahum. Inclui rateio proporcional quando uma mesma entrega contém produtos das duas linhas.</div>
        <div class="kpi-lbl">Frete Linhahum</div>
        <div class="kpi-val" id="k_lh_frete" style="color:var(--green)">-</div>
        <div class="kpi-sub" id="k_lh_pct">-</div>
      </div>
      <div class="kpi-card lp-card-hu">
        <div class="kpi-tooltip">Valor total pago a transportadoras para entregas de produtos Humana Alimentar. Inclui rateio proporcional quando uma mesma entrega contém produtos das duas linhas.</div>
        <div class="kpi-lbl">Frete Humana Alimentar</div>
        <div class="kpi-val" id="k_hu_frete" style="color:var(--blue2)">-</div>
        <div class="kpi-sub" id="k_hu_pct">-</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-tooltip">Total de vendas (valor das notas fiscais) dos produtos da linha Linhahum no período selecionado.</div>
        <div class="kpi-lbl">Faturamento Linhahum</div><div class="kpi-val" id="k_lh_nf" style="font-size:16px">-</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-tooltip">Total de vendas (valor das notas fiscais) dos produtos da linha Humana Alimentar no período selecionado.</div>
        <div class="kpi-lbl">Faturamento Humana</div><div class="kpi-val" id="k_hu_nf" style="font-size:16px">-</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-tooltip">De cada R$ 100 vendidos de Linhahum, quanto foi gasto com frete. Permite comparar a eficiência logística entre as linhas de produto.</div>
        <div class="kpi-lbl">% Frete/Venda Linhahum</div><div class="kpi-val" id="k_lh_pctvenda" style="font-size:18px">-</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-tooltip">De cada R$ 100 vendidos de Humana Alimentar, quanto foi gasto com frete. Permite comparar a eficiência logística entre as linhas de produto.</div>
        <div class="kpi-lbl">% Frete/Venda Humana</div><div class="kpi-val" id="k_hu_pctvenda" style="font-size:18px">-</div>
      </div>
    </div>
  </div>

  <div id="alerts-row"></div>

  <div class="sdiv">Insights Executivos Automáticos</div>
  <div class="insights-grid" id="insights-grid"></div>

  <div class="sdiv">Evolução Temporal</div>
  <div class="card">
    <div class="card-title">Frete Mensal por Empresa (R$)</div>
    <div class="ch-wrap-xl"><canvas id="ch_timeline"></canvas></div>
  </div>
  <div class="card">
    <div class="card-title">% Frete / Venda por Empresa e Mês</div>
    <div class="ch-wrap-xl"><canvas id="ch_pct_emp_mes"></canvas></div>
  </div>
  <div class="card">
    <div class="card-title">% Frete / Venda — Mapa de Desempenho por Empresa e Mês</div>
    <div style="display:flex;flex-wrap:wrap;gap:10px;margin:-4px 0 16px;padding:12px 14px;background:var(--s2);border-radius:8px;border-left:3px solid var(--bd2)">
      <div style="flex:1;min-width:220px">
        <div style="font-size:10px;font-weight:700;color:var(--text3);letter-spacing:.06em;margin-bottom:6px">COMO CALCULAR</div>
        <div style="font-size:11px;color:var(--text2);line-height:1.7">
          <span style="color:var(--text);font-weight:600">% Frete</span> = Valor total do CTe pago à transportadora ÷ Valor total das NF-e vinculadas × 100<br>
          Exemplo: R$ 1.000 de frete para R$ 50.000 em vendas = <span style="color:#10B981;font-weight:600">2,0%</span>
        </div>
      </div>
      <div style="flex:1;min-width:220px">
        <div style="font-size:10px;font-weight:700;color:var(--text3);letter-spacing:.06em;margin-bottom:6px">O QUE ESTÁ INCLUSO</div>
        <div style="font-size:11px;color:var(--text2);line-height:1.7">
          Apenas NF-e que possuem CTe vinculado pelo cruzamento da chave de 44 dígitos (SEFAZ).<br>
          NF-e sem CTe correspondente <span style="color:#F59E0B;font-weight:600">não entram</span> neste cálculo.
        </div>
      </div>
      <div style="flex:1;min-width:220px">
        <div style="font-size:10px;font-weight:700;color:var(--text3);letter-spacing:.06em;margin-bottom:6px">ESCALA DE COR & MÉDIA</div>
        <div style="font-size:11px;color:var(--text2);line-height:1.7">
          Cores <span style="color:#10B981;font-weight:600">relativas</span> ao período exibido: verde = menor %, vermelho = maior %.<br>
          Coluna <span style="color:var(--text);font-weight:600">Média</span> = frete total ÷ vendas totais do período (ponderado por volume).
        </div>
      </div>
    </div>
    <div id="yoy_heatmap" style="overflow-x:auto;overflow-y:visible"></div>
  </div>

  <div class="sdiv">Distribuição Geográfica &amp; Parceiros Logísticos</div>
  <div class="ch2">
    <div class="card">
      <div class="card-title">Custo de Frete por Estado de Destino - Top 15</div>
      <div class="ch-wrap"><canvas id="ch_estado"></canvas></div>
    </div>
    <div class="card">
      <div class="card-title">Participação por Transportadora - Top 10</div>
      <div class="ch-wrap"><canvas id="ch_transp"></canvas></div>
    </div>
  </div>

  <div class="sdiv">Análise por Empresa</div>
  <div class="card">
    <div class="card-title">Frete por Empresa</div>
    <div class="ch-wrap"><canvas id="ch_empresa"></canvas></div>
  </div>

  <div id="warn_box" style="display:none" class="warn-box">
    <strong id="warn_sem">0</strong> NF-e do faturamento não encontraram CTe correspondente.
  </div>

  <div class="sdiv">Performance por Natureza de Operação</div>
  <div class="card">
    <div class="card-title">Ranking - Natureza de Operação</div>
    <div class="tw">
      <table>
        <thead><tr><th>#</th><th>Natureza de Operação</th><th>Qtd NF-e</th><th>Frete Pago</th><th>Frete Cobrado</th><th>Saldo</th><th>% do Total</th><th>Part.</th></tr></thead>
        <tbody id="natop_tbody"></tbody>
      </table>
    </div>
  </div>

  <div class="footer" id="footer_info"></div>
</div>

<!-- TAB OPERACIONAL -->
<div id="tab-operacional" class="tab-panel">
  <div class="sdiv">Detalhamento Analítico por NF-e</div>
  <div class="card">
    <div class="card-title">Detalhes por NF-e <span style="font-size:10px;color:var(--text3);font-weight:400;margin-left:8px;text-transform:none;letter-spacing:0">Visão operacional completa — auditoria e análise aprofundada</span></div>
    <div class="tw dtbl" id="details_wrap" style="max-height:70vh;overflow-y:auto">
      <table>
        <thead><tr>
          <th>Empresa</th><th>Linha</th><th>NF</th><th>Data</th><th>Canal</th>
          <th class="sort-th" id="th_total_nf" onclick="sortBy('total_nf')">Total NF</th>
          <th class="sort-th" id="th_valor_frete" onclick="sortBy('valor_frete')">Valor Frete</th>
          <th class="sort-th" id="th_pct" onclick="sortBy('pct')">%Fr/Venda</th>
          <th>Linhahum</th><th>Humana</th>
          <th>Fr.Cobrado</th>
          <th class="sort-th" id="th_diferenca" onclick="sortBy('diferenca')">Saldo</th>
          <th>Frete LH</th><th>Frete HU</th>
          <th>Qtd NF/CTe</th>
          <th>Transportadora</th><th>Origem</th><th>Destino</th><th>Peso(kg)</th>
        </tr></thead>
        <tbody id="tbody"></tbody>
      </table>
    </div>
    <div class="pager" id="pager"></div>
  </div>
</div>

<!-- TAB MARKETPLACE -->
<div id="tab-marketplace" class="tab-panel">
  <div class="mkt-kpi-row">
    <div class="mkt-card" style="border-top:3px solid #FF6900">
      <div class="kpi-tooltip">Valor total pago a Shopee (SHPS Tecnologia) para entrega de pedidos desta plataforma no período. O frete Shopee é operado diretamente pela plataforma e debitado via CTe.</div>
      <div class="mkt-lbl">Total Frete Shopee</div>
      <div class="mkt-val" id="mkt_shopee_frete">-</div>
      <div class="mkt-sub" id="mkt_shopee_qtd">-</div>
    </div>
    <div class="mkt-card" style="border-top:3px solid #FFE600">
      <div class="kpi-tooltip">Valor total pago ao Mercado Livre (eBazar) para entrega de pedidos desta plataforma. Frete operado pelo ecossistema Meli e cobrado via CTe próprio.</div>
      <div class="mkt-lbl">Total Frete Mercado Livre</div>
      <div class="mkt-val" id="mkt_ml_frete">-</div>
      <div class="mkt-sub" id="mkt_ml_qtd">-</div>
    </div>
    <div class="mkt-card" style="border-top:3px solid var(--blue2)">
      <div class="kpi-tooltip">Custo médio por pedido entregue via Shopee. Calculado dividindo o frete total pelo número de CTe. Valores crescentes podem indicar revisão na tabela contratada com a plataforma.</div>
      <div class="mkt-lbl">Frete Médio Shopee</div>
      <div class="mkt-val" id="mkt_shopee_med">-</div>
      <div class="mkt-sub">por entrega</div>
    </div>
    <div class="mkt-card" style="border-top:3px solid var(--green2)">
      <div class="kpi-tooltip">Custo médio por pedido entregue via Mercado Livre. Comparar com Shopee para avaliar qual plataforma tem menor custo logístico relativo.</div>
      <div class="mkt-lbl">Frete Médio Mercado Livre</div>
      <div class="mkt-val" id="mkt_ml_med">-</div>
      <div class="mkt-sub">por entrega</div>
    </div>
  </div>
  <div class="card">
    <div class="card-title">Shopee vs Mercado Livre - Frete Mensal</div>
    <div class="ch-wrap-xl"><canvas id="ch_mkt_timeline"></canvas></div>
  </div>
  <div class="card">
    <div class="card-title">Detalhes Marketplace</div>
    <div style="display:flex;gap:6px;align-items:center;margin-bottom:12px">
      <span style="font-size:11px;color:var(--text3);font-weight:600">Exibir:</span>
      <div class="cat-filter">
        <button class="cat-btn active" id="mkt_f_all" onclick="setMktFilter('')">Todos</button>
        <button class="cat-btn" id="mkt_f_shopee" onclick="setMktFilter('SHOPEE')"><i class="fa-solid fa-store"></i> Shopee</button>
        <button class="cat-btn" id="mkt_f_ml" onclick="setMktFilter('MERCADO LIVRE')"><i class="fa-solid fa-tag"></i> Mercado Livre</button>
      </div>
    </div>
    <div class="tw dtbl" id="mkt_wrap">
      <table>
        <thead><tr>
          <th>Empresa</th><th>Linha</th><th>NF</th><th>Data</th><th>Canal</th>
          <th>Total NF</th><th>Valor Frete</th><th>%Fr/Venda</th>
          <th>Linhahum</th><th>Humana</th><th>Fr.Cobrado</th><th>Saldo</th>
          <th>Frete LH</th><th>Frete HU</th><th>Qtd NF/CTe</th>
          <th>Transportadora</th><th>Origem</th><th>Destino</th><th>Peso(kg)</th>
        </tr></thead>
        <tbody id="mkt_tbody"></tbody>
      </table>
    </div>
    <div class="pager" id="mkt_pager"></div>
  </div>
</div>

<!-- TAB CLIENTES -->
<div id="tab-clientes" class="tab-panel">
  <div class="kpi-row" style="grid-template-columns:repeat(3,1fr)">
    <div class="kpi-card">
      <div class="kpi-tooltip">Grupos formados por entregas ao mesmo cliente na mesma semana que poderiam ter sido consolidadas em um único CTe, reduzindo o custo de frete e a complexidade operacional.</div>
      <div class="kpi-lbl">Grupos Consolidáveis</div>
      <div class="kpi-val" id="cli_k_grupos">-</div>
      <div class="kpi-sub">cliente + semana com 2+ entregas</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-tooltip">Soma dos fretes menores dentro de cada grupo de consolidação. Representa o custo que poderia ser eliminado se todas as entregas do mesmo cliente na mesma semana fossem agrupadas em um único CTe.</div>
      <div class="kpi-lbl">Economia Estimada</div>
      <div class="kpi-val" id="cli_k_eco" style="color:var(--green)">-</div>
      <div class="kpi-sub">se todos os grupos forem consolidados</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-tooltip">Total de CTe individuais que poderiam ser eliminados pela consolidação. Menos documentos de frete reduz custo administrativo e fiscal além da redução do frete em si.</div>
      <div class="kpi-lbl">CTe Consolidáveis</div>
      <div class="kpi-val" id="cli_k_ctes">-</div>
      <div class="kpi-sub">documentos de transporte</div>
    </div>
  </div>
  <div class="conso-banner" id="conso_banner">
    <div class="conso-num" id="conso_grupos">-</div>
    <div class="conso-txt" id="conso_txt">Calculando...</div>
  </div>
  <div class="card">
    <div class="card-title">Oportunidades de Consolidação por Cliente e Semana</div>
    <div class="sr" style="margin-bottom:12px">
      <input type="text" id="cli_search" placeholder="Buscar por nome do cliente ou número de NF-e..." style="width:100%;max-width:440px">
    </div>
    <div class="tw">
      <table>
        <thead><tr><th>Cliente</th><th>Empresa</th><th>Semana</th><th>Entregas</th><th>Total Frete</th><th>Destino(s) de Entrega</th><th>Mesmo Destino?</th><th title="Soma dos fretes menores — economia se fossem consolidados na maior entrega">Econ. Potencial <i class="fa-solid fa-circle-info"></i></th><th></th></tr></thead>
        <tbody id="cli_tbody"></tbody>
      </table>
    </div>
    <div class="pager" id="cli_pager"></div>
  </div>
</div>

<!-- TAB CTe NAO VINCULADOS -->
<div id="tab-nao-vinculados" class="tab-panel">
  <div class="kpi-row" style="grid-template-columns:repeat(4,1fr)">
    <div class="kpi-card">
      <div class="kpi-val" id="nv_k_qtd">-</div>
      <div class="kpi-lbl">CTe sem Vínculo</div>
      <div class="kpi-sub">não cruzados com faturamento</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-val" id="nv_k_frete">-</div>
      <div class="kpi-lbl">Frete sem Vínculo</div>
      <div class="kpi-sub">valor total não apurado</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-val" id="nv_k_transp">-</div>
      <div class="kpi-lbl">Transportadoras</div>
      <div class="kpi-sub">distintas envolvidas</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-val" id="nv_k_nferefs">-</div>
      <div class="kpi-lbl">NF-e Referenciadas</div>
      <div class="kpi-sub">não localizadas no ERP</div>
    </div>
  </div>
  <div class="card" style="margin-top:16px">
    <div class="card-title">Documentos de Transporte sem NF-e Correspondente</div>
    <p style="color:var(--text2);font-size:12px;margin:-6px 0 14px">Conhecimentos de Frete (CTe) emitidos cujas Notas Fiscais não foram localizadas no faturamento. Pode indicar CTe de terceiros, períodos distintos ou notas ainda não exportadas do ERP.</p>
    <div class="sr">
      <input type="text" id="nv_search" placeholder="Buscar transportadora, cidade, chave CTe...">
      <select id="nv_uf"><option value="">Todos os destinos</option></select>
      <select id="nv_transp"><option value="">Todas as transportadoras</option></select>
    </div>
    <div class="tw">
      <table>
        <thead><tr><th>Chave CTe</th><th>Data</th><th>Transportadora</th><th>Origem</th><th>Destino</th><th>Valor Frete</th><th>Motivo sem vínculo</th></tr></thead>
        <tbody id="nv_tbody"></tbody>
      </table>
    </div>
    <div class="pager" id="nv_pager"></div>
  </div>

  <!-- CTe Cancelados -->
  <div class="kpi-row" style="grid-template-columns:repeat(3,1fr);margin-top:20px">
    <div class="kpi-card" style="border-top:3px solid var(--red2)">
      <div class="kpi-val" id="cancel_k_qtd" style="color:var(--red2)">-</div>
      <div class="kpi-lbl">CTe Cancelados</div>
      <div class="kpi-sub">excluídos do processamento</div>
    </div>
    <div class="kpi-card" style="border-top:3px solid var(--red2)">
      <div class="kpi-val" id="cancel_k_frete" style="color:var(--red2)">-</div>
      <div class="kpi-lbl">Frete Excluído</div>
      <div class="kpi-sub">valor cancelado não computado</div>
    </div>
    <div class="kpi-card" style="border-top:3px solid var(--red2)">
      <div class="kpi-val" id="cancel_k_transp">-</div>
      <div class="kpi-lbl">Transportadoras</div>
      <div class="kpi-sub">com documentos cancelados</div>
    </div>
  </div>
  <div class="card" style="margin-top:16px;border-left:3px solid var(--red2)">
    <div class="card-title" style="color:var(--red2)"><i class="fa-solid fa-ban"></i> CTe Cancelados — Excluídos do Processamento</div>
    <p style="color:var(--text2);font-size:12px;margin:-6px 0 14px">Conhecimentos de Frete com evento de cancelamento registrado na SEFAZ. Estes documentos foram automaticamente excluídos de todos os cálculos do dashboard.</p>
    <div id="cancel_empty" style="display:none;color:var(--text3);font-size:12px;padding:10px 0"><i class="fa-solid fa-circle-check" style="color:var(--green2)"></i> Nenhum CTe cancelado encontrado na pasta de eventos.</div>
    <div id="cancel_list_wrap" class="tw">
      <table>
        <thead><tr><th>Chave CTe (44 dígitos)</th><th>Transportadora</th><th>Valor Frete</th><th style="text-align:center">Ação</th></tr></thead>
        <tbody id="cancel_tbody"></tbody>
      </table>
    </div>
  </div>
</div>

<!-- TAB POR EMPRESA -->
<!-- TAB COMPRAS -->
<div id="tab-compras" class="tab-panel">
  <div class="sdiv">Frete de Entrada — Custo Logístico nas Compras</div>
  <div class="kpi-row" style="grid-template-columns:repeat(4,1fr)">
    <div class="kpi-card">
      <div class="kpi-val" id="comp_qtd">-</div>
      <div class="kpi-lbl">CTe de Compra</div>
      <div class="kpi-sub">documentos processados</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-val" id="comp_frete">-</div>
      <div class="kpi-lbl">Frete Total Compras</div>
      <div class="kpi-sub">pago à transportadora</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-val" id="comp_peso">-</div>
      <div class="kpi-lbl">Peso Total</div>
      <div class="kpi-sub">kg transportados</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-val" id="comp_frete_medio">-</div>
      <div class="kpi-lbl">Frete Médio</div>
      <div class="kpi-sub">por CTe</div>
    </div>
  </div>
  <div class="card">
    <div class="card-title">Detalhamento por CTe de Compra</div>
    <p style="color:var(--text3);font-size:11px;margin:-6px 0 12px">Conhecimentos de Frete cujo destinatário é uma empresa do grupo Humana e a NF-e não consta no faturamento de saída — caracterizando frete de entrada (compras). Filtre por empresa e período no cabeçalho.</p>
    <div class="sr">
      <input type="text" id="comp_search" placeholder="Buscar fornecedor, origem, transportadora, NF-e...">
      <select id="comp_sel_emp"><option value="">Todas as empresas</option></select>
    </div>
    <div style="overflow-x:auto;margin-top:10px" id="comp_wrap">
      <table id="comp_table" style="width:100%;border-collapse:collapse;font-size:11px">
        <thead>
          <tr style="border-bottom:1px solid var(--bd)">
            <th style="padding:8px 10px;text-align:left;color:var(--text3);font-weight:600;white-space:nowrap">Data</th>
            <th style="padding:8px 10px;text-align:left;color:#475569;font-weight:600;white-space:nowrap">Fornecedor (Remetente)</th>
            <th style="padding:8px 10px;text-align:left;color:#475569;font-weight:600;white-space:nowrap">Origem</th>
            <th style="padding:8px 10px;text-align:left;color:#475569;font-weight:600;white-space:nowrap">Destino</th>
            <th style="padding:8px 10px;text-align:left;color:#475569;font-weight:600;white-space:nowrap">Empresa</th>
            <th style="padding:8px 10px;text-align:left;color:#475569;font-weight:600;white-space:nowrap">Transportadora</th>
            <th style="padding:8px 10px;text-align:left;color:#475569;font-weight:600;white-space:nowrap">NF-e(s)</th>
            <th style="padding:8px 10px;text-align:right;color:#475569;font-weight:600;white-space:nowrap">Valor Frete</th>
            <th style="padding:8px 10px;text-align:right;color:#475569;font-weight:600;white-space:nowrap">Peso (kg)</th>
            <th style="padding:8px 10px;text-align:right;color:#475569;font-weight:600;white-space:nowrap">Vol. (m³)</th>
          </tr>
        </thead>
        <tbody id="comp_tbody"></tbody>
      </table>
    </div>
    <div id="comp_pager" style="margin-top:10px"></div>
  </div>
</div>

<!-- TAB DEVOLUÇÃO MARKETPLACE -->
<div id="tab-dev-mkt" class="tab-panel">
  <div class="sdiv">Devolução Marketplace — Retorno de Pedidos via Transportadora da Plataforma</div>

  <!-- KPIs ML -->
  <div style="font-size:10px;font-weight:700;letter-spacing:.08em;color:#FFE600;margin-bottom:6px;padding-left:2px">MERCADO LIVRE</div>
  <div class="kpi-row" style="grid-template-columns:repeat(4,1fr)">
    <div class="kpi-card">
      <div class="kpi-val" id="dm_ml_qtd">-</div>
      <div class="kpi-lbl">CTe Devoluções ML</div>
      <div class="kpi-sub">documentos processados</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-val" id="dm_ml_frete">-</div>
      <div class="kpi-lbl">Frete Total ML</div>
      <div class="kpi-sub">pago à EBAZARCOMBR</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-val" id="dm_ml_peso">-</div>
      <div class="kpi-lbl">Peso Total ML</div>
      <div class="kpi-sub">kg devolvidos</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-val" id="dm_ml_medio">-</div>
      <div class="kpi-lbl">Frete Médio ML</div>
      <div class="kpi-sub">por CTe</div>
    </div>
  </div>

  <!-- KPIs Shopee -->
  <div style="font-size:10px;font-weight:700;letter-spacing:.08em;color:#FF6900;margin-bottom:6px;padding-left:2px">SHOPEE</div>
  <div class="kpi-row" style="grid-template-columns:repeat(4,1fr)">
    <div class="kpi-card">
      <div class="kpi-val" id="dm_sh_qtd">-</div>
      <div class="kpi-lbl">CTe Devoluções Shopee</div>
      <div class="kpi-sub">documentos processados</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-val" id="dm_sh_frete">-</div>
      <div class="kpi-lbl">Frete Total Shopee</div>
      <div class="kpi-sub">pago à SHPS</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-val" id="dm_sh_peso">-</div>
      <div class="kpi-lbl">Peso Total Shopee</div>
      <div class="kpi-sub">kg devolvidos</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-val" id="dm_sh_medio">-</div>
      <div class="kpi-lbl">Frete Médio Shopee</div>
      <div class="kpi-sub">por CTe</div>
    </div>
  </div>

  <!-- Tabela -->
  <div class="card">
    <div class="card-title">Detalhamento por CTe de Devolução</div>
    <p style="color:var(--text3);font-size:11px;margin:-6px 0 12px">CTe emitidos pelas plataformas Mercado Livre e Shopee para retorno de mercadoria ao grupo Humana. Indica devoluções de clientes cujo frete de retorno é arcado pelo grupo.</p>
    <div class="sr">
      <input type="text" id="dm_search" placeholder="Buscar remetente, origem, empresa, NF-e...">
      <select id="dm_sel_plat">
        <option value="">Todas as plataformas</option>
        <option value="ml">Mercado Livre</option>
        <option value="shopee">Shopee</option>
      </select>
      <select id="dm_sel_emp"><option value="">Todas as empresas</option></select>
    </div>
    <div style="overflow-x:auto;margin-top:10px">
      <table style="width:100%;border-collapse:collapse;font-size:11px">
        <thead>
          <tr style="border-bottom:1px solid var(--bd)">
            <th style="padding:8px 10px;text-align:left;color:var(--text3);font-weight:600;white-space:nowrap">Plataforma</th>
            <th style="padding:8px 10px;text-align:left;color:var(--text3);font-weight:600;white-space:nowrap">Data</th>
            <th style="padding:8px 10px;text-align:left;color:var(--text3);font-weight:600;white-space:nowrap">Remetente (Origem)</th>
            <th style="padding:8px 10px;text-align:left;color:#475569;font-weight:600;white-space:nowrap">Destino</th>
            <th style="padding:8px 10px;text-align:left;color:#475569;font-weight:600;white-space:nowrap">Empresa</th>
            <th style="padding:8px 10px;text-align:left;color:#475569;font-weight:600;white-space:nowrap">NF-e(s)</th>
            <th style="padding:8px 10px;text-align:right;color:#475569;font-weight:600;white-space:nowrap">Valor Frete</th>
            <th style="padding:8px 10px;text-align:right;color:#475569;font-weight:600;white-space:nowrap">Peso (kg)</th>
            <th style="padding:8px 10px;text-align:right;color:#475569;font-weight:600;white-space:nowrap">Vol. (m³)</th>
          </tr>
        </thead>
        <tbody id="dm_tbody"></tbody>
      </table>
    </div>
    <div id="dm_pager" style="margin-top:10px"></div>
  </div>
</div>

<div id="tab-empresa" class="tab-panel">
  <div id="emp_periodo_banner" style="margin-bottom:14px;padding:8px 16px;background:rgba(59,130,246,.07);border:1px solid rgba(59,130,246,.18);border-radius:8px;font-size:12px;color:var(--text2);display:flex;align-items:center;gap:8px">
    <i class="fa-solid fa-calendar-days" style="color:var(--blue2);opacity:.8"></i>
    <span id="emp_periodo_txt">Carregando...</span>
  </div>
  <div class="kpi-row" style="grid-template-columns:repeat(3,1fr)">
    <div class="kpi-card">
      <div class="kpi-tooltip">Quantidade de filiais ou CNPJs distintos com movimentações de frete no período. Permite dimensionar a abrangência da análise e identificar se todas as unidades estão sendo monitoradas.</div>
      <div class="kpi-lbl">Empresas Analisadas</div>
      <div class="kpi-val" id="emp_k_qtd">-</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-tooltip">Filial que mais gastou com frete no período selecionado. Indica onde concentrar esforços de negociação e otimização de rotas para maior impacto no resultado.</div>
      <div class="kpi-lbl">Maior Gasto em Frete</div>
      <div class="kpi-val" id="emp_k_top_emp" style="font-size:18px">-</div>
      <div class="kpi-sub" id="emp_k_top_val"></div>
    </div>
    <div class="kpi-card">
      <div class="kpi-tooltip">Transportadora responsável pelo maior volume de frete consolidando todas as empresas do grupo. Sinaliza o principal parceiro logístico e onde uma renegociação teria maior impacto financeiro.</div>
      <div class="kpi-lbl">Principal Transportadora</div>
      <div class="kpi-val" id="emp_k_top_transp" style="font-size:13px;line-height:1.3">-</div>
      <div class="kpi-sub" id="emp_k_top_transp_pct"></div>
    </div>
  </div>
  <div class="ch2eq">
    <div class="card"><div class="card-title">Frete Total por Empresa</div><div class="ch-wrap"><canvas id="ch_emp_frete"></canvas></div></div>
    <div class="card"><div class="card-title">Concentração Transportadora x Empresa (Top 5)</div><div class="ch-wrap-lg"><canvas id="ch_emp_stacked"></canvas></div></div>
  </div>
  <div class="card">
    <div class="card-title">Resumo por Empresa</div>
    <div class="tw"><table>
      <thead><tr><th>#</th><th>Empresa</th><th>NF-e</th><th>Total Frete</th><th>% do Total</th><th>Transp. Principal</th><th>Frete Transp.</th><th>Concentração</th><th>N Transp.</th></tr></thead>
      <tbody id="emp_tbody"></tbody>
    </table></div>
  </div>
  <div class="card">
    <div class="card-title">Top 5 Transportadoras por Empresa</div>
    <div class="tw"><table>
      <thead><tr><th>Empresa</th><th>Transportadora</th><th>NF-e</th><th>Frete Pago</th><th>% da Empresa</th><th>% do Total</th></tr></thead>
      <tbody id="emp_det_tbody"></tbody>
    </table></div>
  </div>

  <div class="sdiv" style="margin-top:4px">Frete entre Empresas (Operacional x Comercial)</div>
  <div class="kpi-row" style="grid-template-columns:repeat(4,1fr)">
    <div class="kpi-card">
      <div class="kpi-tooltip">Frete pago em entregas de venda para clientes externos. Exclui transferências entre unidades do grupo.</div>
      <div class="kpi-lbl">Frete Comercial (Vendas)</div>
      <div class="kpi-val" id="emp_frete_com" style="color:var(--blue2)">-</div>
      <div class="kpi-sub" id="emp_frete_com_sub">-</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-tooltip">Frete pago em transferências entre unidades da própria empresa. Representa custo logístico interno.</div>
      <div class="kpi-lbl">Frete Operacional (Transf.)</div>
      <div class="kpi-val" id="emp_frete_op" style="color:var(--purple)">-</div>
      <div class="kpi-sub" id="emp_frete_op_sub">-</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-tooltip">Quantidade de NF-e de transferência entre unidades no período. O valor em destaque são as NF-e com CTe vinculado (custo de frete registrado); o total do faturamento inclui também as transferências sem CTe (frete próprio ou sem custo registrado).</div>
      <div class="kpi-lbl">NF-e Transferidas</div>
      <div class="kpi-val" id="emp_qtd_transf">-</div>
      <div class="kpi-sub" id="emp_qtd_transf_sub" style="line-height:1.6">NF-e únicas com CTe</div>
      <div class="kpi-sub" id="emp_qtd_transf_fat" style="color:var(--text3);font-size:10px">- NF-e únicas no faturamento</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-tooltip">Percentual do frete total que é representado por movimentações internas entre unidades.</div>
      <div class="kpi-lbl">% Frete Operacional</div>
      <div class="kpi-val" id="emp_pct_op">-</div>
      <div class="kpi-sub">do frete total</div>
    </div>
  </div>
  <div id="emp_transf_destinos_wrap" style="margin:2px 0 10px;font-size:11px;display:flex;align-items:center;gap:6px;flex-wrap:wrap">
    <span style="color:var(--text3)" id="emp_transf_destinos_lbl">Destinos com CTe:</span>
    <span id="emp_transf_destinos" style="display:flex;gap:4px;flex-wrap:wrap">—</span>
  </div>
  <div class="ch2eq">
    <div class="card">
      <div class="card-title">Frete Comercial vs Operacional por Empresa</div>
      <div class="ch-wrap-lg"><canvas id="ch_emp_tipo"></canvas></div>
    </div>
    <div class="card">
      <div class="card-title">Custo Operacional por Empresa (Transferências)</div>
      <p style="color:var(--text3);font-size:11px;margin:-6px 0 10px">Frete pago em transferências internas — identifica quais empresas têm maior custo logístico operacional</p>
      <div class="tw"><table>
        <thead><tr><th>Empresa</th><th>NF Transferidas</th><th>Frete Operacional</th><th>% do Frete Total</th><th>UF Destino Principal</th><th>Ticket Médio</th></tr></thead>
        <tbody id="emp_transf_tbody"></tbody>
      </table></div>
    </div>
  </div>

  <div class="sdiv" style="margin-top:4px">Transferências entre Lojas do Grupo</div>
  <div class="kpi-row" style="grid-template-columns:repeat(3,1fr)">
    <div class="kpi-card">
      <div class="kpi-tooltip">NF-e emitidas tendo como destinatário uma empresa do grupo Humana Alimentar. Representam movimentação interna de estoque entre lojas — excluídas da aba Consolidação de Frete para não distorcer o custo comercial.</div>
      <div class="kpi-lbl">NF-e Internas (entre Lojas)</div>
      <div class="kpi-val" id="emp_hu_qtd" style="color:var(--amber)">-</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-tooltip">Frete total pago para movimentação de estoque entre lojas do grupo. Custo estrutural de distribuição interna — distinto do frete comercial (vendas a clientes externos).</div>
      <div class="kpi-lbl">Frete entre Lojas</div>
      <div class="kpi-val" id="emp_hu_frete" style="color:var(--amber)">-</div>
      <div class="kpi-sub" id="emp_hu_pct">do frete total</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-tooltip">Valor médio de frete por NF-e de transferência interna. Comparar com o ticket médio geral ajuda a avaliar se o custo de distribuição entre lojas é proporcional.</div>
      <div class="kpi-lbl">Ticket Médio Interno</div>
      <div class="kpi-val" id="emp_hu_ticket" style="font-size:18px">-</div>
    </div>
  </div>
  <div class="card">
    <div class="card-title">Detalhe por Empresa Origem × Loja Destino</div>
    <div class="tw"><table>
      <thead><tr><th>Empresa Origem</th><th>Loja Destino</th><th>NF-e</th><th>Frete Total</th><th>% da Empresa</th><th>UF</th><th>Ticket Médio</th></tr></thead>
      <tbody id="emp_hu_tbody"></tbody>
    </table></div>
  </div>

  <div class="sdiv" style="margin-top:4px">NF-e de Transferência Sem CTe Vinculado</div>
  <div class="card">
    <p style="color:var(--text3);font-size:11px;margin:-6px 0 10px">Transferências identificadas no faturamento que não possuem CTe de frete — mercadoria retirada pelo destinatário ou frete próprio sem CTe emitido.</p>
    <div class="tw"><table>
      <thead><tr><th>NF-e</th><th>Data</th><th>Empresa</th><th>Destinatário</th><th>Cidade/UF</th><th>Nat. Operação</th><th style="text-align:right">Valor NF</th></tr></thead>
      <tbody id="emp_transf_sem_cte_tbody"></tbody>
    </table></div>
  </div>

  <div class="sdiv" style="margin-top:4px">Evolução Mensal por Transportadora</div>
  <div class="card">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px">
      <div class="card-title" style="margin:0">Frete por Transportadora ao Longo do Tempo</div>
      <select id="emp_tl_emp" onchange="buildEmpTimeline()" style="background:#1E293B;border:1px solid var(--bd);color:var(--text);border-radius:6px;padding:3px 10px;font-size:11px;cursor:pointer">
        <option value="">Todas as empresas</option>
      </select>
    </div>
    <p style="color:var(--text3);font-size:11px;margin:0 0 10px">Composição mensal de frete pelas top 5 transportadoras — mostra mudanças de mix e qual transportadora dominou cada período</p>
    <div class="ch-wrap-xl"><canvas id="ch_emp_tl"></canvas></div>
  </div>
</div>

<div id="float-hscroll"><div id="float-hscroll-inner"></div></div>

<script>
const DATA = __DATA__;

const BRL  = v => v.toLocaleString('pt-BR',{style:'currency',currency:'BRL'});
const N    = (v,d=0) => v.toLocaleString('pt-BR',{maximumFractionDigits:d});
const MESES= ['','Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez'];
const TR_ALIAS={
  'SHPS TECNOLOGIA E SERVIÇO LTDA':'SHOPEE',
  'SHPS TECNOLOGIA E SERVICO LTDA':'SHOPEE',
  'EBAZARCOMBR LTDA':'MERCADO LIVRE',
};
const MARKETPLACE_TR=new Set(['SHPS TECNOLOGIA E SERVIÇO LTDA','SHPS TECNOLOGIA E SERVICO LTDA','EBAZARCOMBR LTDA']);
function trName(raw){
  if(!raw||raw==='-') return raw||'-';
  const clean=raw.replace(/^.*? - /,'').trim();
  return TR_ALIAS[clean.toUpperCase()]||clean;
}
function isMarketplace(tr){
  if(!tr) return false;
  const clean=tr.replace(/^.*? - /,'').trim().toUpperCase();
  if(MARKETPLACE_TR.has(clean)) return true;
  // Fallback para variações de grafia/encoding no XML
  if(clean.includes('SHPS TECNOLOGIA')) return true;
  if(clean.includes('EBAZARCOMBR')) return true;
  return false;
}
// Normaliza canal: uppercase + remove underscores e espaços para comparação robusta
// Ex: 'SITE_LINHAHUM' == 'SITE LINHAHUM', 'ECOMMERCE_TELEVENDAS' == 'ECOMMERCE TELEVENDAS'
function normCh(s){ return (s||'').toUpperCase().replace(/[\s_\-]+/g,''); }
const ONLINE_CH_RAW=['AMAZON','ECOMMERCE','ECOMMERCETELEVENDAS','MAGALU','MERCADOLIVRE',
  'RAIADROGASIL','SHOPPE','SHOPEE','SITELINHAHUM','TIKTOSHOP','TIKTOKSHOP','BELEZAWEB','BELEZANAWEB'];
const ONLINE_CH_NORM=new Set(ONLINE_CH_RAW);
// Mantém ONLINE_CH original para compatibilidade com buildCanalOptions
const ONLINE_CH=new Set(['AMAZON','ECOMMERCE','ECOMMERCE_TELEVENDAS','MAGALU','MERCADO LIVRE','RAIA DROGASIL','SHOPPE','SHOPEE','SITE LINHAHUM','SITE_LINHAHUM','TIKTOSHOP','TIKTOK SHOP','BELEZA WEB','BELEZAWEB']);
function isOnlineCh(c){ return ONLINE_CH_NORM.has(normCh(c)); }
function getCategoria(canal){ return isOnlineCh(canal)?'Online':'B2B'; }

const dataMes = d => (d.data||'').slice(3,5);
const dataAno = d => (d.data||'').slice(6,10);
const per  = d => d ? d.substring(3,10) : '';
const perL = p => { const [m,y]=p.split('/'); return MESES[+m]+'/'+y; };

function getWeek(dateStr){
  if(!dateStr) return '';
  const parts=dateStr.split('/');
  if(parts.length<3) return '';
  const d=new Date(+parts[2],+parts[1]-1,+parts[0]);
  const jan1=new Date(d.getFullYear(),0,1);
  const wk=Math.ceil(((d-jan1)/86400000+jan1.getDay()+1)/7);
  return d.getFullYear()+'-W'+String(wk).padStart(2,'0');
}

Chart.defaults.color       = '#E2E8F0';
Chart.defaults.borderColor = 'rgba(255,255,255,.05)';
Chart.defaults.font.family = "'Inter','Segoe UI',system-ui,sans-serif";
const COLORS=['#3B82F6','#10B981','#F59E0B','#EF4444','#7C3AED','#34D399','#FCD34D','#F87171','#A78BFA','#60A5FA','#6EE7B7','#FBBF24','#22D3EE','#FB7185','#C4B5FD'];
const CR={};

const hasChart=()=>typeof Chart!=='undefined';
function mkBar(id,lbs,vals,color,lbl){
  if(!hasChart())return;try{
  if(CR[id]) CR[id].destroy();
  CR[id]=new Chart(document.getElementById(id),{type:'bar',
    data:{labels:lbs,datasets:[{label:lbl||'Frete',data:vals,backgroundColor:color||'#2563EB',borderRadius:5,borderSkipped:false}]},
    options:{responsive:true,maintainAspectRatio:false,
      plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>' '+BRL(c.raw)}}},
      scales:{x:{grid:{display:false},ticks:{font:{size:10},color:'#E2E8F0'}},
              y:{grid:{color:'rgba(255,255,255,.04)'},ticks:{callback:v=>BRL(v),font:{size:10},color:'#E2E8F0'}}}}});
  }catch(e){}}
function mkMultiBar(id,lbs,vals,colors){
  if(!hasChart())return;try{
  if(CR[id]) CR[id].destroy();
  CR[id]=new Chart(document.getElementById(id),{type:'bar',
    data:{labels:lbs,datasets:[{label:'Frete',data:vals,backgroundColor:colors,borderRadius:5,borderSkipped:false}]},
    options:{responsive:true,maintainAspectRatio:false,
      plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>' '+BRL(c.raw)}}},
      scales:{x:{grid:{display:false},ticks:{font:{size:10},color:'#E2E8F0'}},
              y:{grid:{color:'rgba(255,255,255,.04)'},ticks:{callback:v=>BRL(v),font:{size:10},color:'#E2E8F0'}}}}});
  }catch(e){}}
function mkDonut(id,lbs,vals){
  if(!hasChart())return;try{
  if(CR[id]) CR[id].destroy();
  CR[id]=new Chart(document.getElementById(id),{type:'doughnut',
    data:{labels:lbs,datasets:[{data:vals,backgroundColor:COLORS,borderWidth:2,borderColor:'#fff',hoverOffset:6}]},
    options:{responsive:true,maintainAspectRatio:false,cutout:'64%',
      plugins:{legend:{position:'right',labels:{font:{size:10},boxWidth:9,padding:10,color:'#E2E8F0'}},
        tooltip:{callbacks:{label:c=>{const t=c.dataset.data.reduce((a,b)=>a+b,0);
          return ' '+c.label+': '+BRL(c.raw)+' ('+(c.raw/t*100).toFixed(1)+'%)';}}}}}});
  }catch(e){}}
function mkGrouped(id,lbs,ds){
  if(!hasChart())return;try{
  if(CR[id]) CR[id].destroy();
  CR[id]=new Chart(document.getElementById(id),{type:'bar',data:{labels:lbs,datasets:ds},
    options:{responsive:true,maintainAspectRatio:false,
      plugins:{legend:{position:'top',labels:{font:{size:10},boxWidth:9,color:'#E2E8F0'}},
        tooltip:{callbacks:{label:c=>' '+c.dataset.label+': '+BRL(c.raw)}}},
      scales:{x:{grid:{display:false},ticks:{font:{size:10},color:'#E2E8F0'}},
              y:{grid:{color:'rgba(255,255,255,.04)'},ticks:{callback:v=>BRL(v),font:{size:10},color:'#E2E8F0'}}}}});
  }catch(e){}}
function mkStacked(id,lbs,ds){
  if(!hasChart())return;try{
  if(CR[id]) CR[id].destroy();
  CR[id]=new Chart(document.getElementById(id),{type:'bar',data:{labels:lbs,datasets:ds},
    options:{responsive:true,maintainAspectRatio:false,
      plugins:{legend:{position:'bottom',labels:{font:{size:10},boxWidth:9,color:'#E2E8F0'}},
        tooltip:{callbacks:{label:c=>' '+c.dataset.label+': '+BRL(c.raw)}}},
      scales:{x:{stacked:true,grid:{display:false},ticks:{font:{size:10},color:'#E2E8F0'}},
              y:{stacked:true,grid:{color:'rgba(255,255,255,.04)'},ticks:{callback:v=>BRL(v),font:{size:10},color:'#E2E8F0'}}}}});
  }catch(e){}}
function mkLine(id,lbs,ds){
  if(!hasChart())return;try{
  if(CR[id]) CR[id].destroy();
  CR[id]=new Chart(document.getElementById(id),{type:'line',data:{labels:lbs,datasets:ds},
    options:{responsive:true,maintainAspectRatio:false,
      interaction:{mode:'index',intersect:false},
      plugins:{
        legend:{position:'top',labels:{font:{size:10},boxWidth:9,padding:16,color:'#E2E8F0',usePointStyle:true,pointStyle:'circle'}},
        tooltip:{callbacks:{label:c=>' '+c.dataset.label+': '+BRL(c.raw)},
          backgroundColor:'#1E293B',borderColor:'#334155',borderWidth:1,
          titleColor:'#F8FAFC',bodyColor:'#94A3B8',padding:12,boxPadding:4}},
      scales:{
        x:{grid:{display:false},ticks:{font:{size:10},color:'#E2E8F0'}},
        y:{grid:{color:'rgba(255,255,255,.04)'},ticks:{callback:v=>BRL(v),font:{size:10},color:'#E2E8F0'}}}}});
  }catch(e){}}
function mkLinePct(id,lbs,ds){
  if(!hasChart())return;try{
  if(CR[id]) CR[id].destroy();
  CR[id]=new Chart(document.getElementById(id),{type:'line',data:{labels:lbs,datasets:ds},
    options:{responsive:true,maintainAspectRatio:false,
      interaction:{mode:'index',intersect:false},
      plugins:{
        legend:{position:'top',labels:{font:{size:10},boxWidth:9,padding:16,color:'#E2E8F0',usePointStyle:true,pointStyle:'circle'}},
        tooltip:{callbacks:{label:c=>' '+c.dataset.label+': '+c.raw.toFixed(2)+'%'},
          backgroundColor:'#1E293B',borderColor:'#334155',borderWidth:1,
          titleColor:'#F8FAFC',bodyColor:'#94A3B8',padding:12,boxPadding:4}},
      scales:{
        x:{grid:{display:false},ticks:{font:{size:10},color:'#E2E8F0'}},
        y:{grid:{color:'rgba(255,255,255,.04)'},ticks:{callback:v=>v.toFixed(1)+'%',font:{size:10},color:'#E2E8F0'}}}}});
  }catch(e){}}
// Heatmap % Frete/Venda
function renderYoY(){
  const d=window._yoyData;if(!d) return;
  const {allEmps,byYME,allPers,tlLbs}=d;
  const container=document.getElementById('yoy_heatmap');if(!container) return;

  // Coleta todos os valores para escala de cores relativa
  const allVals=[];
  allEmps.forEach(emp=>{
    allPers.forEach(p=>{
      const ano=p.slice(3,7),mes=p.slice(0,2);
      const v=byYME[ano+'|'+emp]&&byYME[ano+'|'+emp][mes];
      if(v&&v.nf) allVals.push(v.fr/v.nf*100);
    });
  });
  const vMin=allVals.length?Math.min(...allVals):0;
  const vMax=allVals.length?Math.max(...allVals):5;

  function cellBg(val){
    if(val===null) return '#0A1628';
    const t=vMax===vMin?0.5:(val-vMin)/(vMax-vMin);
    const hue=Math.round(142-142*t); // 142=verde → 0=vermelho
    return`hsl(${hue},55%,18%)`;
  }
  function cellFg(val){
    if(val===null) return '#334155';
    const t=vMax===vMin?0.5:(val-vMin)/(vMax-vMin);
    const hue=Math.round(142-142*t);
    return`hsl(${hue},80%,62%)`;
  }

  const thBase='padding:6px 10px;font-size:9px;font-weight:600;color:var(--text3);white-space:nowrap;text-align:center;border-bottom:1px solid var(--bd)';
  const stickyBase='position:sticky;left:0;z-index:2;background:var(--sticky-bg)';

  let html='<table style="border-collapse:separate;border-spacing:2px;min-width:100%">';

  // Cabeçalho
  html+=`<thead><tr>
    <th style="${thBase};text-align:left;${stickyBase}">Empresa</th>`;
  allPers.forEach((p,i)=>{
    const lbl=tlLbs[i];
    const isJan=p.startsWith('01');
    html+=`<th style="${thBase}${isJan?';border-left:2px solid var(--bd2);color:var(--text3)':''}">${lbl}</th>`;
  });
  html+=`<th style="${thBase};border-left:2px solid var(--bd2);color:var(--text3)">Média</th>`;
  html+='</tr></thead><tbody>';

  // Linhas por empresa
  allEmps.forEach(emp=>{
    let totFr=0,totNf=0;
    const cells=allPers.map(p=>{
      const ano=p.slice(3,7),mes=p.slice(0,2);
      const v=byYME[ano+'|'+emp]&&byYME[ano+'|'+emp][mes];
      const val=v&&v.nf?v.fr/v.nf*100:null;
      if(val!==null){totFr+=v.fr;totNf+=v.nf;}
      return{val,isJan:p.startsWith('01')};
    });
    const avg=totNf?totFr/totNf*100:null;
    html+=`<tr><td style="padding:5px 12px;font-size:11px;font-weight:700;color:var(--text);white-space:nowrap;${stickyBase}">${emp}</td>`;
    cells.forEach(({val,isJan})=>{
      const bg=cellBg(val),fg=cellFg(val);
      const txt=val!==null?val.toFixed(1)+'%':'—';
      html+=`<td style="text-align:center;padding:5px 8px;background:${bg};color:${fg};border-radius:4px;font-size:10px;font-weight:700;white-space:nowrap${isJan?';border-left:2px solid #1E3A5F':''}">${txt}</td>`;
    });
    const avgBg=cellBg(avg),avgFg=cellFg(avg);
    html+=`<td style="text-align:center;padding:5px 10px;background:${avgBg};color:${avgFg};border-radius:4px;font-size:10px;font-weight:800;white-space:nowrap;border-left:2px solid #1E3A5F">${avg!==null?avg.toFixed(1)+'%':'—'}</td>`;
    html+='</tr>';
  });

  html+='</tbody></table>';

  // Legenda escala de cores
  html+=`<div style="display:flex;align-items:center;gap:10px;margin-top:12px;font-size:10px;color:var(--text3)">
    <span>Escala:</span>
    <div style="width:160px;height:8px;border-radius:4px;background:linear-gradient(to right,hsl(142,55%,35%),hsl(71,55%,28%),hsl(0,55%,30%))"></div>
    <span style="color:#10B981">${vMin.toFixed(1)}% (mínimo)</span>
    <span>→</span>
    <span style="color:#EF4444">${vMax.toFixed(1)}% (máximo)</span>
  </div>`;

  container.innerHTML=html;
}
// STATE
const state={ano:'',mes:'',empresa:'',linha:'',natop:[],estado:'',transp:'',canal:'',q:'',categoria:''};
const selAno =document.getElementById('filter_ano');
const selMes =document.getElementById('filter_mes');
const selEmpH=document.getElementById('filter_empresa_h');
const selLnH =document.getElementById('filter_linha_h');
const selEst =document.getElementById('filter_estado');
const selTr  =document.getElementById('filter_transp');
const selCn  =document.getElementById('filter_canal');
const inpQ   =document.getElementById('hd_search');

// Todos os canais únicos (excl. marketplace) pré-calculados
const ALL_CANAIS=[...new Set(DATA.detalhes.filter(d=>!d.is_marketplace).map(d=>d.canal).filter(Boolean))].sort();
// isOnlineCh já definida acima com normalização robusta (remove _/espaços)
function buildCanalOptions(cat){
  const prev=state.canal;
  selCn.innerHTML='';
  let list,label;
  if(cat==='Online'){
    list=ALL_CANAIS.filter(isOnlineCh);
    label='Canais Online ('+list.length+')';
  } else if(cat==='B2B'){
    list=ALL_CANAIS.filter(c=>!isOnlineCh(c));
    label='Canais B2B ('+list.length+')';
  } else {
    list=ALL_CANAIS;
    label='Canal ('+list.length+')';
  }
  // Opção-cabeçalho mostra quantos canais estão disponíveis
  const def=document.createElement('option');
  def.value='';def.textContent=label;selCn.appendChild(def);
  list.forEach(c=>{
    const o=document.createElement('option');
    o.value=c;o.textContent=c;
    if(c===prev) o.selected=true;
    selCn.appendChild(o);
  });
  // Se canal atual não pertence ao grupo, resetar
  if(prev&&!list.includes(prev)){state.canal='';selCn.value='';}
}

// Populate dropdowns
const anos=[...new Set(DATA.detalhes.map(d=>dataAno(d)).filter(Boolean))].sort();
anos.forEach(a=>{const o=document.createElement('option');o.value=a;o.textContent=a;selAno.appendChild(o);});
const mesesDisp=[...new Set(DATA.detalhes.map(d=>dataMes(d)).filter(Boolean))].sort();
mesesDisp.forEach(m=>{const o=document.createElement('option');o.value=m;o.textContent=MESES[+m]||m;selMes.appendChild(o);});
[...new Set(DATA.detalhes.map(d=>d.empresa).filter(Boolean))].sort().forEach(e=>{const o=document.createElement('option');o.value=e;o.textContent=e;selEmpH.appendChild(o);});
[...new Set(DATA.detalhes.map(d=>d.estado).filter(Boolean))].sort().forEach(e=>{const o=document.createElement('option');o.value=e;o.textContent=e;selEst.appendChild(o);});
[...new Set(DATA.detalhes.map(d=>d.transportadora).filter(Boolean))].filter(t=>!isMarketplace(t)).sort().forEach(t=>{const o=document.createElement('option');o.value=t;o.textContent=trName(t);selTr.appendChild(o);});
buildCanalOptions('');

// MULTI-SELECT NAT OP
(function(){
  const natOps=[...new Set(DATA.detalhes.map(d=>d.nat_operacao).filter(Boolean))].sort();
  const btn=document.getElementById('ms_natop_btn');
  const drop=document.getElementById('ms_natop_drop');
  const allRow=document.createElement('div');
  allRow.className='ms-opt ms-all';
  allRow.innerHTML='<input type="checkbox" id="ms_all" checked><label for="ms_all">Todas as Nat. Operação</label>';
  drop.appendChild(allRow);
  natOps.forEach((n,i)=>{
    const d=document.createElement('div');d.className='ms-opt';
    const id='ms_n_'+i;
    const safe=n.replace(/&/g,'&amp;').replace(/"/g,'&quot;');
    d.innerHTML='<input type="checkbox" id="'+id+'" value="'+safe+'" checked><label for="'+id+'" title="'+safe+'">'+safe+'</label>';
    drop.appendChild(d);
  });
  function updateBtn(){
    if(state.natop.length===0){
      btn.innerHTML='Nat. Op. <span class="ms-arrow">v</span>';
    } else {
      btn.innerHTML='<span class="ms-count">'+state.natop.length+'</span> sel. <span class="ms-arrow">v</span>';
    }
  }
  function syncAll(){
    const allCb=drop.querySelector('#ms_all');
    const others=[...drop.querySelectorAll('input:not(#ms_all)')];
    const allChk=others.every(c=>c.checked);
    allCb.checked=allChk;
    allCb.indeterminate=!allChk&&others.some(c=>c.checked);
  }
  drop.addEventListener('change',e=>{
    const cb=e.target;
    if(cb.id==='ms_all'){
      drop.querySelectorAll('input:not(#ms_all)').forEach(c=>{c.checked=cb.checked;});
      state.natop=[];
    } else {
      const checked=[...drop.querySelectorAll('input:not(#ms_all)')].filter(c=>c.checked).map(c=>c.value);
      const total=[...drop.querySelectorAll('input:not(#ms_all)')].length;
      state.natop=checked.length===total?[]:checked;
      syncAll();
    }
    updateBtn();renderAll();
  });
  btn.addEventListener('click',e=>{
    e.stopPropagation();
    const isOpen=drop.classList.toggle('open');
    btn.classList.toggle('open');
    if(isOpen){
      const r=btn.getBoundingClientRect();
      drop.style.top=(r.bottom+4)+'px';
      drop.style.right=(window.innerWidth-r.right)+'px';
    }
  });
  document.addEventListener('click',e=>{
    if(!document.getElementById('ms_natop_wrap').contains(e.target)){drop.classList.remove('open');btn.classList.remove('open');}
  });
})();

// CATEGORIA
function setCategoria(cat){
  state.categoria=cat;
  document.getElementById('cat_all').classList.toggle('active',cat==='');
  document.getElementById('cat_b2b').classList.toggle('active',cat==='B2B');
  document.getElementById('cat_online').classList.toggle('active',cat==='Online');
  buildCanalOptions(cat);
  // Destaca o select de canal quando está filtrado
  selCn.style.borderColor=cat==='Online'?'var(--blue2)':cat==='B2B'?'var(--green2)':'var(--bd2)';
  selCn.style.color=cat?'var(--text)':'';
  renderAll();
}

// FILTROS AVANCADOS TOGGLE
function toggleAdvFilters(){
  const w=document.getElementById('hd_adv_wrap');
  const a=document.getElementById('hd_adv_arrow');
  const hidden=w.classList.contains('hidden');
  w.classList.toggle('hidden',!hidden);
  a.textContent=hidden?'▲':'▼';
}

// COMPARATIVO MES ANTERIOR
function prevMonthAgg(){
  if(!state.mes) return null;
  const curM=parseInt(state.mes);
  const curY=state.ano||'';
  let prevM=curM-1,prevY=curY;
  if(prevM===0){prevM=12;prevY=curY?String(parseInt(curY)-1):'';}
  const prevMStr=String(prevM).padStart(2,'0');
  const prevRows=DATA.detalhes.filter(d=>{
    if(d.is_marketplace) return false;
    if(dataMes(d)!==prevMStr) return false;
    if(prevY&&dataAno(d)!==prevY) return false;
    if(state.empresa&&d.empresa!==state.empresa) return false;
    if(state.linha&&d.linha!==state.linha) return false;
    if(state.categoria&&getCategoria(d.canal)!==state.categoria) return false;
    if(state.natop.length&&!state.natop.includes(d.nat_operacao)) return false;
    if(state.estado&&d.estado!==state.estado) return false;
    if(state.transp&&d.transportadora!==state.transp) return false;
    if(state.canal&&d.canal!==state.canal) return false;
    return true;
  });
  if(!prevRows.length) return null;
  return{agg:aggregate(prevRows),mes:prevM,ano:prevY};
}
function vsChip(cur,prv,higherIsBad){
  if(!prv||Math.abs(prv)<0.01) return '';
  const pct=(cur-prv)/Math.abs(prv)*100;
  const sign=pct>0?'▲':'▼';
  const good=higherIsBad?pct<=0:pct>=0;
  return '<span class="chip '+(good?'chip-green':'chip-red')+'" style="font-size:9px;padding:1px 6px">'+sign+' '+Math.abs(pct).toFixed(1)+'% vs anterior</span>';
}

// CENTRAL FILTER
function filterRows(rows,opts){
  const excMkt=(opts&&opts.excMkt!==undefined)?opts.excMkt:true;
  const onlyMkt=(opts&&opts.onlyMkt)||false;
  return rows.filter(d=>{
    if(excMkt&&d.is_marketplace) return false;
    if(onlyMkt&&!d.is_marketplace) return false;
    if(state.categoria&&getCategoria(d.canal)!==state.categoria) return false;
    if(state.ano&&dataAno(d)!==state.ano) return false;
    if(state.mes&&dataMes(d)!==state.mes) return false;
    if(state.empresa&&d.empresa!==state.empresa) return false;
    if(state.linha&&d.linha!==state.linha) return false;
    if(state.natop.length&&!state.natop.includes(d.nat_operacao)) return false;
    if(state.estado&&d.estado!==state.estado) return false;
    if(state.transp&&d.transportadora!==state.transp) return false;
    if(state.canal&&d.canal!==state.canal) return false;
    if(state.q){const h=(d.empresa+' '+d.linha+' '+d.nat_operacao+' '+d.cliente+' '+d.estado+' '+d.transportadora+' '+d.numero).toLowerCase();if(!h.includes(state.q)) return false;}
    return true;
  });
}

// TAGS
function updateTags(){
  const el=document.getElementById('active-filters');
  const L={ano:'Ano',mes:'Mes',linha:'Linha',empresa:'Empresa',natop:'Nat.Op.',estado:'UF',transp:'Transportadora',canal:'Canal',categoria:'Categoria'};
  const D={
    ano:state.ano,mes:state.mes?MESES[+state.mes]||state.mes:'',linha:state.linha,empresa:state.empresa,
    natop:state.natop.length?state.natop.length+' sel.':'',
    estado:state.estado,transp:state.transp?trName(state.transp):'',canal:state.canal,categoria:state.categoria
  };
  el.innerHTML=Object.entries(D).filter(([,v])=>v)
    .map(([k,v])=>'<span class="ftag">'+L[k]+': <strong>'+v+'</strong><span class="rm" data-key="'+k+'">&times;</span></span>').join('');
  el.querySelectorAll('.rm').forEach(b=>{
    b.onclick=()=>{
      const k=b.dataset.key;
      if(k==='natop'){
        state.natop=[];
        document.querySelectorAll('#ms_natop_drop input').forEach(c=>{c.checked=true;});
        document.getElementById('ms_natop_btn').innerHTML='Nat. Op. <span class="ms-arrow">v</span>';
      } else if(k==='categoria'){
        setCategoria('');return;
      } else {
        state[k]='';
        const m={ano:selAno,mes:selMes,linha:selLnH,empresa:selEmpH,estado:selEst,transp:selTr,canal:selCn};
        if(m[k]) m[k].value='';
      }
      renderAll();
    };
  });
}

// AGGREGATE
function aggregate(rows){
  const byEst={},byTr={},byCn={},byEmp={},byNat={};
  let tot=0,flh=0,fhu=0,nlh=0,nhu=0,cobTot=0,difTot=0,totalFat=0,margem=0,nCom=0,nSem=0;
  const inc=(obj,k,fr,nf,fl,fh)=>{
    if(!obj[k]) obj[k]={qtd:0,frete:0,nf:0,frete_lh:0,frete_hu:0};
    obj[k].qtd++;obj[k].frete+=fr;obj[k].nf+=nf;obj[k].frete_lh+=fl;obj[k].frete_hu+=fh;
  };
  rows.forEach(d=>{
    const fr=d.valor_frete,nf=d.total_nf,fl=d.frete_linhahum||0,fh=d.frete_humana||0;
    const cob=d.frete_cobrado||0,dif=d.diferenca_frete||0,nat=d.nat_operacao||'N/A';
    inc(byEst,d.estado||'N/A',fr,nf,fl,fh);inc(byTr,d.transportadora||'N/A',fr,0,fl,fh);
    inc(byCn,d.canal||'N/A',fr,nf,0,0);inc(byEmp,d.empresa||'N/A',fr,nf,fl,fh);
    if(!byNat[nat]) byNat[nat]={qtd:0,frete:0,nf:0,cobrado:0,diferenca:0};
    byNat[nat].qtd++;byNat[nat].frete+=fr;byNat[nat].nf+=nf;byNat[nat].cobrado+=cob;byNat[nat].diferenca+=dif;
    tot+=fr;flh+=fl;fhu+=fh;nlh+=(d.linhahum_total||0);nhu+=(d.humana_total||0);
    cobTot+=cob;difTot+=dif;totalFat+=nf;margem+=(d.margem_bruta||0);
    if(cob>0) nCom++; else nSem++;
  });
  const toList=(obj,k)=>Object.entries(obj).map(([l,v])=>({label:l,...v})).sort((a,b)=>b[k||'frete']-a[k||'frete']);
  const trList=toList(byTr);
  return{qtd:rows.length,tot,flh,fhu,nlh,nhu,cobTot,difTot,totalFat,margem,
    media:rows.length?tot/rows.length:0,fretePctFat:totalFat?tot/totalFat*100:0,
    nCom,nSem,numTransp:trList.length,topTransp:trList[0]||null,
    concTop1:trList.length&&tot?trList[0].frete/tot*100:0,
    byEst:toList(byEst),byTr:trList,byCn:toList(byCn),byEmp:toList(byEmp),byNat:toList(byNat)};
}

// ALERTS
function renderAlerts(agg){
  const el=document.getElementById('alerts-row');const al=[];
  if(agg.concTop1>70){const tr=agg.topTransp?trName(agg.topTransp.label):'?';
    al.push({t:'a-red',i:'<i class="fa-solid fa-triangle-exclamation"></i>',m:'<strong>Risco de Concentração:</strong> '+tr+' representa '+agg.concTop1.toFixed(1)+'% do frete. Alta dependência de um único parceiro logístico.'});}
  if(agg.difTot<-5000)
    al.push({t:'a-red',i:'<i class="fa-solid fa-arrow-trend-down"></i>',m:'<strong>Saldo Negativo:</strong> Empresa paga '+BRL(Math.abs(agg.difTot))+' a mais do que cobra. Revisar política de repasse de frete.'});
  if(agg.fretePctFat>8)
    al.push({t:'a-yellow',i:'<i class="fa-solid fa-lightbulb"></i>',m:'<strong>Custo de Frete Elevado:</strong> '+agg.fretePctFat.toFixed(1)+'% do faturamento &mdash; acima do benchmark (&lt;5%). Oportunidade de negociação e otimização de rotas.'});
  else if(agg.fretePctFat>5)
    al.push({t:'a-yellow',i:'<i class="fa-solid fa-chart-bar"></i>',m:'<strong>Frete na Zona de Atenção:</strong> '+agg.fretePctFat.toFixed(1)+'% do faturamento. Benchmark: &lt;5%.'});
  if(agg.qtd>0&&agg.nSem/agg.qtd>0.3)
    al.push({t:'a-yellow',i:'<i class="fa-solid fa-gift"></i>',m:'<strong>Alto Índice de Frete Grátis:</strong> '+(agg.nSem/agg.qtd*100).toFixed(1)+'% das entregas sem repasse. Avaliar impacto na margem bruta.'});
  if(al.length===0&&agg.qtd>0)
    al.push({t:'a-green',i:'<i class="fa-solid fa-circle-check"></i>',m:'<strong>Indicadores dentro do esperado.</strong> Nenhum desvio crítico identificado.'});
  el.innerHTML=al.map(a=>'<div class="alert '+a.t+'"><span class="alert-icon">'+a.i+'</span><span class="alert-text">'+a.m+'</span></div>').join('');
}

// INSIGHTS
function renderInsights(agg){
  const el=document.getElementById('insights-grid');
  if(!el||!agg.qtd) return;
  const ins=[];
  if(agg.topTransp){
    const tr=trName(agg.topTransp.label);const pct=agg.concTop1.toFixed(1);
    const cls=agg.concTop1>70?'bad':agg.concTop1>50?'hi':'ok';
    ins.push({i:'<i class="fa-solid fa-truck"></i>',t:'Parceiro Logístico Dominante',
      b:'<strong>'+tr+'</strong> concentra <span class="'+cls+'">'+pct+'%</span> do custo ('+BRL(agg.topTransp.frete)+'). '
        +(agg.concTop1>70?'Concentração <span class="bad">crítica</span> &mdash; renegociar e diversificar.'
          :agg.concTop1>50?'Concentração <span class="hi">moderada</span> &mdash; avaliar diversificação.':'Distribuição <span class="ok">saudável</span>.')});}
  const pct=agg.fretePctFat;
  ins.push({i:'<i class="fa-solid fa-chart-bar"></i>',t:'Custo Logístico vs Receita',
    b:'Frete = <strong><span class="'+(pct>8?'bad':pct>5?'hi':'ok')+'">'+pct.toFixed(2)+'%</span></strong> do faturamento vinculado. Benchmark: <strong>3-5%</strong>. '
      +(pct<=5?'<span class="ok">Dentro do padrão</span>.':pct<=8?'<span class="hi">Atenção</span>: margem de melhoria via negociação.':'<span class="bad">Acima do limite</span>: revisão urgente.')});
  ins.push({i:'<i class="fa-solid fa-scale-balanced"></i>',t:'Resultado Financeiro do Frete',
    b:'Saldo cobrado vs pago: <strong><span class="'+(agg.difTot>=0?'ok':'bad')+'">'+BRL(agg.difTot)+'</span></strong>. '
      +(agg.difTot>=0?'Empresa recupera <span class="ok">'+( Math.abs(agg.difTot)/agg.tot*100).toFixed(1)+'%</span> via repasse. Posicao favoravel.'
        :'<span class="bad">'+N(agg.nSem)+'</span> entregas sem frete cobrado elevam o custo operacional liquido.')});
  if(agg.byEst.length){const top=agg.byEst[0];const pctE=(top.frete/agg.tot*100).toFixed(1);const med=top.qtd?top.frete/top.qtd:0;const d=((med-agg.media)/agg.media*100).toFixed(0);
    ins.push({i:'<i class="fa-solid fa-location-dot"></i>',t:'Estado de Maior Impacto',
      b:'<strong>'+top.label+'</strong> responde por <strong>'+pctE+'%</strong> do frete ('+BRL(top.frete)+'). Ticket médio: '+BRL(med)+' &mdash; '
        +(+d>20?'<span class="bad">'+d+'% acima</span> da média geral.':+d<-20?'<span class="ok">'+Math.abs(+d)+'% abaixo</span> da média.':'alinhado com a média ('+BRL(agg.media)+')')+'.'});}
  if(agg.flh>0||agg.fhu>0){const tot2=agg.flh+agg.fhu||1;const pLH=(agg.flh/tot2*100).toFixed(1);const pHU=(agg.fhu/tot2*100).toFixed(1);
    const pLHv=agg.nlh?(agg.flh/agg.nlh*100).toFixed(2):null;const pHUv=agg.nhu?(agg.fhu/agg.nhu*100).toFixed(2):null;
    ins.push({i:'<i class="fa-solid fa-box-open"></i>',t:'Mix de Frete por Produto',
      b:'Linhahum: <strong>'+BRL(agg.flh)+'</strong> (<span class="'+(+pLHv>8?'bad':+pLHv>5?'hi':'ok')+'">'+pLH+'% do mix'+(pLHv?', '+pLHv+'% s/venda':'')+'</span>). '
        +'Humana: <strong>'+BRL(agg.fhu)+'</strong> (<span class="'+(+pHUv>8?'bad':+pHUv>5?'hi':'ok')+'">'+pHU+'% do mix'+(pHUv?', '+pHUv+'% s/venda':'')+'</span>). '
        +'Produto com maior custo relativo é prioridade de negociação.'});}
  const r=DATA.resumo;const taxa=r.total_nfe_fat?(agg.qtd/r.total_nfe_fat*100):0;
  ins.push({i:'<i class="fa-solid fa-link"></i>',t:'Cobertura de Documentos',
    b:'<strong><span class="'+(taxa>=90?'ok':taxa>=70?'hi':'bad')+'">'+taxa.toFixed(1)+'%</span></strong> das NF-e possuem CTe ('+N(agg.qtd)+' de '+N(r.total_nfe_fat||0)+'). '
      +(taxa>=90?'Cobertura <span class="ok">excelente</span>.':taxa>=70?'Cobertura <span class="hi">parcial</span> &mdash; CTe pendentes podem subestimar o custo.':'Cobertura <span class="bad">baixa</span> &mdash; verificar importacao de CTe.')});
  el.innerHTML=ins.map(i=>'<div class="insight-card"><div class="insight-icon">'+i.i+'</div><div class="insight-title">'+i.t+'</div><div class="insight-body">'+i.b+'</div></div>').join('');
}

// RENDER ALL
const PAGE=50;let tablePage=0;let filteredRows=[];let tableRows=[];let tableSort={col:null,dir:'desc'};
function renderAll(){
  filteredRows=filterRows(DATA.detalhes,{excMkt:true,onlyMkt:false});
  tableRows=applySortToRows(filteredRows);
  const agg=aggregate(tableRows);const r=DATA.resumo;

  // Hero KPIs
  document.getElementById('h_total').textContent=BRL(agg.tot);
  const pctStr=agg.fretePctFat.toFixed(1)+'%';
  const chipEl=document.getElementById('h_pct_fat_chip');
  chipEl.textContent=pctStr;
  chipEl.className='chip '+(agg.fretePctFat>8?'chip-red':agg.fretePctFat>5?'chip-amber':'chip-green');
  const saldoEl=document.getElementById('h_saldo');
  saldoEl.textContent=BRL(agg.difTot);
  saldoEl.style.color=agg.difTot>=0?'var(--green)':'var(--red)';
  document.getElementById('h_saldo_sub').innerHTML=agg.difTot>=0
    ?'<span class="chip chip-green"><i class="fa-solid fa-arrow-up"></i> Cobrado &gt; Pago</span>&nbsp;empresa cobre o custo'
    :'<span class="chip chip-red"><i class="fa-solid fa-arrow-down"></i> Pago &gt; Cobrado</span>&nbsp;prejuizo no frete';
  const pctRecEl=document.getElementById('h_pct_rec');
  pctRecEl.textContent=pctStr;
  pctRecEl.style.color=agg.fretePctFat>8?'var(--red)':agg.fretePctFat>5?'var(--yellow)':'var(--green)';
  document.getElementById('h_pct_rec_sub').innerHTML=agg.fretePctFat<=5
    ?'<span class="chip chip-green"><i class="fa-solid fa-check"></i> Abaixo do benchmark</span>'
    :agg.fretePctFat<=8?'<span class="chip chip-amber"><i class="fa-solid fa-triangle-exclamation"></i>Atenção &mdash; meta &lt;5%</span>'
    :'<span class="chip chip-red"><i class="fa-solid fa-xmark"></i> Acima do benchmark</span>';
  document.getElementById('h_ticket').textContent=BRL(agg.media);
  document.getElementById('h_ticket_sub').textContent=N(agg.qtd)+' entregas vinculadas';

  // Secondary KPIs
  document.getElementById('k_vinc').textContent=N(agg.qtd);
  document.getElementById('k_vinc_sub').textContent='de '+N(r.total_nfe_fat||0)+' NF-e';
  const taxa=r.total_nfe_fat?(agg.qtd/r.total_nfe_fat*100):0;
  const taxaEl=document.getElementById('k_cobertura');
  taxaEl.textContent=taxa.toFixed(1)+'%';
  taxaEl.style.color=taxa>=90?'var(--green)':taxa>=70?'var(--yellow)':'var(--red)';
  document.getElementById('k_ntransp').textContent=N(agg.numTransp);
  document.getElementById('k_ntransp_sub').textContent=agg.topTransp?'Top: '+trName(agg.topTransp.label):'';
  const concEl=document.getElementById('k_conc');
  concEl.textContent=agg.concTop1.toFixed(1)+'%';
  concEl.style.color=agg.concTop1>70?'var(--red)':agg.concTop1>50?'var(--yellow)':'var(--green)';
  document.getElementById('k_conc_sub').textContent=agg.topTransp?trName(agg.topTransp.label):'';
  document.getElementById('k_gratis').textContent=N(agg.nSem);
  document.getElementById('k_gratis_sub').textContent=(agg.qtd?(agg.nSem/agg.qtd*100).toFixed(1):0)+'% das entregas';

  // LP KPIs
  const tot1=agg.tot||1;
  document.getElementById('k_lh_frete').textContent=BRL(agg.flh);
  document.getElementById('k_lh_pct').textContent=(agg.flh/tot1*100).toFixed(1)+'% do frete';
  document.getElementById('k_hu_frete').textContent=BRL(agg.fhu);
  document.getElementById('k_hu_pct').textContent=(agg.fhu/tot1*100).toFixed(1)+'% do frete';
  document.getElementById('k_lh_nf').textContent=BRL(agg.nlh);
  document.getElementById('k_hu_nf').textContent=BRL(agg.nhu);
  const lhPV=document.getElementById('k_lh_pctvenda');
  lhPV.textContent=agg.nlh?(agg.flh/agg.nlh*100).toFixed(2)+'%':'--';
  lhPV.style.color=agg.nlh&&agg.flh/agg.nlh*100>8?'var(--red)':agg.nlh&&agg.flh/agg.nlh*100>5?'var(--yellow)':'var(--green)';
  const huPV=document.getElementById('k_hu_pctvenda');
  huPV.textContent=agg.nhu?(agg.fhu/agg.nhu*100).toFixed(2)+'%':'--';
  huPV.style.color=agg.nhu&&agg.fhu/agg.nhu*100>8?'var(--red)':agg.nhu&&agg.fhu/agg.nhu*100>5?'var(--yellow)':'var(--green)';

  renderAlerts(agg);renderInsights(agg);

  // TIMELINE chart - frete absoluto
  const allPers=[...new Set(DATA.detalhes.map(d=>per(d.data)).filter(Boolean))].sort();
  const allEmps=[...new Set(tableRows.map(d=>d.empresa).filter(Boolean))].sort();
  const byPE={};
  tableRows.forEach(d=>{
    const p=per(d.data);if(!p) return;const e=d.empresa||'N/A';
    if(!byPE[p]) byPE[p]={};byPE[p][e]=(byPE[p][e]||0)+d.valor_frete;
  });
  const tlLbs=allPers.map(p=>perL(p));
  const tlDs=allEmps.map((emp,i)=>({
    label:emp,data:allPers.map(p=>(byPE[p]&&byPE[p][emp])||0),
    borderColor:COLORS[i%COLORS.length],backgroundColor:COLORS[i%COLORS.length]+'22',
    fill:false,tension:.4,pointRadius:3,pointHoverRadius:6,borderWidth:2,
    pointBackgroundColor:COLORS[i%COLORS.length],pointBorderColor:'#fff',pointBorderWidth:2,
  }));
  mkLine('ch_timeline',tlLbs,tlDs);

  // % Frete/Venda — eixo X cronológico, uma linha por empresa
  const byPE_nf={};
  tableRows.forEach(d=>{
    const p=per(d.data);if(!p) return;const e=d.empresa||'N/A';
    if(!byPE_nf[p]) byPE_nf[p]={};
    if(!byPE_nf[p][e]) byPE_nf[p][e]={fr:0,nf:0};
    byPE_nf[p][e].fr+=d.valor_frete;byPE_nf[p][e].nf+=d.total_nf;
  });
  const pctDs=allEmps.map((emp,i)=>({
    label:emp,
    data:allPers.map(p=>{const v=byPE_nf[p]&&byPE_nf[p][emp];return v&&v.nf?+(v.fr/v.nf*100).toFixed(2):null;}),
    borderColor:COLORS[i%COLORS.length],backgroundColor:COLORS[i%COLORS.length]+'22',
    fill:false,tension:.4,pointRadius:3,pointHoverRadius:6,borderWidth:2,
    pointBackgroundColor:COLORS[i%COLORS.length],pointBorderColor:'#fff',pointBorderWidth:2,
    spanGaps:true,
  }));
  mkLinePct('ch_pct_emp_mes',tlLbs,pctDs);

  // Comparativo anual por mês — popula dropdown e guarda dados
  const allYears=[...new Set(tableRows.map(d=>dataAno(d)).filter(Boolean))].sort();
  const byYME={}; // {ano: {mes: {fr,nf}}} e {ano+'|'+emp: {mes:{fr,nf}}}
  tableRows.forEach(d=>{
    const a=dataAno(d),m=dataMes(d),e=d.empresa||'N/A';if(!a||!m) return;
    // total
    if(!byYME[a]) byYME[a]={};
    if(!byYME[a][m]) byYME[a][m]={fr:0,nf:0};
    byYME[a][m].fr+=d.valor_frete; byYME[a][m].nf+=d.total_nf;
    // por empresa
    const ke=a+'|'+e;
    if(!byYME[ke]) byYME[ke]={};
    if(!byYME[ke][m]) byYME[ke][m]={fr:0,nf:0};
    byYME[ke][m].fr+=d.valor_frete; byYME[ke][m].nf+=d.total_nf;
  });
  window._yoyData={allYears,allEmps,byYME,allPers,tlLbs};
  renderYoY();

  // Charts
  const top15E=agg.byEst.slice(0,15);
  mkMultiBar('ch_estado',top15E.map(x=>x.label),top15E.map(x=>x.frete),
    top15E.map((_,i)=>'hsl('+(215-i*6)+',70%,'+(52-i)+'%)'));
  const top10T=agg.byTr.slice(0,10);
  mkDonut('ch_transp',top10T.map(x=>trName(x.label)),top10T.map(x=>x.frete));
  mkBar('ch_empresa',agg.byEmp.map(x=>x.label),agg.byEmp.map(x=>x.frete),'#059669');

  // Warn
  const wShow=r.nfe_sem_cte>0&&!state.ano&&!state.mes&&!state.empresa&&!state.linha;
  document.getElementById('warn_box').style.display=wShow?'':'none';
  document.getElementById('warn_sem').textContent=N(r.nfe_sem_cte);

  // Nat Op table
  document.getElementById('natop_tbody').innerHTML=agg.byNat.map((n,i)=>{
    const saldo=n.diferenca||0;const sC=saldo>0?'color:var(--green)':saldo<0?'color:var(--red)':'color:var(--text3)';
    const pct=agg.tot?(n.frete/agg.tot*100):0;
    return '<tr><td style="color:var(--text3);font-weight:700;font-size:10px">'+(i+1)+'</td>'
      +'<td style="color:var(--text);font-weight:500">'+n.label+'</td>'
      +'<td>'+N(n.qtd)+'</td><td style="color:var(--text);font-weight:600">'+BRL(n.frete)+'</td>'
      +'<td>'+BRL(n.cobrado)+'</td>'
      +'<td style="'+sC+';font-weight:700">'+BRL(saldo)+'</td>'
      +'<td>'+pct.toFixed(1)+'%</td>'
      +'<td><div style="width:'+Math.min(pct*4,100)+'px;height:3px;background:var(--blue);border-radius:2px;opacity:.7"></div></td></tr>';
  }).join('');

  updateTags();
  document.getElementById('tb_vinc').textContent=N(agg.qtd);
  document.getElementById('tb_op').textContent=N(agg.qtd);
  document.getElementById('footer_info').textContent=N(agg.qtd)+' NF-e vinculadas  |  '+BRL(agg.tot)+'  |  '+DATA.gerado_em;

  // Comparativo mes anterior
  const prevData=prevMonthAgg();
  const prev=prevData?prevData.agg:null;
  const prevLbl=prevData?MESES[prevData.mes]+(prevData.ano?' '+prevData.ano.slice(2):''):'';
  const vsNote=prev?(' <span style="color:var(--text3);font-size:9px">vs '+prevLbl+'</span>'):'';
  document.getElementById('h_total_vs').innerHTML=prev?vsChip(agg.tot,prev.tot,true)+vsNote:'';
  document.getElementById('h_saldo_vs').innerHTML=prev?vsChip(agg.difTot,prev.difTot,false)+vsNote:'';
  document.getElementById('h_pct_vs').innerHTML=prev?vsChip(agg.fretePctFat,prev.fretePctFat,true)+vsNote:'';
  document.getElementById('h_ticket_vs').innerHTML=prev?vsChip(agg.media,prev.media,true)+vsNote:'';

  tablePage=0;renderTable();
  // Re-renderiza a aba ativa se não for a Visão Geral (que já foi atualizada acima)
  const activeTab=document.querySelector('.tab-btn.active');
  if(activeTab){
    const tab=activeTab.getAttribute('data-tab');
    if(tab==='empresa') renderEmpresa();
    else if(tab==='marketplace') renderMarketplace();
    else if(tab==='clientes') renderClientes();
    else if(tab==='nao-vinculados') nvRender();
    else if(tab==='compras') renderCompras();
    else if(tab==='dev-mkt') renderDevMkt();
    // 'visao-geral' e 'operacional' já foram atualizados acima
  }
}

// TABLE HELPERS
function pctBar(fr,nf,maxPct){
  if(!nf) return '<span style="color:var(--text3)">-</span>';
  const p=fr/nf*100;
  const cls=p<5?'tg':p<10?'ty':'tr';
  const barClr=p<5?'var(--green)':p<10?'var(--amber)':'var(--red)';
  const w=maxPct>0?Math.min(100,p/maxPct*100).toFixed(0):0;
  return '<div class="pct-bar-wrap">'
    +'<span class="tag '+cls+'">'+p.toFixed(1)+'%</span>'
    +'<div class="pct-bar-bg"><div class="pct-bar-fill" style="width:'+w+'%;background:'+barClr+'"></div></div>'
    +'</div>';
}
function applySortToRows(rows){
  if(!tableSort.col) return rows;
  return [...rows].sort((a,b)=>{
    let va,vb;
    if(tableSort.col==='pct'){va=a.total_nf?a.valor_frete/a.total_nf:0;vb=b.total_nf?b.valor_frete/b.total_nf:0;}
    else if(tableSort.col==='total_nf'){va=a.total_nf||0;vb=b.total_nf||0;}
    else if(tableSort.col==='valor_frete'){va=a.valor_frete||0;vb=b.valor_frete||0;}
    else if(tableSort.col==='diferenca'){va=a.diferenca_frete||0;vb=b.diferenca_frete||0;}
    return tableSort.dir==='desc'?vb-va:va-vb;
  });
}
function sortBy(col){
  if(tableSort.col===col) tableSort.dir=tableSort.dir==='desc'?'asc':'desc';
  else{tableSort.col=col;tableSort.dir='desc';}
  tableRows=applySortToRows(filteredRows);
  tablePage=0;renderTable();updateSortHeaders();
}
function updateSortHeaders(){
  ['total_nf','valor_frete','diferenca','pct'].forEach(c=>{
    const th=document.getElementById('th_'+c);if(!th)return;
    th.classList.remove('sort-asc','sort-desc');
    if(tableSort.col===c) th.classList.add('sort-'+tableSort.dir);
  });
}
function linhaTag(l){
  if(l==='Linhahum') return '<span class="tag tg">Linhahum</span>';
  if(l==='Humana Alimentar') return '<span class="tag tb">Humana</span>';
  return '<span class="tag ty">Misto</span>';
}
// Índice CTe → NF-e para exibir rateio completo
const cteRateioIndex={};
DATA.detalhes.forEach(d=>{
  if(d.is_rateio&&d.cte_chave){
    if(!cteRateioIndex[d.cte_chave]) cteRateioIndex[d.cte_chave]=[];
    cteRateioIndex[d.cte_chave].push(d);
  }
});
function toggleRateioDetail(trId,cteChave,curNfe){
  const detId='rd-'+trId;
  const existing=document.getElementById(detId);
  const btn=document.getElementById('rb-'+trId);
  if(existing){
    existing.remove();
    if(btn) btn.innerHTML='<i class="fa-solid fa-circle-info"></i> Rateio';
    return;
  }
  if(btn) btn.innerHTML='<i class="fa-solid fa-chevron-up"></i> Fechar';
  const peers=(cteRateioIndex[cteChave]||[]).slice().sort((a,b)=>b.pct_rateio-a.pct_rateio);
  const totCte=peers.length?(peers[0].valor_frete_cte||peers.reduce((s,r)=>s+r.valor_frete,0)):0;
  const maxPct=peers.length?peers[0].pct_rateio:1;
  const peersHtml=peers.map(r=>{
    const isCur=r.chave_nfe===curNfe;
    const bw=(maxPct>0?r.pct_rateio/maxPct*100:0).toFixed(0);
    return '<tr style="border-bottom:1px solid #1A2535'+(isCur?';background:rgba(245,158,11,.08)':'')+'">'
      +'<td style="padding:5px 10px"><strong style="color:'+(isCur?'var(--amber)':'var(--text)')+'">'+r.empresa+'</strong>'+(isCur?' <span style="font-size:9px;background:#3D2E00;color:var(--amber);padding:1px 6px;border-radius:4px">esta NF-e</span>':'')+'</td>'
      +'<td style="font-family:monospace;font-size:10px;color:var(--text3)">'+r.numero+'</td>'
      +'<td style="text-align:right;color:var(--text)">'+BRL(r.total_nf)+'</td>'
      +'<td style="text-align:right;color:var(--blue2);font-weight:700">'+BRL(r.valor_frete)+'</td>'
      +'<td style="text-align:right;font-weight:700;color:var(--amber)">'+r.pct_rateio+'%</td>'
      +'<td style="min-width:100px;padding:5px 10px"><div style="height:4px;border-radius:2px;background:#1E2D42"><div style="height:100%;border-radius:2px;background:var(--amber);width:'+bw+'%"></div></div></td>'
      +'</tr>';
  }).join('');
  const panel='<tr id="'+detId+'" style="background:#080D18"><td colspan="19" style="padding:0">'
    +'<div style="background:#0A1525;border-left:3px solid var(--amber);padding:14px 18px;margin:0 0 2px 0">'
    +'<div style="display:flex;align-items:center;gap:14px;margin-bottom:10px;flex-wrap:wrap">'
    +'<span style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.7px;color:var(--amber)"><i class="fa-solid fa-truck"></i> Rateio do CTe</span>'
    +'<span style="font-family:monospace;font-size:10px;color:var(--text3)">...'+cteChave.slice(-14)+'</span>'
    +'<span style="font-size:11px;color:var(--text2)">Frete total do CTe: <strong style="color:var(--text)">'+BRL(totCte)+'</strong></span>'
    +'<span style="font-size:11px;color:var(--text2)">Dividido entre <strong style="color:var(--amber)">'+peers.length+'</strong> NF-e do faturamento</span>'
    +'</div>'
    +'<table style="width:100%;border-collapse:collapse;font-size:11px">'
    +'<thead><tr style="border-bottom:1px solid #2A3F58;font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:var(--text3)">'
    +'<th style="padding:4px 10px;text-align:left">Empresa</th><th style="text-align:left">NF</th>'
    +'<th style="text-align:right">Valor da Nota</th><th style="text-align:right">Frete Rateado</th>'
    +'<th style="text-align:right">% do Rateio</th><th style="min-width:100px">Proporção</th></tr></thead>'
    +'<tbody>'+peersHtml+'</tbody>'
    +'<tfoot><tr style="border-top:1px solid #2A3F58;font-weight:700">'
    +'<td colspan="3" style="padding:5px 10px;color:var(--text3);font-size:10px">Total</td>'
    +'<td style="text-align:right;color:var(--text)">'+BRL(totCte)+'</td>'
    +'<td style="text-align:right;color:var(--text)">100%</td><td></td>'
    +'</tr></tfoot></table></div></td></tr>';
  document.getElementById(trId).insertAdjacentHTML('afterend',panel);
}
function mkDetailRow(d,rowId){
  const dif=d.diferenca_frete||0;const dC=dif>0?'color:var(--green)':dif<0?'color:var(--red)':'color:var(--text3)';
  const cob=d.frete_cobrado||0;
  const pct=d.total_nf?d.valor_frete/d.total_nf*100:0;
  const rowCls=pct>10?' class="row-alert"':'';
  const rid=rowId||'x';
  const rateioBtn=d.is_rateio
    ?'<button id="rb-'+rid+'" onclick="event.stopPropagation();toggleRateioDetail(\''+rid+'\',\''+d.cte_chave+'\',\''+d.chave_nfe+'\')" style="margin-left:5px;background:#3D2E00;border:1px solid #6B4F00;color:var(--amber);font-size:9px;font-weight:700;padding:1px 7px;border-radius:4px;cursor:pointer;font-family:inherit"><i class="fa-solid fa-circle-info"></i> Rateio</button>'
    :'';
  return '<tr id="'+rid+'"'+rowCls+'>'
    +'<td><strong>'+(d.empresa||'-')+'</strong></td>'
    +'<td>'+linhaTag(d.linha)+'</td>'
    +'<td style="font-family:monospace;font-size:10px">'+(d.numero||'-')+'</td>'
    +'<td>'+(d.data||'-')+'</td><td>'+(d.canal||'-')+'</td>'
    +'<td style="color:var(--text);font-weight:600">'+BRL(d.total_nf)+'</td>'
    +'<td style="color:var(--blue2);font-weight:600;white-space:nowrap">'+BRL(d.valor_frete)+rateioBtn+'</td>'
    +'<td>'+pctBarInline(d.valor_frete,d.total_nf)+'</td>'
    +'<td>'+BRL(d.linhahum_total||0)+'</td><td>'+BRL(d.humana_total||0)+'</td>'
    +'<td>'+(cob>0?BRL(cob):'<span style="color:var(--text3)">-</span>')+'</td>'
    +'<td style="'+dC+';font-weight:700">'+(cob>0?BRL(dif):'<span style="color:var(--text3)">-</span>')+'</td>'
    +'<td>'+BRL(d.frete_linhahum||0)+'</td><td>'+BRL(d.frete_humana||0)+'</td>'
    +'<td style="text-align:center">'+(d.qtd_nf_cte||1)+'</td>'
    +'<td title="'+(d.transportadora||'')+'">'+trName(d.transportadora||'-')+'</td>'
    +'<td style="font-size:10px">'+(d.origem_cidade||'')+(d.origem_uf?'/'+d.origem_uf:'')+'</td>'
    +'<td style="font-size:10px">'+(d.destino_cidade||'')+(d.destino_uf?'/'+d.destino_uf:'')+'</td>'
    +'<td style="text-align:right">'+(d.peso_kg||0)+'</td>'
    +'</tr>';
}
function pctBarInline(fr,nf){
  if(!nf) return '<span style="color:var(--text3)">-</span>';
  const p=fr/nf*100;
  const cls=p<5?'tg':p<10?'ty':'tr';
  const barClr=p<5?'var(--green)':p<10?'var(--amber)':'var(--red)';
  return '<div class="pct-bar-wrap">'
    +'<span class="tag '+cls+'">'+p.toFixed(1)+'%</span>'
    +'<div class="pct-bar-bg"><div class="pct-bar-fill" style="width:'+Math.min(p*5,100)+'%;background:'+barClr+'"></div></div>'
    +'</div>';
}
function mkPager(total,page,perPage,pagerId,onPage){
  const pages=Math.ceil(total/perPage);
  const pager=document.getElementById(pagerId);pager.innerHTML='';
  if(pages<=1){pager.innerHTML='<span class="pinfo">'+N(total)+' registro(s)</span>';return;}
  const addBtn=(lbl,pg,act,dis)=>{
    const b=document.createElement('button');b.textContent=lbl;
    if(act)b.classList.add('active');if(dis)b.disabled=true;
    b.onclick=()=>onPage(pg);pager.appendChild(b);
  };
  const info=document.createElement('span');info.className='pinfo';
  info.textContent=N(total)+' reg.  p.'+(page+1)+'/'+pages;pager.appendChild(info);
  addBtn('<<',0,false,page===0);addBtn('<',page-1,false,page===0);
  const lo=Math.max(0,page-2),hi=Math.min(pages-1,page+2);
  for(let i=lo;i<=hi;i++) addBtn(i+1,i,i===page);
  addBtn('>',page+1,false,page===pages-1);addBtn('>>',pages-1,false,page===pages-1);
}
function renderTable(){
  const tbody=document.getElementById('tbody');
  const slice=tableRows.slice(tablePage*PAGE,tablePage*PAGE+PAGE);
  tbody.innerHTML=slice.map((d,i)=>mkDetailRow(d,'dr'+(tablePage*PAGE+i))).join('');
  mkPager(tableRows.length,tablePage,PAGE,'pager',pg=>{tablePage=pg;renderTable();});
}

// EVENTS
selAno.addEventListener('change', ()=>{state.ano=selAno.value;renderAll();});
selMes.addEventListener('change', ()=>{state.mes=selMes.value;renderAll();});
selEmpH.addEventListener('change',()=>{state.empresa=selEmpH.value;renderAll();});
selLnH.addEventListener('change', ()=>{state.linha=selLnH.value;renderAll();});
selEst.addEventListener('change', ()=>{state.estado=selEst.value;renderAll();});
selTr.addEventListener('change',  ()=>{state.transp=selTr.value;renderAll();});
selCn.addEventListener('change',  ()=>{state.canal=selCn.value;renderAll();});
inpQ.addEventListener('input',    ()=>{state.q=inpQ.value.toLowerCase();renderAll();});

// ABA MARKETPLACE
let mktPage=0;let mktRows=[];let mktFilterVal='';
function setMktFilter(val){
  mktFilterVal=val;
  document.getElementById('mkt_f_all').classList.toggle('active',val==='');
  document.getElementById('mkt_f_shopee').classList.toggle('active',val==='SHOPEE');
  document.getElementById('mkt_f_ml').classList.toggle('active',val==='MERCADO LIVRE');
  mktPage=0;renderMktTable();
}
function renderMarketplace(){
  mktRows=filterRows(DATA.detalhes,{excMkt:false,onlyMkt:true});
  const shopee=mktRows.filter(d=>d.marketplace_type==='shopee');
  const ml=mktRows.filter(d=>d.marketplace_type==='ml');
  const sumF=arr=>arr.reduce((s,d)=>s+d.valor_frete,0);
  document.getElementById('mkt_shopee_frete').textContent=BRL(sumF(shopee));
  document.getElementById('mkt_shopee_qtd').textContent=N(shopee.length)+' CTe';
  document.getElementById('mkt_shopee_med').textContent=shopee.length?BRL(sumF(shopee)/shopee.length):'-';
  document.getElementById('mkt_ml_frete').textContent=BRL(sumF(ml));
  document.getElementById('mkt_ml_qtd').textContent=N(ml.length)+' CTe';
  document.getElementById('mkt_ml_med').textContent=ml.length?BRL(sumF(ml)/ml.length):'-';
  document.getElementById('tb_mkt').textContent=N(mktRows.length);

  // Timeline Shopee vs ML
  const allPers=[...new Set(DATA.detalhes.map(d=>per(d.data)).filter(Boolean))].sort();
  const byPerSh={},byPerMl={};
  shopee.forEach(d=>{const p=per(d.data);if(p) byPerSh[p]=(byPerSh[p]||0)+d.valor_frete;});
  ml.forEach(d=>{const p=per(d.data);if(p) byPerMl[p]=(byPerMl[p]||0)+d.valor_frete;});
  mkLine('ch_mkt_timeline',allPers.map(p=>perL(p)),[
    {label:'Shopee',data:allPers.map(p=>byPerSh[p]||0),borderColor:'#FF6900',backgroundColor:'#FF690022',fill:false,tension:.4,pointRadius:3,pointHoverRadius:6,borderWidth:2,pointBackgroundColor:'#FF6900',pointBorderColor:'#fff',pointBorderWidth:2},
    {label:'Mercado Livre',data:allPers.map(p=>byPerMl[p]||0),borderColor:'#FFE600',backgroundColor:'#FFE60022',fill:false,tension:.4,pointRadius:3,pointHoverRadius:6,borderWidth:2,pointBackgroundColor:'#FFE600',pointBorderColor:'#fff',pointBorderWidth:2},
  ]);

  mktPage=0;renderMktTable();
}
function renderMktTable(){
  const tbody=document.getElementById('mkt_tbody');
  const filtered=mktFilterVal==='SHOPEE'?mktRows.filter(d=>d.marketplace_type==='shopee'):mktFilterVal==='MERCADO LIVRE'?mktRows.filter(d=>d.marketplace_type==='ml'):mktRows;
  const slice=filtered.slice(mktPage*PAGE,mktPage*PAGE+PAGE);
  tbody.innerHTML=slice.map(d=>mkDetailRow(d)).join('');
  mkPager(filtered.length,mktPage,PAGE,'mkt_pager',pg=>{mktPage=pg;renderMktTable();});
}

// ABA CLIENTES
let cliPage=0;let cliData=[];
function renderClientes(){
  // Exclui marketplace, linha Humana Alimentar e NF-e cujo destinatário é uma loja do grupo (transferências internas)
  const rows=filterRows(DATA.detalhes,{excMkt:true,onlyMkt:false})
    .filter(d=>d.linha!=='Humana Alimentar')
    .filter(d=>!/HUMANA\s*ALIMENTAR/i.test(d.cliente||''));
  const grupos={};
  rows.forEach(d=>{
    const wk=getWeek(d.data);if(!wk) return;
    const key=(d.cliente||'?')+'||'+(d.empresa||'?')+'||'+wk;
    if(!grupos[key]) grupos[key]={cliente:d.cliente||'?',empresa:d.empresa||'?',semana:wk,ctes:[],destinos:{}};
    grupos[key].ctes.push(d);
    const dest=(d.destino_cidade||'?')+'/'+(d.destino_uf||'?');
    grupos[key].destinos[dest]=(grupos[key].destinos[dest]||0)+1;
  });
  cliData=Object.values(grupos).filter(g=>g.ctes.length>=2).sort((a,b)=>b.ctes.length-a.ctes.length);
  document.getElementById('tb_cli').textContent=N(cliData.length);
  let ecoTotal=0;let totalCtesConsolid=0;
  cliData.forEach(g=>{
    const fretes=g.ctes.map(d=>d.valor_frete).sort((a,b)=>a-b);
    ecoTotal+=fretes.slice(0,fretes.length-1).reduce((s,v)=>s+v,0);
    totalCtesConsolid+=fretes.length-1;
  });
  document.getElementById('conso_grupos').textContent=N(cliData.length);
  document.getElementById('conso_txt').innerHTML='<strong>grupos</strong> com potencial de consolidação — economia estimada de <strong>'+BRL(ecoTotal)+'</strong> (fretes menores dentro de cada grupo).';
  document.getElementById('cli_k_grupos').textContent=N(cliData.length);
  document.getElementById('cli_k_eco').textContent=BRL(ecoTotal);
  document.getElementById('cli_k_ctes').textContent=N(totalCtesConsolid);
  cliPage=0;renderCliTable();
}
function fmtSemana(wk){
  const m=wk.match(/(\d{4})-W(\d+)/);
  return m?'Sem. '+m[2]+'/'+m[1]:wk;
}
function toggleCliDetails(key){
  const el=document.getElementById('clidet-'+key);
  const btn=document.getElementById('clibtn-'+key);
  if(!el) return;
  const open=el.style.display!=='none';
  el.style.display=open?'none':'table-row';
  btn.textContent=open?'▼ Ver detalhes':'▲ Fechar';
}
function renderCliTable(){
  const tbody=document.getElementById('cli_tbody');
  const q=(document.getElementById('cli_search')||{value:''}).value.trim().toLowerCase();
  const display=q?cliData.filter(g=>
    (g.cliente||'').toLowerCase().includes(q)||
    g.ctes.some(d=>(d.numero||'').toLowerCase().includes(q))
  ):cliData;
  const slice=display.slice(cliPage*PAGE,cliPage*PAGE+PAGE);
  tbody.innerHTML=slice.map((g,idx)=>{
    const gkey=cliPage*PAGE+idx;
    const tot=g.ctes.reduce((s,d)=>s+d.valor_frete,0);
    const fretes=g.ctes.map(d=>d.valor_frete).sort((a,b)=>a-b);
    const eco=fretes.slice(0,fretes.length-1).reduce((s,v)=>s+v,0);
    const destList=Object.entries(g.destinos).sort((a,b)=>b[1]-a[1]);
    const mesmoDest=destList.length===1;
    // Chips de destino: mostra cada cidade como chip
    const destChips=destList.slice(0,3).map(([d,n])=>{
      const [cidade,uf]=(d||'').split('/');
      return '<span class="chip chip-gray" style="margin:1px 2px;font-size:9px;display:inline-block">'
        +(cidade||d)+(uf?' <strong>'+uf+'</strong>':'')+(destList.length>1&&n>1?' ×'+n:'')+'</span>';
    }).join('')+(destList.length>3?'<span style="font-size:9px;color:var(--text3)"> +'+( destList.length-3)+' mais</span>':'');
    const mesmoBadge=mesmoDest
      ?'<span class="chip chip-green" style="font-size:9px"><i class="fa-solid fa-check"></i> Mesmo destino</span>'
      :'<span class="chip chip-amber" style="font-size:9px"><i class="fa-solid fa-triangle-exclamation"></i>'+destList.length+' destinos diferentes</span>';
    const mainRow='<tr style="cursor:pointer" onclick="toggleCliDetails('+gkey+')">'
      +'<td style="white-space:normal;max-width:180px"><strong>'+(g.cliente||'-')+'</strong></td>'
      +'<td>'+g.empresa+'</td>'
      +'<td><span class="chip chip-blue">'+fmtSemana(g.semana)+'</span></td>'
      +'<td style="text-align:center"><span class="chip chip-amber">'+g.ctes.length+'x</span></td>'
      +'<td style="color:var(--text);font-weight:600;white-space:nowrap">'+BRL(tot)+'</td>'
      +'<td style="max-width:220px;white-space:normal;line-height:1.6">'+destChips+'</td>'
      +'<td style="white-space:nowrap">'+mesmoBadge+'</td>'
      +'<td style="color:var(--green2);font-weight:700;white-space:nowrap">'+BRL(eco)+'</td>'
      +'<td><button id="clibtn-'+gkey+'" class="chip chip-blue" style="cursor:pointer;border:none;padding:3px 9px;font-size:10px;white-space:nowrap" onclick="event.stopPropagation();toggleCliDetails('+gkey+')"><i class="fa-solid fa-chevron-down"></i> Detalhar</button></td>'
      +'</tr>';
    // Agrupa NF-e por CTe para exibição com chave completa
    const cteGrps={};
    g.ctes.forEach(d=>{
      const ck=d.cte_chave||'__sem__';
      if(!cteGrps[ck]){cteGrps[ck]={cte_chave:d.cte_chave||'',transportadora:d.transportadora||'',
        destino_cidade:d.destino_cidade||'',destino_uf:d.destino_uf||'',
        origem_cidade:d.origem_cidade||'',origem_uf:d.origem_uf||'',
        valor_frete_cte:d.valor_frete_cte||0,peso_kg:d.peso_kg||0,nfes:[]};}
      cteGrps[ck].nfes.push(d);
    });
    const detHeader='<tr style="background:rgba(59,130,246,.08);border-bottom:1px solid #2A3F58;font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:var(--text3)">'
      +'<td style="padding:6px 10px;min-width:80px">Data NF</td>'
      +'<td style="min-width:85px">Número NF</td>'
      +'<td style="min-width:100px">Valor Nota</td>'
      +'<td style="min-width:105px">Frete Rateado</td>'
      +'<td style="min-width:70px;color:var(--amber)">% Frete</td>'
      +'<td style="min-width:90px">Origem</td>'
      +'<td colspan="2" style="min-width:220px;color:var(--blue2)">Chave NF-e</td>'
      +'<td style="min-width:110px;color:var(--blue2)"><i class="fa-solid fa-location-dot"></i> Destino</td>'
      +'</tr>';
    const detRows=Object.values(cteGrps).map(cg=>{
      const cteFull=cg.cte_chave;
      const cteDisp=cteFull?cteFull.slice(0,12)+'…'+cteFull.slice(-8):'--';
      const cteHdr='<tr style="background:rgba(59,130,246,.18);border-top:2px solid rgba(59,130,246,.45);border-bottom:1px solid rgba(59,130,246,.25)">'
        +'<td colspan="9" style="padding:6px 10px">'
        +'<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">'
        +'<span style="background:rgba(59,130,246,.3);border-radius:4px;padding:1px 7px;font-size:9px;font-weight:800;color:var(--blue2);letter-spacing:.5px">CTe</span>'
        +'<code style="font-size:10.5px;color:var(--text);letter-spacing:.3px;user-select:all" title="'+cteFull+'">'+cteDisp+'</code>'
        +'<button onclick="navigator.clipboard.writeText(\''+cteFull+'\');this.textContent=\'✓ Copiado!\';setTimeout(()=>{this.textContent=\'⧉ Copiar\'},1500)" '
        +'style="background:rgba(59,130,246,.2);border:1px solid rgba(59,130,246,.4);color:var(--blue2);border-radius:4px;padding:2px 8px;font-size:9px;cursor:pointer;white-space:nowrap">⧉ Copiar</button>'
        +'<span style="font-size:10px;color:var(--text2);font-weight:600">'+trName(cg.transportadora||'-')+'</span>'
        +(cg.origem_cidade?'<span style="font-size:9px;color:var(--text3)">'+cg.origem_cidade+'/'+cg.origem_uf+' → '+cg.destino_cidade+'</span>':'')
        +'<span style="font-size:11px;color:var(--blue2);font-weight:700;margin-left:4px">'+BRL(cg.valor_frete_cte)+'</span>'
        +(cg.peso_kg?'<span style="font-size:9px;color:var(--text3)">'+N(cg.peso_kg)+' kg</span>':'')
        +'<span style="font-size:9px;color:var(--text3)">'+cg.nfes.length+' NF-e</span>'
        +'</div></td></tr>';
      const nfeRows=cg.nfes.map(d=>{
        const pct=d.total_nf?(d.valor_frete/d.total_nf*100):0;
        const pctCls=pct>10?'color:var(--red2)':pct>5?'color:var(--amber)':'color:var(--green2)';
        const nfeShort=d.chave_nfe?d.chave_nfe.slice(0,10)+'…'+d.chave_nfe.slice(-10):'--';
        const freteDisp=BRL(d.valor_frete)+(d.is_rateio?'<span style="font-size:8px;color:var(--text3);margin-left:2px">'+d.pct_rateio+'%</span>':'');
        return '<tr style="border-bottom:1px solid var(--bd);font-size:11px">'
          +'<td style="padding:5px 10px 5px 20px;color:var(--text2);white-space:nowrap">'+d.data+'</td>'
          +'<td style="font-family:monospace;font-size:10px;color:var(--text3)">'+d.numero+'</td>'
          +'<td style="color:var(--text);font-weight:600;white-space:nowrap">'+BRL(d.total_nf)+'</td>'
          +'<td style="color:var(--blue2);font-weight:700;white-space:nowrap">'+freteDisp+'</td>'
          +'<td style="font-weight:700;white-space:nowrap;'+pctCls+'">'+pct.toFixed(1)+'%</td>'
          +'<td style="font-size:10px;color:var(--text2)">'+(d.origem_cidade||'<span style="color:var(--text3)">-</span>')+'</td>'
          +'<td colspan="2" style="font-family:monospace;font-size:9px;color:var(--text3)" title="'+(d.chave_nfe||'')+'">'+nfeShort+'</td>'
          +'<td style="color:var(--text);font-weight:500;white-space:nowrap">'+(d.destino_cidade||'<span style="color:var(--text3)">-</span>')+'<span class="chip chip-gray" style="font-size:9px;margin-left:3px">'+(d.destino_uf||'-')+'</span></td>'
          +'</tr>';
      }).join('');
      return cteHdr+nfeRows;
    }).join('');
    const detPanel='<tr id="clidet-'+gkey+'" style="display:none"><td colspan="9" style="padding:0"><div style="background:#0D1525;border-top:1px solid var(--bd);padding:0"><table style="width:100%;border-collapse:collapse">'+detHeader+detRows+'</table></div></td></tr>';
    return mainRow+detPanel;
  }).join('');
  mkPager(display.length,cliPage,PAGE,'cli_pager',pg=>{cliPage=pg;renderCliTable();});
}
document.getElementById('cli_search').addEventListener('input',()=>{cliPage=0;renderCliTable();});

// ABA EMPRESA
const NAT_TRANSF=/TRANSFER|1-00005-0000002/i;
const HU_CLI=/HUMANA\s*ALIMENTAR/i;
const CNPJ_EMPRESA=DATA.cnpj_map||{};
function resolveEmpDest(d){ return CNPJ_EMPRESA[d.dest_cnpj]||CNPJ_EMPRESA[d.part_cnpj]||d.cliente||'?'; }
function isTransferencia(d){
  return NAT_TRANSF.test(d.nat_operacao||'')
      || NAT_TRANSF.test(d.cod_nat_operacao||'')
      || !!(d.dest_cnpj && CNPJ_EMPRESA[d.dest_cnpj]);
}
let _empTlRows=[];
function buildEmpTimeline(){
  const sel=document.getElementById('emp_tl_emp');
  if(!sel) return;
  const empF=sel.value;
  const subset=empF?_empTlRows.filter(d=>d.empresa===empF):_empTlRows;
  const byMP={};
  subset.forEach(d=>{
    const p=per(d.data);if(!p) return;
    const tr=trName(d.transportadora||'N/A');
    if(!byMP[p]) byMP[p]={};
    byMP[p][tr]=(byMP[p][tr]||0)+d.valor_frete;
  });
  const months=Object.keys(byMP).sort();
  const trTotals={};
  months.forEach(m=>Object.entries(byMP[m]).forEach(([tr,v])=>{trTotals[tr]=(trTotals[tr]||0)+v;}));
  const top5=Object.entries(trTotals).sort((a,b)=>b[1]-a[1]).slice(0,5).map(([tr])=>tr);
  const ds=top5.map((tr,i)=>({
    label:tr,data:months.map(m=>byMP[m][tr]||0),
    backgroundColor:COLORS[i],borderRadius:3,
  }));
  ds.push({label:'Outros',data:months.map(m=>{
    const s=top5.reduce((a,tr)=>a+(byMP[m][tr]||0),0);
    const tot=Object.values(byMP[m]).reduce((a,v)=>a+v,0);
    return Math.max(0,tot-s);
  }),backgroundColor:'rgba(255,255,255,.1)',borderRadius:3});
  mkStacked('ch_emp_tl',months.map(p=>perL(p)),ds);
}
function renderEmpresa(){
  // Exclui marketplace (mesma regra da Visao Geral)
  const rows=filterRows(DATA.detalhes,{excMkt:true,onlyMkt:false});
  const byEmp={},trGlobal={};
  rows.forEach(d=>{
    const emp=d.empresa||'N/A',tr=d.transportadora||'N/A',fr=d.valor_frete;
    if(!byEmp[emp]) byEmp[emp]={qtd:0,frete:0,trs:{}};
    byEmp[emp].qtd++;byEmp[emp].frete+=fr;
    if(!byEmp[emp].trs[tr]) byEmp[emp].trs[tr]={qtd:0,frete:0};
    byEmp[emp].trs[tr].qtd++;byEmp[emp].trs[tr].frete+=fr;
    trGlobal[tr]=(trGlobal[tr]||0)+fr;
  });
  const empList=Object.entries(byEmp)
    .map(([emp,v])=>({emp,...v,trList:Object.entries(v.trs).map(([tr,tv])=>({tr,...tv})).sort((a,b)=>b.frete-a.frete)}))
    .sort((a,b)=>b.frete-a.frete);
  const totalG=empList.reduce((s,e)=>s+e.frete,0)||1;
  document.getElementById('emp_k_qtd').textContent=N(empList.length);
  document.getElementById('tb_emp').textContent=N(empList.length);
  const top=empList[0];
  if(top){
    document.getElementById('emp_k_top_emp').textContent=top.emp;
    document.getElementById('emp_k_top_val').textContent=BRL(top.frete);
    const topTr=top.trList[0];
    if(topTr){
      document.getElementById('emp_k_top_transp').textContent=trName(topTr.tr);
      document.getElementById('emp_k_top_transp_pct').textContent=(topTr.frete/top.frete*100).toFixed(1)+'% do frete da empresa';
    }
  }
  mkBar('ch_emp_frete',empList.map(e=>e.emp),empList.map(e=>e.frete),'#3B82F6');
  const top5Tr=Object.entries(trGlobal).sort((a,b)=>b[1]-a[1]).slice(0,5).map(([tr])=>tr);
  const stackDs=top5Tr.map((tr,i)=>({label:trName(tr),data:empList.map(e=>(e.trs[tr]||{frete:0}).frete),backgroundColor:COLORS[i],borderRadius:3}));
  stackDs.push({label:'Outros',data:empList.map(e=>{const s=top5Tr.reduce((a,tr)=>a+(e.trs[tr]||{frete:0}).frete,0);return Math.max(0,e.frete-s);}),backgroundColor:'rgba(255,255,255,.12)',borderRadius:3});
  mkStacked('ch_emp_stacked',empList.map(e=>e.emp),stackDs);
  document.getElementById('emp_tbody').innerHTML=empList.map((e,i)=>{
    const topTr=e.trList[0]||{tr:'-',frete:0};
    const pctTot=(e.frete/totalG*100).toFixed(1);const pctConc=e.frete?(topTr.frete/e.frete*100).toFixed(1):'0.0';
    const cC=+pctConc>70?'tr':+pctConc>50?'ty':'tg';
    return '<tr><td style="color:var(--text3);font-weight:700;font-size:10px">'+(i+1)+'</td>'
      +'<td><strong>'+e.emp+'</strong></td><td>'+N(e.qtd)+'</td>'
      +'<td style="color:var(--text);font-weight:600">'+BRL(e.frete)+'</td>'
      +'<td><div style="display:flex;align-items:center;gap:6px"><div style="width:'+Math.min(+pctTot*4,100)+'px;height:3px;background:var(--blue);border-radius:2px;opacity:.8"></div><span>'+pctTot+'%</span></div></td>'
      +'<td title="Principal por valor pago — '+trName(topTr.tr)+' recebeu '+pctConc+'% do custo de frete desta empresa">'+trName(topTr.tr)+'<span style="font-size:9px;color:var(--text3);margin-left:4px">(por valor)</span></td>'
      +'<td>'+BRL(topTr.frete)+' <span style="font-size:9px;color:var(--text3)">('+N(topTr.qtd)+' NF)</span></td>'
      +'<td><span class="tag '+cC+'">'+pctConc+'%</span></td>'
      +'<td>'+N(e.trList.length)+'</td></tr>';
  }).join('');
  const det=[];
  empList.forEach(e=>{
    e.trList.slice(0,5).forEach((t,j)=>{
      const pE=e.frete?(t.frete/e.frete*100).toFixed(1):'0.0';const pT=(t.frete/totalG*100).toFixed(1);
      det.push('<tr><td>'+(j===0?'<strong>'+e.emp+'</strong>':'')+'</td>'
        +'<td title="'+t.tr+'">'+trName(t.tr)+'</td>'
        +'<td>'+N(t.qtd)+'</td><td style="color:var(--text);font-weight:600">'+BRL(t.frete)+'</td>'
        +'<td>'+pE+'%</td><td style="color:var(--text3)">'+pT+'%</td></tr>');
    });
    if(e.trList.length>5){
      const of=e.trList.slice(5).reduce((s,t)=>s+t.frete,0);const oq=e.trList.slice(5).reduce((s,t)=>s+t.qtd,0);
      det.push('<tr style="color:var(--text3);font-size:11px"><td></td><td>+ '+(e.trList.length-5)+' outras</td><td>'+N(oq)+'</td><td>'+BRL(of)+'</td><td>'+(e.frete?(of/e.frete*100).toFixed(1):0)+'%</td><td>-</td></tr>');
    }
  });
  document.getElementById('emp_det_tbody').innerHTML=det.join('');

  // ── Frete Comercial vs Operacional ──────────────────────────────────────
  const rowsCom=rows.filter(d=>!isTransferencia(d));
  const rowsOp =rows.filter(d=> isTransferencia(d));
  const totCom=rowsCom.reduce((s,d)=>s+d.valor_frete,0);
  const totOp =rowsOp.reduce((s,d)=>s+d.valor_frete,0);
  const totAll=totCom+totOp||1;
  // Total de transferências no faturamento (com ou sem CTe) respeitando filtros ativos
  let _totalTransfFat=0;
  const _tf=DATA.transf_fat||{};
  Object.entries(_tf).forEach(([k,cnt])=>{
    const [emp,ano,mes]=k.split('||');
    if(state.empresa&&emp!==state.empresa) return;
    if(state.ano&&ano!==state.ano) return;
    if(state.mes&&mes!==state.mes) return;
    _totalTransfFat+=cnt;
  });
  document.getElementById('emp_frete_com').textContent=BRL(totCom);
  document.getElementById('emp_frete_com_sub').textContent=N(rowsCom.length)+' NF-e de venda';
  document.getElementById('emp_frete_op').textContent=BRL(totOp);
  document.getElementById('emp_frete_op_sub').textContent=N(rowsOp.length)+' NF-e de transferência';
  document.getElementById('emp_qtd_transf').textContent=N(rowsOp.length);
  document.getElementById('emp_qtd_transf_fat').textContent=N(_totalTransfFat)+' no faturamento';
  document.getElementById('emp_pct_op').textContent=(totOp/totAll*100).toFixed(1)+'%';
  // Destinos das transferências com CTe vinculado
  const _byDest={};
  rowsOp.forEach(d=>{const dest=resolveEmpDest(d);_byDest[dest]=(_byDest[dest]||0)+1;});
  const _destEntries=Object.entries(_byDest).sort((a,b)=>b[1]-a[1]);
  const _lbl=state.empresa?'Destinos de '+state.empresa+' (com CTe):':'Destinos das transferências (com CTe):';
  document.getElementById('emp_transf_destinos_lbl').textContent=_lbl;
  document.getElementById('emp_transf_destinos').innerHTML=_destEntries.length
    ?_destEntries.map(([k,v])=>'<span class="chip chip-gray" style="font-size:10px"><b>'+k+'</b>: '+N(v)+'</span>').join('')
    :'<span style="color:var(--text3)">—</span>';

  // Gráfico Comercial vs Operacional por empresa
  const allEmps2=[...new Set(rows.map(d=>d.empresa).filter(Boolean))].sort();
  const byCom={},byOp2={};
  rowsCom.forEach(d=>{const e=d.empresa||'?'; byCom[e]=(byCom[e]||0)+d.valor_frete;});
  rowsOp.forEach(d=>{const e=d.empresa||'?';  byOp2[e]=(byOp2[e]||0)+d.valor_frete;});
  mkGrouped('ch_emp_tipo',allEmps2,[
    {label:'Comercial (Vendas)',data:allEmps2.map(e=>byCom[e]||0),backgroundColor:'#3B82F6',borderRadius:3},
    {label:'Operacional (Transf.)',data:allEmps2.map(e=>byOp2[e]||0),backgroundColor:'#7C3AED',borderRadius:3},
  ]);

  // Tabela operacional por empresa: agrupa transferências por empresa (origem)
  // Mostra destino principal pelo UF do CTe (mais confiável que o nome do cliente)
  const opByEmp={};
  rowsOp.forEach(d=>{
    const emp=d.empresa||'?';
    if(!opByEmp[emp]) opByEmp[emp]={qtd:0,frete:0,destUfs:{},freTotal:0};
    opByEmp[emp].qtd++;opByEmp[emp].frete+=d.valor_frete;
    if(d.destino_uf){opByEmp[emp].destUfs[d.destino_uf]=(opByEmp[emp].destUfs[d.destino_uf]||0)+1;}
  });
  // % do frete total por empresa (inclui comercial+operacional)
  const freByEmp={};rows.forEach(d=>{const e=d.empresa||'?';freByEmp[e]=(freByEmp[e]||0)+d.valor_frete;});
  const opList=Object.entries(opByEmp)
    .map(([emp,v])=>{
      const topUf=Object.entries(v.destUfs).sort((a,b)=>b[1]-a[1])[0];
      return{emp,qtd:v.qtd,frete:v.frete,pctEmp:freByEmp[emp]?(v.frete/freByEmp[emp]*100):0,topUf:topUf?topUf[0]:'-',ticket:v.qtd?v.frete/v.qtd:0};
    }).sort((a,b)=>b.frete-a.frete);
  document.getElementById('emp_transf_tbody').innerHTML=opList.length
    ?opList.map(o=>{
        const pC=o.pctEmp>30?'color:var(--red2)':o.pctEmp>15?'color:var(--amber)':'color:var(--green2)';
        return'<tr>'
          +'<td><strong>'+o.emp+'</strong></td>'
          +'<td style="text-align:center">'+N(o.qtd)+'</td>'
          +'<td style="color:var(--purple2);font-weight:600">'+BRL(o.frete)+'</td>'
          +'<td><span style="font-weight:700;'+pC+'">'+o.pctEmp.toFixed(1)+'%</span><span style="color:var(--text3);font-size:10px"> do frete total</span></td>'
          +'<td style="text-align:center"><span class="chip chip-gray" style="font-size:10px">'+o.topUf+'</span></td>'
          +'<td style="color:var(--text2)">'+BRL(o.ticket)+'</td>'
          +'</tr>';}).join('')
    :'<tr><td colspan="6" style="text-align:center;color:var(--text3);padding:20px">Nenhuma transferência no período selecionado</td></tr>';

  // ── Banner de período ──────────────────────────────────────────────────────
  const parts=[];
  if(state.ano) parts.push(state.ano);
  if(state.mes) parts.push(MESES[+state.mes]);
  if(state.empresa) parts.push(state.empresa);
  if(state.linha) parts.push(state.linha);
  if(state.canal) parts.push('Canal: '+state.canal);
  if(state.estado) parts.push('UF: '+state.estado);
  if(state.transp) parts.push('Transp: '+trName(state.transp));
  document.getElementById('emp_periodo_txt').innerHTML=
    (parts.length
      ? '<strong>Exibindo:</strong> '+parts.join(' · ')
      : '<strong>Exibindo:</strong> Todos os períodos · Todas as empresas')
    +' &nbsp;<span style="color:var(--text3);font-size:11px">('+N(rows.length)+' NF-e vinculadas)</span>';

  // ── Transferências entre Lojas do Grupo ───────────────────────────────────
  const rowsHu=rows.filter(d=>HU_CLI.test(d.cliente||''));
  const totHuFrete=rowsHu.reduce((s,d)=>s+d.valor_frete,0);
  const totFreteGlobal=rows.reduce((s,d)=>s+d.valor_frete,0)||1;
  document.getElementById('emp_hu_qtd').textContent=N(rowsHu.length);
  document.getElementById('emp_hu_frete').textContent=BRL(totHuFrete);
  document.getElementById('emp_hu_pct').textContent=(totHuFrete/totFreteGlobal*100).toFixed(1)+'% do frete total';
  document.getElementById('emp_hu_ticket').textContent=rowsHu.length?BRL(totHuFrete/rowsHu.length):'-';
  const huMap={};
  rowsHu.forEach(d=>{
    const k=(d.empresa||'?')+'||'+(d.cliente||'?');
    if(!huMap[k]) huMap[k]={emp:d.empresa||'?',cli:d.cliente||'?',qtd:0,frete:0,uf:d.destino_uf||'-'};
    huMap[k].qtd++;huMap[k].frete+=d.valor_frete;
    if(d.destino_uf) huMap[k].uf=d.destino_uf;
  });
  const huList=Object.values(huMap).sort((a,b)=>b.frete-a.frete);
  document.getElementById('emp_hu_tbody').innerHTML=huList.length
    ?huList.map(h=>{
      const pct=freByEmp[h.emp]?(h.frete/freByEmp[h.emp]*100).toFixed(1):'-';
      return'<tr>'
        +'<td><strong>'+h.emp+'</strong></td>'
        +'<td style="font-size:11px;color:var(--text2)">'+h.cli+'</td>'
        +'<td style="text-align:center">'+N(h.qtd)+'</td>'
        +'<td style="color:var(--amber);font-weight:600">'+BRL(h.frete)+'</td>'
        +'<td>'+pct+'%</td>'
        +'<td><span class="chip chip-gray" style="font-size:10px">'+h.uf+'</span></td>'
        +'<td style="color:var(--text2)">'+BRL(h.qtd?h.frete/h.qtd:0)+'</td>'
        +'</tr>';}).join('')
    :'<tr><td colspan="7" style="text-align:center;color:var(--text3);padding:20px">Nenhuma transferência interna no período selecionado</td></tr>';

  // ── NF-e de transferência sem CTe ────────────────────────────────────────
  const _tscRows=(DATA.transf_sem_cte||[]).filter(d=>{
    if(state.empresa&&d.empresa!==state.empresa) return false;
    if(state.ano&&(d.data||'').slice(6,10)!==state.ano) return false;
    if(state.mes&&(d.data||'').slice(3,5)!==state.mes) return false;
    return true;
  });
  document.getElementById('emp_transf_sem_cte_tbody').innerHTML=_tscRows.length
    ?_tscRows.sort((a,b)=>a.data.localeCompare(b.data)).map(d=>{
        const dest=CNPJ_EMPRESA[d.part_cnpj]||d.cliente||'?';
        return'<tr>'
          +'<td style="font-size:11px">'+d.numero+'</td>'
          +'<td style="font-size:11px">'+d.data+'</td>'
          +'<td><strong>'+d.empresa+'</strong></td>'
          +'<td style="font-size:11px">'+dest+'</td>'
          +'<td style="font-size:11px"><span class="chip chip-gray">'+d.cidade+'/'+d.estado+'</span></td>'
          +'<td style="font-size:10px;color:var(--text3)">'+d.nat_operacao+'</td>'
          +'<td style="text-align:right;color:var(--text2)">'+BRL(d.total_nf)+'</td>'
          +'</tr>';}).join('')
    :'<tr><td colspan="7" style="text-align:center;color:var(--text3);padding:16px">Nenhuma transferência sem CTe no período selecionado</td></tr>';

  // ── Timeline Transportadora × Mês ────────────────────────────────────────
  _empTlRows=rows;
  const empTlSel=document.getElementById('emp_tl_emp');
  const curEmpTl=empTlSel.value;
  empTlSel.innerHTML='<option value="">Todas as empresas</option>';
  empList.forEach(e=>{
    const o=document.createElement('option');o.value=e.emp;o.textContent=e.emp;
    if(e.emp===curEmpTl) o.selected=true;
    empTlSel.appendChild(o);
  });
  buildEmpTimeline();
}

// ABA CTe NAO VINCULADOS (exclui marketplace — esses ficam na aba Marketplace)
const nvBase=DATA.ctes_nao_vinculados.filter(c=>!isMarketplace(c.transportadora));
let nvPage=0;let nvRows=nvBase;
const nvSelUf=document.getElementById('nv_uf');
const nvSelTr=document.getElementById('nv_transp');
const nvInp=document.getElementById('nv_search');
[...new Set(nvBase.map(c=>c.destino_uf).filter(Boolean))].sort()
  .forEach(uf=>{const o=document.createElement('option');o.value=uf;o.textContent=uf;nvSelUf.appendChild(o);});
[...new Set(nvBase.map(c=>c.transportadora).filter(Boolean))].sort()
  .forEach(t=>{const o=document.createElement('option');o.value=t;o.textContent=trName(t);nvSelTr.appendChild(o);});
function nvFilter(){
  const q=nvInp.value.toLowerCase(),uf=nvSelUf.value,tr=nvSelTr.value;
  nvRows=nvBase.filter(c=>{
    if(uf&&c.destino_uf!==uf) return false;
    if(tr&&c.transportadora!==tr) return false;
    if(q){const h=(c.cte_chave+' '+c.transportadora+' '+c.origem_cidade+' '+c.destino_cidade).toLowerCase();if(!h.includes(q)) return false;}
    return true;
  });
  nvPage=0;nvRender();
}
function nvRender(){
  const tbody=document.getElementById('nv_tbody');
  const slice=nvRows.slice(nvPage*PAGE,nvPage*PAGE+PAGE);
  tbody.innerHTML=slice.map(c=>'<tr>'
    +'<td style="font-family:monospace;font-size:10px;color:var(--text3)">'+c.cte_chave+'</td>'
    +'<td>'+(c.data_emissao||'-')+'</td>'
    +'<td title="'+(c.transportadora||'')+'">'+trName(c.transportadora||'-')+'</td>'
    +'<td style="font-size:10px">'+(c.origem_cidade||'')+(c.origem_uf?'/'+c.origem_uf:'')+'</td>'
    +'<td style="font-size:10px">'+(c.destino_cidade||'')+(c.destino_uf?'/'+c.destino_uf:'')+'</td>'
    +'<td style="color:var(--blue2);font-weight:600">'+BRL(c.valor_frete)+'</td>'
    +'<td style="font-size:11px;color:var(--yellow)"><i class="fa-solid fa-triangle-exclamation"></i>'+(c.motivo||'Motivo não identificado')+'</td></tr>').join('');
  mkPager(nvRows.length,nvPage,PAGE,'nv_pager',pg=>{nvPage=pg;nvRender();});
}
nvInp.addEventListener('input',nvFilter);nvSelUf.addEventListener('change',nvFilter);nvSelTr.addEventListener('change',nvFilter);
nvRender();
// KPIs — CTe sem vínculo
document.getElementById('nv_k_qtd').textContent=N(nvBase.length);
document.getElementById('nv_k_frete').textContent=BRL(nvBase.reduce((s,c)=>s+c.valor_frete,0));
document.getElementById('nv_k_transp').textContent=N(new Set(nvBase.map(c=>c.transportadora).filter(Boolean)).size);
document.getElementById('nv_k_nferefs').textContent=N(nvBase.reduce((s,c)=>s+(c.nfe_refs||[]).length,0));

// CTe cancelados
(function(){
  const cancelData=DATA.cancelados_data||[];
  const chaves=DATA.cte_cancelados_chaves||[];
  // KPIs
  document.getElementById('cancel_k_qtd').textContent=N(cancelData.length);
  document.getElementById('cancel_k_frete').textContent=BRL(cancelData.reduce((s,c)=>s+c.valor_frete,0));
  document.getElementById('cancel_k_transp').textContent=N(new Set(cancelData.map(c=>c.transportadora).filter(Boolean)).size);
  // Tabela
  const tbody=document.getElementById('cancel_tbody');
  const wrap=document.getElementById('cancel_list_wrap');
  const empty=document.getElementById('cancel_empty');
  if(!chaves.length){wrap.style.display='none';empty.style.display='block';return;}
  tbody.innerHTML=cancelData.map(c=>'<tr>'
    +'<td style="font-family:monospace;font-size:10px;color:var(--text)">'+c.cte_chave+'</td>'
    +'<td style="font-size:10px;color:var(--text2);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="'+c.transportadora+'">'+trName(c.transportadora||'-')+'</td>'
    +'<td style="color:var(--red2);font-weight:600;white-space:nowrap">'+BRL(c.valor_frete)+'</td>'
    +'<td style="text-align:center"><button onclick="navigator.clipboard.writeText(\''+c.cte_chave+'\');this.textContent=\'✓\';setTimeout(()=>{this.textContent=\'⧉ Copiar\'},1500)" '
    +'style="background:rgba(239,68,68,.15);border:1px solid rgba(239,68,68,.4);color:var(--red2);border-radius:4px;padding:2px 8px;font-size:9px;cursor:pointer">⧉ Copiar</button></td>'
    +'</tr>').join('');
})();

// ── ABA COMPRAS ──────────────────────────────────────────────────────────────
let compPage=0;
const compInp=document.getElementById('comp_search');
const compSelEmp=document.getElementById('comp_sel_emp');

// Popula filtro de empresa
(()=>{
  const emps=[...new Set((DATA.compras||[]).map(d=>d.empresa_dest).filter(Boolean))].sort();
  emps.forEach(e=>{const o=document.createElement('option');o.value=e;o.textContent=e;compSelEmp.appendChild(o);});
})();

function compFilter(){compPage=0;renderCompras();}
function renderCompras(){
  const rows=(DATA.compras||[]).filter(d=>{
    const empOk=(!compSelEmp.value||d.empresa_dest===compSelEmp.value)
               &&(!state.empresa||d.empresa_dest===state.empresa);
    const anoOk=!state.ano||(d.data_emissao||'').slice(0,4)===state.ano;
    const mesOk=!state.mes||(d.data_emissao||'').slice(5,7)===state.mes;
    const q=(compInp.value||'').toLowerCase();
    const qOk=!q||(d.rem_nome||'').toLowerCase().includes(q)
      ||(d.origem_cidade||'').toLowerCase().includes(q)
      ||(d.transportadora||'').toLowerCase().includes(q)
      ||(d.cte_chave||'').includes(q)
      ||(d.nfe_refs||[]).some(n=>n.includes(q));
    return empOk&&anoOk&&mesOk&&qOk;
  });

  // KPIs
  const totFrete=rows.reduce((s,d)=>s+d.valor_frete,0);
  const totPeso=rows.reduce((s,d)=>s+d.peso_kg,0);
  document.getElementById('comp_qtd').textContent=N(rows.length);
  document.getElementById('comp_frete').textContent=BRL(totFrete);
  document.getElementById('comp_peso').textContent=N(Math.round(totPeso))+' kg';
  document.getElementById('comp_frete_medio').textContent=rows.length?BRL(totFrete/rows.length):'R$ 0';

  // Tabela paginada
  const PAGE=50;
  const slice=rows.slice(compPage*PAGE,(compPage+1)*PAGE);
  const tbody=document.getElementById('comp_tbody');
  tbody.innerHTML=slice.map(d=>{
    const orig=(d.origem_cidade||'?')+(d.origem_uf?'/'+d.origem_uf:'');
    const dest=(d.destino_cidade||'?')+(d.destino_uf?'/'+d.destino_uf:'');
    const nfeChips=(d.nfe_refs||[]).slice(0,3).map(ch=>`<span class="chip chip-gray" style="font-size:9px;font-family:monospace" title="${ch}">${ch.slice(25,34)}…</span>`).join(' ')
      +((d.nfe_refs||[]).length>3?`<span style="font-size:9px;color:var(--text3)"> +${(d.nfe_refs||[]).length-3}</span>`:'');
    const vol=d.volume_m3?d.volume_m3.toFixed(3):'—';
    const data=(d.data_emissao||'').slice(0,10)||'—';
    return '<tr style="border-bottom:1px solid var(--row-border)">'
      +'<td style="padding:7px 10px;white-space:nowrap;color:var(--text3);font-size:10px">'+data+'</td>'
      +'<td style="padding:7px 10px;max-width:200px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--text);font-weight:600" title="'+(d.rem_nome||'')+'">'+( d.rem_nome||'<span style="color:var(--text3)">—</span>')+'</td>'
      +'<td style="padding:7px 10px;white-space:nowrap;color:var(--text2)">'+orig+'</td>'
      +'<td style="padding:7px 10px;white-space:nowrap;color:var(--text2)">'+dest+'</td>'
      +'<td style="padding:7px 10px"><span class="chip chip-blue" style="font-size:10px;font-weight:700">'+(d.empresa_dest||'?')+'</span></td>'
      +'<td style="padding:7px 10px;max-width:180px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--text3);font-size:10px" title="'+(d.transportadora||'')+'">'+( d.transportadora||'—')+'</td>'
      +'<td style="padding:7px 10px">'+( nfeChips||'<span style="color:var(--text3);font-size:10px">sem NF-e</span>')+'</td>'
      +'<td style="padding:7px 10px;text-align:right;color:var(--text);font-weight:700;white-space:nowrap">'+BRL(d.valor_frete)+'</td>'
      +'<td style="padding:7px 10px;text-align:right;color:var(--text2);white-space:nowrap">'+N(Math.round(d.peso_kg))+'</td>'
      +'<td style="padding:7px 10px;text-align:right;color:var(--text2);white-space:nowrap">'+vol+'</td>'
      +'</tr>';
  }).join('');
  mkPager(rows.length,compPage,PAGE,'comp_pager',pg=>{compPage=pg;renderCompras();});
}
compInp.addEventListener('input',compFilter);
compSelEmp.addEventListener('change',compFilter);

// ── ABA DEVOLUÇÃO MARKETPLACE ─────────────────────────────────────────────────
let dmPage=0;
const dmInp=document.getElementById('dm_search');
const dmSelPlat=document.getElementById('dm_sel_plat');
const dmSelEmp=document.getElementById('dm_sel_emp');

(()=>{
  const emps=[...new Set((DATA.devolucoes_mkt||[]).map(d=>d.empresa_dest).filter(Boolean))].sort();
  emps.forEach(e=>{const o=document.createElement('option');o.value=e;o.textContent=e;dmSelEmp.appendChild(o);});
})();

function dmFilter(){dmPage=0;renderDevMkt();}
function renderDevMkt(){
  const base=(DATA.devolucoes_mkt||[]).filter(d=>{
    const platOk=!dmSelPlat.value||d.mkt_type===dmSelPlat.value;
    const empOk=(!dmSelEmp.value||d.empresa_dest===dmSelEmp.value)
               &&(!state.empresa||d.empresa_dest===state.empresa);
    const anoOk=!state.ano||(d.data_emissao||'').slice(0,4)===state.ano;
    const mesOk=!state.mes||(d.data_emissao||'').slice(5,7)===state.mes;
    const q=(dmInp.value||'').toLowerCase();
    const qOk=!q||(d.rem_nome||'').toLowerCase().includes(q)
      ||(d.origem_cidade||'').toLowerCase().includes(q)
      ||(d.empresa_dest||'').toLowerCase().includes(q)
      ||(d.nfe_refs||[]).some(n=>n.includes(q));
    return platOk&&empOk&&anoOk&&mesOk&&qOk;
  });

  // KPIs por plataforma (sempre sobre o total, sem filtro de plataforma)
  const allBase=(DATA.devolucoes_mkt||[]).filter(d=>{
    const anoOk=!state.ano||(d.data_emissao||'').slice(0,4)===state.ano;
    const mesOk=!state.mes||(d.data_emissao||'').slice(5,7)===state.mes;
    return anoOk&&mesOk;
  });
  const ml=allBase.filter(d=>d.mkt_type==='ml');
  const sh=allBase.filter(d=>d.mkt_type==='shopee');
  const kpi=(id,val)=>{const el=document.getElementById(id);if(el)el.textContent=val;};
  kpi('dm_ml_qtd',N(ml.length));
  kpi('dm_ml_frete',BRL(ml.reduce((s,d)=>s+d.valor_frete,0)));
  kpi('dm_ml_peso',N(Math.round(ml.reduce((s,d)=>s+d.peso_kg,0)))+' kg');
  kpi('dm_ml_medio',ml.length?BRL(ml.reduce((s,d)=>s+d.valor_frete,0)/ml.length):'R$ 0');
  kpi('dm_sh_qtd',N(sh.length));
  kpi('dm_sh_frete',BRL(sh.reduce((s,d)=>s+d.valor_frete,0)));
  kpi('dm_sh_peso',N(Math.round(sh.reduce((s,d)=>s+d.peso_kg,0)))+' kg');
  kpi('dm_sh_medio',sh.length?BRL(sh.reduce((s,d)=>s+d.valor_frete,0)/sh.length):'R$ 0');

  // Tabela
  const PAGE=50;
  const slice=base.slice(dmPage*PAGE,(dmPage+1)*PAGE);
  const platChip=t=>t==='ml'
    ?'<span class="chip" style="background:#FFE60022;color:#FFE600;font-size:9px;font-weight:700">ML</span>'
    :'<span class="chip" style="background:#FF690022;color:#FF6900;font-size:9px;font-weight:700">Shopee</span>';
  document.getElementById('dm_tbody').innerHTML=slice.map(d=>{
    const orig=(d.origem_cidade||'?')+(d.origem_uf?'/'+d.origem_uf:'');
    const dest=(d.destino_cidade||'?')+(d.destino_uf?'/'+d.destino_uf:'');
    const nfeChips=(d.nfe_refs||[]).slice(0,3).map(ch=>`<span class="chip chip-gray" style="font-size:9px;font-family:monospace" title="${ch}">${ch.slice(25,34)}…</span>`).join(' ')
      +((d.nfe_refs||[]).length>3?`<span style="font-size:9px;color:var(--text3)"> +${(d.nfe_refs||[]).length-3}</span>`:'');
    const vol=d.volume_m3?d.volume_m3.toFixed(3):'—';
    return '<tr style="border-bottom:1px solid var(--row-border)">'
      +'<td style="padding:7px 10px">'+platChip(d.mkt_type)+'</td>'
      +'<td style="padding:7px 10px;white-space:nowrap;color:var(--text3);font-size:10px">'+((d.data_emissao||'').slice(0,10)||'—')+'</td>'
      +'<td style="padding:7px 10px;max-width:200px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--text2)" title="'+(d.rem_nome||orig)+'">'+( d.rem_nome||orig)+'</td>'
      +'<td style="padding:7px 10px;white-space:nowrap;color:var(--text2)">'+dest+'</td>'
      +'<td style="padding:7px 10px"><span class="chip chip-blue" style="font-size:10px;font-weight:700">'+(d.empresa_dest||'?')+'</span></td>'
      +'<td style="padding:7px 10px">'+( nfeChips||'<span style="color:var(--text3);font-size:10px">sem NF-e</span>')+'</td>'
      +'<td style="padding:7px 10px;text-align:right;color:var(--text);font-weight:700;white-space:nowrap">'+BRL(d.valor_frete)+'</td>'
      +'<td style="padding:7px 10px;text-align:right;color:var(--text2);white-space:nowrap">'+N(Math.round(d.peso_kg))+'</td>'
      +'<td style="padding:7px 10px;text-align:right;color:var(--text2);white-space:nowrap">'+vol+'</td>'
      +'</tr>';
  }).join('');
  mkPager(base.length,dmPage,PAGE,'dm_pager',pg=>{dmPage=pg;renderDevMkt();});
}
dmInp.addEventListener('input',dmFilter);
dmSelPlat.addEventListener('change',dmFilter);
dmSelEmp.addEventListener('change',dmFilter);

// TABS
document.querySelectorAll('.tab-btn').forEach(btn=>{
  btn.addEventListener('click',()=>{
    const tab=btn.dataset.tab;
    document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p=>p.classList.remove('active'));
    btn.classList.add('active');document.getElementById('tab-'+tab).classList.add('active');
    if(tab==='empresa') renderEmpresa();
    else if(tab==='marketplace') renderMarketplace();
    else if(tab==='clientes') renderClientes();
    else if(tab==='compras') renderCompras();
    else if(tab==='dev-mkt') renderDevMkt();
    else if(tab==='operacional') renderTable();
  });
});

// FLOATING HORIZONTAL SCROLLBAR
(function(){
  const wrap=document.getElementById('details_wrap');
  const bar=document.getElementById('float-hscroll');
  const inner=document.getElementById('float-hscroll-inner');
  if(!wrap) return;
  let syncing=false;
  function syncWidth(){
    inner.style.width=wrap.scrollWidth+'px';
    const r=wrap.getBoundingClientRect();
    bar.style.left=r.left+'px';bar.style.width=r.width+'px';
  }
  function updateVisibility(){
    const r=wrap.getBoundingClientRect();
    const tableVisible=r.top<window.innerHeight&&r.bottom>0;
    const nativeVisible=r.bottom<=window.innerHeight+2;
    bar.style.display=(tableVisible&&!nativeVisible)?'block':'none';
    if(tableVisible&&!nativeVisible){bar.style.left=r.left+'px';bar.style.width=r.width+'px';}
  }
  new ResizeObserver(()=>{syncWidth();updateVisibility();}).observe(wrap);
  window.addEventListener('scroll',updateVisibility,{passive:true});
  window.addEventListener('resize',()=>{syncWidth();updateVisibility();},{passive:true});
  bar.addEventListener('scroll',()=>{if(syncing)return;syncing=true;wrap.scrollLeft=bar.scrollLeft;syncing=false;});
  wrap.addEventListener('scroll',()=>{if(syncing)return;syncing=true;bar.scrollLeft=wrap.scrollLeft;syncing=false;});
})();

// TEMA DARK / OCEAN
function toggleTheme(){
  const isOcean=document.documentElement.classList.toggle('ocean');
  document.getElementById('theme-toggle').textContent=isOcean?'🌑':'🌊';
  document.getElementById('theme-toggle').title=isOcean?'Alternar para tema escuro':'Alternar para tema Ocean';
  localStorage.setItem('frete-theme',isOcean?'ocean':'dark');
}
(function(){
  if(localStorage.getItem('frete-theme')==='ocean'){
    document.documentElement.classList.add('ocean');
    const btn=document.getElementById('theme-toggle');
    if(btn){btn.textContent='🌑';btn.title='Alternar para tema escuro';}
  }
})();

// INIT
try{
  document.getElementById('hd_gen').textContent='Gerado em '+DATA.gerado_em;
  document.getElementById('tb_naov').textContent=N(nvBase.length);
  document.getElementById('tb_emp').textContent=N([...new Set(DATA.detalhes.map(d=>d.empresa).filter(Boolean))].length);
  document.getElementById('tb_comp').textContent=N((DATA.compras||[]).length);
  document.getElementById('tb_devmkt').textContent=N((DATA.devolucoes_mkt||[]).length);
  renderAll();
}catch(err){console.error('[FRETE DASH] Erro na inicializacao:',err);}
</script>
</body>
</html>"""


# ─── Firebase Upload ──────────────────────────────────────────────────────────
def split_by_empresa(dados):
    """Divide dados em {empresa: dados_filtrados} para upload individual."""
    empresas = set()
    empresas.update(d.get("empresa","") for d in dados.get("detalhes",[]) if d.get("empresa"))
    empresas.update(d.get("empresa_dest","") for d in dados.get("compras",[]) if d.get("empresa_dest"))
    empresas.update(d.get("empresa_dest","") for d in dados.get("devolucoes_mkt",[]) if d.get("empresa_dest"))
    result = {}
    for emp in sorted(empresas):
        det = [d for d in dados.get("detalhes",[]) if d.get("empresa")==emp]
        total_frete = sum(d.get("valor_frete",0) for d in det)
        qtd = len(det)
        result[emp] = {
            "empresa": emp,
            "gerado_em": dados.get("gerado_em",""),
            "cnpj_map": dados.get("cnpj_map",{}),
            "por_nat_op": dados.get("por_nat_op",[]),
            "ctes_nao_vinculados": dados.get("ctes_nao_vinculados",[]),
            "cancelados_data": dados.get("cancelados_data",[]),
            "cte_cancelados_chaves": dados.get("cte_cancelados_chaves",[]),
            "detalhes": det,
            "compras": [d for d in dados.get("compras",[]) if d.get("empresa_dest")==emp],
            "devolucoes_mkt": [d for d in dados.get("devolucoes_mkt",[]) if d.get("empresa_dest")==emp],
            "transf_sem_cte": [d for d in dados.get("transf_sem_cte",[]) if d.get("empresa")==emp],
            "transf_fat": {k:v for k,v in dados.get("transf_fat",{}).items() if k.startswith(emp+"||")},
            "resumo": {
                **dados.get("resumo",{}),
                "valor_total_frete": round(total_frete,2),
                "media_frete": round(total_frete/qtd,2) if qtd else 0,
                "nfe_com_cte": qtd,
                "total_faturamento": round(sum(d.get("total_nf",0) for d in det),2),
            },
        }
    return result


def upload_to_firestore(empresa_data, dados_completos):
    """Faz upload dos dados por empresa para Firebase Firestore."""
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore as fb_firestore
    except ImportError:
        print("\n[AVISO] firebase-admin nao instalado. Execute: pip install firebase-admin")
        print("        Upload pulado.")
        return False

    key_path = os.path.join(BASE_DIR, "serviceAccountKey.json")
    if not os.path.exists(key_path):
        print(f"\n[AVISO] serviceAccountKey.json nao encontrado em {BASE_DIR}")
        print("        Baixe em Firebase Console > Configuracoes > Contas de servico")
        print("        Upload pulado.")
        return False

    try:
        if not firebase_admin._apps:
            cred = credentials.Certificate(key_path)
            firebase_admin.initialize_app(cred)

        db = fb_firestore.client()
        print(f"\n[Firestore] Fazendo upload...")
        for emp, data in empresa_data.items():
            json_str = json.dumps(data, ensure_ascii=False)
            size_kb = len(json_str.encode("utf-8")) / 1024
            if size_kb > 900:
                print(f"   AVISO: {emp} muito grande ({size_kb:.0f} KB) — limite Firestore é 1MB por doc")
            db.collection("dados").document(emp).set({
                "payload": json_str,
                "gerado_em": data.get("gerado_em", ""),
                "size_kb": round(size_kb, 1),
            })
            print(f"   OK  dados/{emp}  ({size_kb:.1f} KB)")

        meta = {
            "gerado_em": dados_completos.get("gerado_em", ""),
            "empresas": sorted(empresa_data.keys()),
            "timestamp": datetime.now().isoformat(),
        }
        db.collection("dados").document("_meta").set(meta)
        print("   OK  dados/_meta")
        print(f"\n[OK] Firestore: {len(empresa_data)} empresa(s) publicadas.")
        return True
    except Exception as e:
        print(f"\n[ERRO] Upload Firestore falhou: {e}")
        import traceback; traceback.print_exc()
        return False


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print(" Processador de Fretes")
    print("=" * 60)

    nfe_map                           = parse_faturamento(BASE_DIR)
    chaves_canceladas                          = parse_cancelamentos()
    cte_list, nfe_to_cte, n_cancel, c_lista   = parse_ctes(CTE_XML_DIR, chaves_canceladas)

    if not cte_list and not nfe_map:
        print("\n[ERRO] Nenhum dado encontrado. Verifique os caminhos.")
        sys.exit(1)

    dados = cruzar(nfe_map, cte_list, nfe_to_cte)
    dados["resumo"]["cte_cancelados"] = n_cancel
    dados["cte_cancelados_chaves"]    = [c["cte_chave"] for c in c_lista]
    dados["cancelados_data"]          = c_lista

    json_str = json.dumps(dados, ensure_ascii=False)
    json_str = json_str.replace('</', '<\\/')
    html = HTML_TEMPLATE.replace("__DATA__", json_str)

    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    # Upload para Firestore (por empresa)
    print("\n[Firebase] Dividindo dados por empresa...")
    empresa_data = split_by_empresa(dados)
    print(f"   Empresas: {', '.join(sorted(empresa_data.keys()))}")
    upload_to_firestore(empresa_data, dados)

    r = dados["resumo"]
    print(f"\n[OK] Dashboard gerado: {OUTPUT_HTML}")
    print(f"   CTe processados:   {r['total_cte']}")
    print(f"   CTe cancelados:    {r.get('cte_cancelados', 0)} (ignorados)")
    print(f"   NF-e faturamento:  {r.get('total_nfe_fat', 0)}")
    print(f"   Vinculadas:        {r['nfe_com_cte']}")
    print(f"   Sem CTe:           {r['nfe_sem_cte']}")
    print(f"   Faturamento total: R$ {r['total_faturamento']:,.2f}")
    print(f"   Valor total frete: R$ {r['valor_total_frete']:,.2f}")
    if r['total_faturamento']:
        print(f"   % Frete/Receita:   {r['valor_total_frete']/r['total_faturamento']*100:.1f}%")
    print(f"   Ticket medio:      R$ {r['media_frete']:,.2f}")
    print("\nAbra o arquivo dashboard_frete.html no navegador.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        print("\n[ERRO FATAL]")
        traceback.print_exc()
    finally:
        input("\nPressione Enter para fechar...")
