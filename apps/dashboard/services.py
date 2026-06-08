"""
Visão do mês (Dashboard) — agregação read-side, sem model próprio.
Ver `../documentacao/04-design/fluxo-de-telas.md` §3.

Reúne, para o `mes_referencia` pedido, os cards de resumo e as seções de listas.
Valores de receitas e gastos variáveis usam a **porção do dono** (rateio do
compartilhado, modelo-de-dados §1); fixos e faturas usam o valor **cheio**
(extrato), como na composição da fatura (RF-041..043).
"""

from decimal import Decimal

from django.db.models import Case, DecimalField, F, Sum, When
from django.utils import timezone

from apps.cartoes.models import Cartao, Fatura
from apps.gastos.models import Gasto
from apps.gastos_fixos.models import GastoFixoMensal
from apps.receitas.models import Receita

_PORCAO_RECEITA = Case(
    When(compartilhada=True, valor_dono__isnull=False, then=F("valor_dono")),
    default=F("valor"),
    output_field=DecimalField(max_digits=12, decimal_places=2),
)
_PORCAO_GASTO = Case(
    When(compartilhado=True, valor_dono__isnull=False, then=F("valor_dono")),
    default=F("valor"),
    output_field=DecimalField(max_digits=12, decimal_places=2),
)


def _soma(qs, expr):
    return qs.aggregate(t=Sum(expr))["t"] or Decimal("0.00")


def _total_faturas(faturas):
    return sum((f.composicao()["total"] for f in faturas), Decimal("0.00"))


def montar_dashboard(usuario, mes):
    receitas = Receita.objects.filter(usuario=usuario, mes_referencia=mes)
    recebidas = receitas.filter(data_real__isnull=False)
    previsto = _soma(receitas, _PORCAO_RECEITA)
    recebido = _soma(recebidas, _PORCAO_RECEITA)

    # Gastos variáveis (dia a dia) fora do crédito — saída de caixa imediata.
    variaveis_qs = Gasto.objects.filter(usuario=usuario, mes_referencia=mes).exclude(
        forma_pagamento=Gasto.FormaPagamento.CREDITO
    )
    total_variaveis = _soma(variaveis_qs, _PORCAO_GASTO)

    # Gastos fixos do mês (valor cheio).
    mensais = list(
        GastoFixoMensal.objects.filter(
            gasto_fixo__usuario=usuario, mes_referencia=mes
        ).select_related("gasto_fixo")
    )
    total_fixos = sum((m.valor_efetivo for m in mensais), Decimal("0.00"))
    fixos_pagos = [m for m in mensais if m.status == GastoFixoMensal.Status.PAGO]
    total_fixos_pagos = sum((m.valor_efetivo for m in fixos_pagos), Decimal("0.00"))

    # Faturas do mês dos cartões ativos.
    faturas = list(
        Fatura.objects.filter(
            cartao__usuario=usuario,
            cartao__status=Cartao.Status.ATIVO,
            mes_referencia=mes,
        ).select_related("cartao")
    )
    faturas_abertas = [f for f in faturas if f.status == Fatura.Status.ABERTA]
    faturas_pagas = [f for f in faturas if f.status == Fatura.Status.PAGA]
    total_faturas_abertas = _total_faturas(faturas_abertas)
    total_faturas_pagas = _total_faturas(faturas_pagas)
    total_faturas = total_faturas_abertas + total_faturas_pagas

    # Cards (§3).
    saldo_disponivel = recebido - (
        total_fixos_pagos + total_variaveis + total_faturas_pagas
    )
    gastos_realizados = total_variaveis + total_fixos + total_faturas
    economia = recebido - gastos_realizados

    return {
        "mes_referencia": mes,
        "status_mes": _status_mes(mes),
        "cards": {
            "receitas": {"previsto": previsto, "recebido": recebido},
            "gastos_fixos": {
                "total": total_fixos,
                "pagos": len(fixos_pagos),
                "quantidade": len(mensais),
            },
            "cartoes": {"total_faturas_abertas": total_faturas_abertas},
            "saldo_disponivel": saldo_disponivel,
            "economia_do_mes": economia,
        },
        "fixos_pendentes": _fixos_pendentes(mensais),
        "faturas_cartoes": _faturas_cartoes(faturas),
        "ultimos_lancamentos": _ultimos_lancamentos(usuario),
    }


def _status_mes(mes):
    """Mês passado é 'fechado'; corrente ou futuro, 'aberto'."""
    corrente = timezone.localdate().replace(day=1)
    return "fechado" if mes < corrente else "aberto"


def _fixos_pendentes(mensais):
    pendentes = [
        m for m in mensais if m.status != GastoFixoMensal.Status.PAGO
    ]
    pendentes.sort(key=lambda m: (m.data_vencimento is None, m.data_vencimento))
    return [
        {
            "id": m.id,
            "descricao": m.gasto_fixo.descricao,
            "valor": m.valor_efetivo,
            "data_vencimento": m.data_vencimento,
            "status": m.status,
        }
        for m in pendentes[:5]
    ]


def _faturas_cartoes(faturas):
    itens = []
    for f in faturas:
        comp = f.composicao()
        itens.append(
            {
                "cartao": f.cartao.nome,
                "fatura_id": f.id,
                "total": comp["total"],
                "limite_disponivel": comp["limite_disponivel"],
                "status": f.status,
            }
        )
    return itens


def _ultimos_lancamentos(usuario):
    gastos = (
        Gasto.objects.filter(usuario=usuario)
        .select_related("categoria")
        .order_by("-data", "-id")[:5]
    )
    return [
        {
            "id": g.id,
            "descricao": g.descricao,
            "valor": g.valor,
            "data": g.data,
            "categoria": g.categoria.nome,
        }
        for g in gastos
    ]
