import os
import sys
import re
from decimal import Decimal

# Setup Django environment
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
import django
django.setup()

from apps.gastos.parser import parsear_cupom

def run_batch():
    ocr_file_path = os.path.join(os.path.dirname(__file__), "..", "_ocr_debug.txt")
    if not os.path.exists(ocr_file_path):
        print(f"File not found: {ocr_file_path}")
        return

    with open(ocr_file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Split by ===== url=... =====
    pattern = r"===== url=.*? ====="
    blocks = re.split(pattern, content)
    headers = re.findall(pattern, content)

    print(f"Loaded {len(blocks)} sections from {ocr_file_path}")

    total_blocks = 0
    successful_blocks = 0
    total_items_parsed = 0
    unidentified_items = 0

    for idx, block in enumerate(blocks):
        block = block.strip()
        if not block:
            continue
        
        # Skip sections that contain JSON geometries as we want to test plain text reconstruction/raw text
        if '"text":' in block:
            continue

        header = headers[idx-1] if idx-1 < len(headers) else "Unknown"
        total_blocks += 1
        try:
            res = parsear_cupom(texto_ocr=block, buscar_online=False)
            items = res.get("itens", [])
            total = res.get("total")
            confere = res.get("total_confere", False)
            
            print(f"\n--- Block {total_blocks} Header: {header} (Length: {len(block)} chars) ---")
            print(f"Est: {res.get('estabelecimento')}, Date: {res.get('data')}, Total: {total}, Confere: {confere}")
            print(f"Parsed {len(items)} items:")
            for i, item in enumerate(items):
                total_items_parsed += 1
                status = "OK" if item.get("identificado") else "UNIDENTIFIED"
                if not item.get("identificado"):
                    unidentified_items += 1
                print(f"  [{status}] {item.get('nome')} | Qtd: {item.get('quantidade')} | Un: {item.get('unidade')} | Unit: {item.get('valor_unitario')} | Total: {item.get('valor')} | Code: {item.get('codigo')}")
            
            if confere:
                successful_blocks += 1
        except Exception as e:
            print(f"\n--- Block {total_blocks} Error: {e} ---")

    print("\n==========================================")
    print(f"Summary:")
    print(f"Total blocks processed: {total_blocks}")
    print(f"Blocks where total checks out: {successful_blocks} ({successful_blocks/total_blocks*100:.1f}%)")
    print(f"Total items parsed: {total_items_parsed}")
    print(f"Unidentified items (requiring review): {unidentified_items} ({unidentified_items/total_items_parsed*100:.1f}%)")
    print("==========================================")

if __name__ == "__main__":
    run_batch()
