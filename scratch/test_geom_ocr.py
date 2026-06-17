"""Batch sobre os blocos COM geometria (capturas reais) — roda o pipeline real:
linhas_ocr -> reconstruir_texto -> parsear_cupom. Mede itens e total_confere."""
import os, sys, re, json
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
import django
django.setup()
from apps.gastos.parser import parsear_cupom

path = os.path.join(os.path.dirname(__file__), "..", "_ocr_debug.txt")
content = open(path, encoding="utf-8").read()
parts = re.split(r"(===== url=.*? =====)", content)

confere = 0
total = 0
items = 0
unident = 0
for i in range(1, len(parts), 2):
    header = parts[i].strip()
    body = parts[i + 1].strip() if i + 1 < len(parts) else ""
    if '"text":' not in body:
        continue
    m = re.search(r'^\[\{"text":.*\]\s*$', body, re.MULTILINE)
    if not m:
        continue
    try:
        linhas = json.loads(m.group(0))
    except json.JSONDecodeError:
        continue
    total += 1
    res = parsear_cupom(linhas_ocr=linhas, buscar_online=False)
    its = res.get("itens", [])
    ok = res.get("total_confere")
    confere += 1 if ok else 0
    items += len(its)
    bad = sum(1 for it in its if not it.get("identificado"))
    unident += bad
    print(f"\n--- Block {total}: total={res.get('total')} confere={ok} itens={len(its)} naoident={bad} est={res.get('estabelecimento')}")
    for it in its:
        st = "OK " if it.get("identificado") else "REV"
        print(f"  [{st}] {it.get('nome')!r:42} q={it.get('quantidade')} {it.get('unidade')} u={it.get('valor_unitario')} v={it.get('valor')}")

print("\n========== RESUMO GEOMETRIA ==========")
print(f"Blocos: {total} | total_confere: {confere} ({confere/total*100:.0f}%)")
print(f"Itens: {items} | precisam revisao: {unident} ({unident/max(items,1)*100:.0f}%)")
