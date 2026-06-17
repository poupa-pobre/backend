import os
import sys

# Setup Django environment
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
import django
django.setup()

import re
from apps.gastos.parser import (
    _parsear_por_sequencial, _parsear_item, _seq_do_inicio,
    encontrar_melhor_sequencia, _RE_DESCONTO, _RE_ITENS_TOTAL
)
_RE_TOTAL = re.compile(
    r"\b(VALOR\s*A\s*PAGAR|VALOR\s*TOTAL|VL\.?\s*TOTAL|TOTAL\s*R\$|"
    r"VALOR\s*PAGO|VALOR\s*COBRADO|VALOR\s*DA\s*COMPRA|VALOR\s*R\$)\b|^TOTAL\b",
    re.IGNORECASE,
)
_RE_FIM_ITENS = re.compile(
    r"\b(QTD\.?\s*TOTAL\s*DE\s*ITEN?S?|TOTAL\s*DE\s*ITEN?S?|QTD\.?\s*TOTAL|"
    r"QTDE?\.?\s*TOTAL|QTDE?,?\s*TOTAL)\b",
    re.IGNORECASE,
)

text = """MEDEIROSE MAIA LTDA (LJ 03)
CNPJ- 05,846.413/0005-39
RUA SENHOR DO BONFIM, 5229
POTENGI- NATAL - RN
DOCUMENTO AUXILIAR DA NOTA FISCAL
DE CONSUMIDOR ELETRONICA
O03
IE - 202138445
EMITIDA EM CONTINGENCIA
Pendente de autorizaca0
#COD| DESCRICAO |QTD|UNIVL UNIVL TOTAL
001 7898908222050 BOLACHA JUCURUTU 250G MANTEIG
1.000UN X
6,49
002 789115280 1842 BISCOITO RECH RICHESTER 125G
3.19 F
7691152801842 BISCOITO RECH RICHESTER 125G
1,000UN x 3,19 F
004 7696045104147 ACHOCOLATADo EM PO ACHOCOLATI
1,000UN X 15,98 T20
005 826 PAO BOMDIA FRANCES KG
0,678KG x
12,99
QTDE, TOTAL DE ITENS
VALOR T0TAL R$
VALOR A PAGAR R$
FORMA PAGAMENT0
TEF
F
6,49
EMITIDA EM CONTINGENCIA
Pendente de autorizacao
3,19
3,19
15,98
8,81
005
37,66
37,66
VALOR PAGO R$
37,66"""

linhas = [l.strip() for l in text.splitlines() if l.strip()]

fim_itens = len(linhas)
for idx, linha in enumerate(linhas):
    if (
        _RE_TOTAL.search(linha)
        or _RE_DESCONTO.search(linha)
        or _RE_ITENS_TOTAL.search(linha)
        or _RE_FIM_ITENS.search(linha)
    ):
        fim_itens = idx
        break

print(f"fim_itens index: {fim_itens} ('{linhas[fim_itens]}')")

candidates = []
for idx in range(fim_itens):
    seq = _seq_do_inicio(linhas[idx])
    if seq is not None:
        candidates.append((idx, seq))
        print(f"Line {idx} matches seq {seq}: '{linhas[idx]}'")

overall_best = encontrar_melhor_sequencia(candidates)
print(f"overall_best: {overall_best}")

if len(overall_best) < 2:
    print("overall_best too short!")
    sys.exit(0)

anchors = [line_idx for line_idx, seq_val in overall_best]
first_val = overall_best[0][1]
first_line = overall_best[0][0]

# Prepend backwards
current_line = first_line
# (simulating the rest of anchors finding)
from apps.gastos.parser import _RE_SEQ, _RE_LINHA_QTD, _eh_ruido
for expected_val in range(first_val - 1, 0, -1):
    found_line = None
    for prev_line in range(current_line - 1, max(-1, current_line - 5), -1):
        m = _RE_SEQ.match(linhas[prev_line])
        if m and not _RE_LINHA_QTD.match(linhas[prev_line]) and not _eh_ruido(linhas[prev_line]):
            found_line = prev_line
            break
    if found_line is not None:
        anchors.insert(0, found_line)
        current_line = found_line
        print(f"Prepend anchor backward: {found_line} -> '{linhas[found_line]}'")
    else:
        break

# Gap filling
final_anchors = []
for i in range(len(overall_best)):
    curr_line, curr_val = overall_best[i]
    if i > 0:
        prev_line, prev_val = overall_best[i - 1]
        if curr_val - prev_val > 1:
            possible_mid_lines = []
            for mid_line in range(prev_line + 1, curr_line):
                m = _RE_SEQ.match(linhas[mid_line])
                if m and not _RE_LINHA_QTD.match(linhas[mid_line]) and not _eh_ruido(linhas[mid_line]):
                    possible_mid_lines.append(mid_line)
            
            lacuna = curr_val - prev_val - 1
            if len(possible_mid_lines) < lacuna:
                candidatas_extras = []
                for mid_line in range(prev_line + 1, curr_line):
                    if mid_line in possible_mid_lines:
                        continue
                    linha = linhas[mid_line]
                    if _eh_ruido(linha) or _RE_LINHA_QTD.match(linha):
                        continue
                    # Prioridade 1: EAN / código de barras
                    if re.match(r"^\s*\d{8,15}\b", linha):
                        candidatas_extras.append((0, mid_line))
                    # Prioridade 2: parece linha de produto
                    elif len(linha.strip()) > 8 and not re.match(r"^\s*\d+([.,]\d+)?\s*$", linha):
                        candidatas_extras.append((1, mid_line))
                candidatas_extras.sort(key=lambda x: (x[0], x[1]))
                faltam = lacuna - len(possible_mid_lines)
                extras = [line for prio, line in candidatas_extras[:faltam]]
                possible_mid_lines.extend(extras)
            
            final_anchors.extend(possible_mid_lines)
            print(f"Gap filling between {prev_val} and {curr_val}: lines {possible_mid_lines}")
    if not final_anchors or curr_line > final_anchors[-1]:
        final_anchors.append(curr_line)

all_anchors = sorted(list(set(anchors + final_anchors)))
print(f"All anchors: {all_anchors}")

for i, start in enumerate(all_anchors):
    end = all_anchors[i + 1] if i + 1 < len(all_anchors) else fim_itens
    bloco = " ".join(l.strip() for l in linhas[start:end])
    bloco_clean = re.sub(r"^\s*[0-9OUQDouqd]{1,3}\s+", "", bloco, count=1)
    print(f"\nParsing anchor index {start} (lines {start}:{end}):")
    print(f"  Raw block: '{bloco}'")
    print(f"  Clean block: '{bloco_clean}'")
    item = _parsear_item(bloco_clean)
    print(f"  Result: {item}")
