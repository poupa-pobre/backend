"""
Reconstrução das linhas do cupom a partir da **geometria** do OCR (RF-024).

O ML Kit devolve o texto em *blocks → lines*, cada um com um bounding box
(`top/left/width/height`). O problema: num cupom, o ML Kit lê **por colunas**
(descrição de um lado, valores do outro) e a ordem do `.text` cru embaralha
tudo — a descrição vai pra uma linha, o `1,000UN x` pra outra, e os valores
caem todos juntos no rodapé. Parsing linha-a-linha do texto cru não funciona.

Aqui reconstruímos as **linhas visuais reais**: agrupamos os fragmentos pela
coordenada **Y** (mesma altura ≈ mesma linha) e ordenamos por **X** dentro de
cada linha. Assim "001 EAN DESC … 6,49" volta a ser uma linha só, com o valor
do lado certo. A junção das 2 linhas físicas do item (a de `qtd x unit`) é feita
depois, no parser.
"""

from __future__ import annotations


def _cy(frag: dict) -> float:
    """Centro vertical do fragmento."""
    return (frag.get("y") or 0) + (frag.get("h") or 0) / 2


def reconstruir_texto(linhas: list[dict]) -> str:
    """Recebe os fragmentos do OCR (`{text,x,y,h,w}`) e devolve o texto com as
    linhas visuais reconstruídas (uma linha física por linha de texto)."""
    frags = [l for l in (linhas or []) if (l.get("text") or "").strip()]
    if not frags:
        return ""

    alturas = sorted((l.get("h") or 0) for l in frags)
    h_med = alturas[len(alturas) // 2] or 12
    # Tolerância vertical: fragmentos cujo centro cai dentro disso são a mesma
    # linha. ~60% da altura típica tolera leve inclinação sem fundir 2 linhas.
    tol = max(h_med * 0.6, 6)

    frags.sort(key=_cy)
    grupos: list[list[dict]] = [[frags[0]]]
    soma = _cy(frags[0])
    for frag in frags[1:]:
        media = soma / len(grupos[-1])
        if abs(_cy(frag) - media) <= tol:
            grupos[-1].append(frag)
            soma += _cy(frag)
        else:
            grupos.append([frag])
            soma = _cy(frag)

    saida = []
    for grupo in grupos:
        grupo.sort(key=lambda l: l.get("x") or 0)
        saida.append("  ".join((l.get("text") or "").strip() for l in grupo))
    return "\n".join(saida)
