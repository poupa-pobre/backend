"""
Cálculo automático do patrimônio líquido — RF-080.

    Patrimônio Líquido = Ativos − Passivos

Ativos:
- **Saldo disponível** do mês: receitas recebidas − gastos pagos fora do crédito,
  ambos pela porção do dono (modelo-de-dados §1);
- **Total investido**: soma de todos os aportes (RF-070);
- **Bens**: valor estimado informado à mão.

Passivos:
- **Faturas não pagas**: composição plena das faturas abertas (fixos + parcelas
  de cartão + variáveis, RF-041..043);
- **Dívidas em aberto**: parcelas pendentes **fora do cartão** (financiamento,
  empréstimo, informal) — as parcelas de cartão já entram via fatura, então
  contá-las aqui duplicaria o passivo.
"""

from decimal import Decimal

from django.db.models import Case, DecimalField, F, Sum, When

from apps.cartoes.models import Fatura
from apps.dividas.models import Parcela
from apps.gastos.models import Gasto
from apps.investimentos.models import Investimento
from apps.receitas.models import Receita

from .models import Bem

#: Porção do dono: o rateio quando compartilhado, senão o valor cheio.
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


def saldo_disponivel(usuario, mes_referencia):
    """Receitas recebidas − gastos pagos (fora do crédito) no mês, porção do dono."""
    recebido = _soma(
        Receita.objects.filter(
            usuario=usuario, mes_referencia=mes_referencia, data_real__isnull=False
        ),
        _PORCAO_RECEITA,
    )
    gastos_pagos = _soma(
        Gasto.objects.filter(usuario=usuario, mes_referencia=mes_referencia).exclude(
            forma_pagamento=Gasto.FormaPagamento.CREDITO
        ),
        _PORCAO_GASTO,
    )
    return recebido - gastos_pagos


def calcular_patrimonio(usuario, mes_referencia):
    """RF-080: devolve ativos, passivos e patrimônio líquido com o detalhamento."""
    saldo = saldo_disponivel(usuario, mes_referencia)
    total_investido = _soma(
        Investimento.objects.filter(usuario=usuario), F("valor_aportado")
    )
    total_bens = _soma(Bem.objects.filter(usuario=usuario), F("valor_estimado"))
    total_ativos = saldo + total_investido + total_bens

    faturas_abertas = Fatura.objects.filter(
        cartao__usuario=usuario, status=Fatura.Status.ABERTA
    ).select_related("cartao")
    total_faturas = sum(
        (f.composicao()["total"] for f in faturas_abertas), Decimal("0.00")
    )
    total_dividas = _soma(
        Parcela.objects.filter(
            divida__usuario=usuario,
            status=Parcela.Status.PENDENTE,
            fatura__isnull=True,  # parcelas de cartão já entram na fatura
        ),
        F("valor"),
    )
    total_passivos = total_faturas + total_dividas

    return {
        "mes_referencia": mes_referencia,
        "ativos": {
            "saldo_disponivel": saldo,
            "total_investido": total_investido,
            "total_bens": total_bens,
        },
        "passivos": {
            "faturas_abertas": total_faturas,
            "dividas_abertas": total_dividas,
        },
        "total_ativos": total_ativos,
        "total_passivos": total_passivos,
        "patrimonio_liquido": total_ativos - total_passivos,
    }
