"""
Relatórios read-side (RF-100) — agregações sem model próprio.

`gastos_por_categoria`: soma, por categoria, os **gastos variáveis** (porção do
dono, modelo-de-dados §1) e os **gastos fixos pagos** (valor efetivo) do mês.
É a base do card "Para onde foi meu dinheiro?" do app.
"""

from collections import defaultdict
from decimal import Decimal

from apps.gastos.models import Gasto
from apps.gastos_fixos.models import GastoFixoMensal


def _mes_anterior(mes):
    if mes.month == 1:
        return mes.replace(year=mes.year - 1, month=12)
    return mes.replace(month=mes.month - 1)


def _porcao_dono(gasto):
    if gasto.compartilhado and gasto.valor_dono is not None:
        return gasto.valor_dono
    return gasto.valor


def gastos_por_categoria(usuario, mes):
    buckets = defaultdict(
        lambda: {"total": Decimal("0.00"), "nome": "", "cor": None}
    )

    gastos = Gasto.objects.filter(usuario=usuario, mes_referencia=mes).select_related(
        "categoria"
    )
    for g in gastos:
        b = buckets[g.categoria_id]
        b["total"] += _porcao_dono(g)
        b["nome"] = g.categoria.nome
        b["cor"] = g.categoria.cor

    fixos = GastoFixoMensal.objects.filter(
        gasto_fixo__usuario=usuario,
        mes_referencia=mes,
        status=GastoFixoMensal.Status.PAGO,
    ).select_related("gasto_fixo__categoria")
    for m in fixos:
        cat = m.gasto_fixo.categoria
        b = buckets[cat.id]
        b["total"] += m.valor_efetivo
        b["nome"] = cat.nome
        b["cor"] = cat.cor

    categorias = [
        {"categoria": cid, "nome": v["nome"], "cor": v["cor"], "total": v["total"]}
        for cid, v in buckets.items()
        if v["total"] > 0
    ]
    categorias.sort(key=lambda c: c["total"], reverse=True)
    return categorias


def _total(usuario, mes):
    return sum(
        (c["total"] for c in gastos_por_categoria(usuario, mes)), Decimal("0.00")
    )


def montar_relatorio(usuario, mes):
    categorias = gastos_por_categoria(usuario, mes)
    total = sum((c["total"] for c in categorias), Decimal("0.00"))
    return {
        "mes_referencia": mes,
        "total": total,
        "total_mes_anterior": _total(usuario, _mes_anterior(mes)),
        "categorias": categorias,
    }
