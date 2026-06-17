import sys
import os
import django

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()

import json
from apps.gastos.parser import parsear_cupom

with open("_ocr_debug.txt", "r", encoding="utf-8") as fh:
    content = fh.read()

sections = content.split("===== url=")
# Section 65: None | linhas=49 =====
# Let us find it dynamically
sec_65_body = None
for sec in sections:
    if "linhas=49 =====" in sec and "BOSITIVO" in sec:
        sec_65_body = sec
        break

if sec_65_body:
    header, body = sec_65_body.split("\n", 1)
    
    texto_cru = ""
    linhas_ocr = None
    if "--- geometria ---" in body:
        parts_geo = body.split("--- geometria ---")
        geo_str = parts_geo[1].split("--- ")[0].strip()
        linhas_ocr = json.loads(geo_str)
        
    if "--- texto cru ---" in body:
        parts = body.split("--- texto cru ---")
        subpart = parts[1].split("--- ")[0]
        texto_cru = subpart.strip()
    
    print("Running parsear_cupom with geometry...")
    from apps.gastos.ocr_layout import reconstruir_texto
    texto_reconstruido = reconstruir_texto(linhas_ocr)
    print("=== RECONSTRUCTED TEXT ===")
    print(texto_reconstruido)
    print("==========================")
    
    # Run _parsear_por_sequencial directly to inspect it
    from apps.gastos.parser import _parsear_por_sequencial, _seq_do_inicio, _RE_SEQ
    linhas = [l for l in (texto_reconstruido or "").splitlines() if l.strip()]
    print("Candidates:")
    for idx, l in enumerate(linhas):
        seq = _seq_do_inicio(l)
        if seq is not None:
            print(f"  Line {idx}: {l[:40]} -> {seq}")
            
    res = parsear_cupom(texto_ocr=texto_cru, linhas_ocr=linhas_ocr, buscar_online=False)
    print("TOTAL:", res.get("total"))
    print("TOTAL CONFIRMADO:", res.get("total_confere"))
    for it in res.get("itens", []):
        print(f"Seq: {it.get('sequencial')} | Cod: {it.get('codigo')} | Nome: {it.get('nome')} | Qtd: {it.get('quantidade')} {it.get('unidade')} | Val: {it.get('valor')} | Unit: {it.get('valor_unitario')} | ID: {it.get('identificado')}")
else:
    print("Section 65 not found!")
