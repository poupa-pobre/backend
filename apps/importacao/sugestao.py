"""
Sugestão de categoria por histórico e **detecção de duplicata** (RN-110).

- `sugerir_categoria`: acha o gasto/receita anterior do usuário com a descrição
  mais parecida e reaproveita a categoria (só p/ gasto; receita não tem categoria).
- `eh_duplicata`: sinaliza (não bloqueia) quando já existe um lançamento com a
  **mesma data**, **mesmo valor** e descrição com **similaridade ≥ 90%**.

A similaridade é o ratio do `difflib.SequenceMatcher` sobre as descrições
normalizadas (minúsculas, sem acento/pontuação) — sem dependência externa.
"""

import unicodedata
from difflib import SequenceMatcher

from apps.gastos.models import Gasto
from apps.receitas.models import Receita

LIMIAR_DUPLICATA = 0.90


def _normalizar(texto):
    s = unicodedata.normalize("NFKD", (texto or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return "".join(c for c in s if c.isalnum() or c.isspace()).strip()


def _similaridade(a, b):
    return SequenceMatcher(None, _normalizar(a), _normalizar(b)).ratio()


def sugerir_categoria(usuario, descricao):
    """Categoria do gasto histórico mais parecido (>0.5). Devolve id ou None."""
    historico = (
        Gasto.objects.filter(usuario=usuario)
        .order_by("-id")
        .values_list("descricao", "categoria_id")[:300]
    )
    melhor_id, melhor_score = None, 0.5
    for desc, cat_id in historico:
        score = _similaridade(descricao, desc)
        if score > melhor_score:
            melhor_id, melhor_score = cat_id, score
    return melhor_id


def eh_duplicata(usuario, transacao):
    """True se já existe lançamento com mesma data+valor e descrição ≥90% similar."""
    if transacao["tipo"] == "gasto":
        existentes = Gasto.objects.filter(
            usuario=usuario, data=transacao["data"], valor=transacao["valor"]
        ).values_list("descricao", flat=True)
    else:
        existentes = Receita.objects.filter(
            usuario=usuario,
            data_prevista=transacao["data"],
            valor=transacao["valor"],
        ).values_list("descricao", flat=True)
    return any(
        _similaridade(transacao["descricao"], d) >= LIMIAR_DUPLICATA for d in existentes
    )
