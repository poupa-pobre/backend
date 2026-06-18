"""
Limite **global** do cartão de crédito (RN-040, RF-040).

Diferente da composição (que é por fatura/mês), aqui o limite considera **tudo
que está comprometido e ainda não foi pago** no cartão, de qualquer mês:

1. **Gastos variáveis no crédito** em faturas ainda não pagas;
2. **Gastos fixos** cobrados no cartão em faturas ainda não pagas;
3. **Parcelas pendentes** — um parcelamento reserva o **total** do limite na
   hora da compra; cada parcela paga libera a sua fatia.

`limite_disponivel = limite_total − limite_usado`. É contra esse disponível que
a criação de gasto no crédito e de parcelamento é validada (comprar R$ 5.000 com
R$ 5.500 livres deixa R$ 500). Imports de models são locais (gastos/dívidas/
fixos importam `cartoes` — evita ciclo).
"""

from decimal import Decimal

from django.db.models import Sum


def formatar_brl(valor):
    """R$ pt-BR (R$ 1.234,56) — usado nas mensagens de limite insuficiente."""
    v = Decimal(valor or 0).quantize(Decimal("0.01"))
    inteiro, _, dec = f"{abs(v):.2f}".partition(".")
    grupos = []
    while len(inteiro) > 3:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    grupos.insert(0, inteiro)
    return f"{'-' if v < 0 else ''}R$ {'.'.join(grupos)},{dec}"


def limite_usado(cartao, ignorar_gasto=None, ignorar_divida=None):
    """Total comprometido no cartão. `ignorar_*` exclui um gasto/dívida do
    cálculo (usado na edição, pra não contar o próprio item duas vezes)."""
    from apps.dividas.models import Parcela
    from apps.gastos.models import Gasto
    from apps.gastos_fixos.models import GastoFixo, GastoFixoMensal

    from .models import Fatura

    # Meses cujas faturas ainda não foram pagas → comprometidos.
    meses_em_aberto = list(
        Fatura.objects.filter(cartao=cartao)
        .exclude(status=Fatura.Status.PAGA)
        .values_list("mes_referencia", flat=True)
    )

    # 1. Gastos variáveis no crédito desses meses.
    gastos_qs = Gasto.objects.filter(
        cartao=cartao,
        forma_pagamento=Gasto.FormaPagamento.CREDITO,
        mes_referencia__in=meses_em_aberto,
    )
    if ignorar_gasto:
        gastos_qs = gastos_qs.exclude(id=ignorar_gasto)
    variaveis = gastos_qs.aggregate(s=Sum("valor"))["s"] or Decimal("0.00")

    # 2. Gastos fixos cobrados no cartão nesses meses.
    fixos = Decimal("0.00")
    for m in GastoFixoMensal.objects.filter(
        gasto_fixo__cartao=cartao,
        gasto_fixo__forma_pagamento=GastoFixo.FormaPagamento.CARTAO,
        mes_referencia__in=meses_em_aberto,
    ).select_related("gasto_fixo"):
        fixos += m.valor_efetivo or Decimal("0.00")

    # 3. Parcelas pendentes (o parcelamento reserva o total; pagar libera).
    parcelas_qs = Parcela.objects.filter(
        divida__cartao=cartao, status=Parcela.Status.PENDENTE
    )
    if ignorar_divida:
        parcelas_qs = parcelas_qs.exclude(divida_id=ignorar_divida)
    parcelas = parcelas_qs.aggregate(s=Sum("valor"))["s"] or Decimal("0.00")

    return variaveis + fixos + parcelas


def limite_disponivel(cartao, ignorar_gasto=None, ignorar_divida=None):
    return cartao.limite_total - limite_usado(
        cartao, ignorar_gasto=ignorar_gasto, ignorar_divida=ignorar_divida
    )
