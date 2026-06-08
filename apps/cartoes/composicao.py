"""
Composição da fatura — RF-041, RF-042, RF-043.

Uma fatura não armazena seus itens: ela é a **agregação por `mes_referencia`** de
três fontes que apontam para o cartão (modelo-de-dados §6):

1. **Gastos fixos no cartão** — `GastoFixoMensal` cujo template é pago naquele cartão;
2. **Parcelas** — `Parcela`s ligadas a esta fatura (parcelamentos no cartão);
3. **Gastos variáveis** — `Gasto`s no crédito daquele cartão no mês.

Os valores aqui são os **cobrados na fatura** (valor cheio); o rateio de itens
compartilhados é acertado via vínculo à parte, fora do extrato. Imports são
locais porque aqueles apps importam `cartoes` (FK `cartao`) — evita ciclo.
"""

from decimal import Decimal


def compor_fatura(fatura):
    """Devolve a composição estruturada da fatura (subtotais, total, limite)."""
    from apps.dividas.models import Parcela
    from apps.gastos.models import Gasto
    from apps.gastos_fixos.models import GastoFixo, GastoFixoMensal

    cartao = fatura.cartao
    mes = fatura.mes_referencia

    # 1. Gastos fixos (Tipo A/B) cobrados neste cartão (RF-042).
    fixos_qs = GastoFixoMensal.objects.filter(
        gasto_fixo__cartao=cartao,
        gasto_fixo__forma_pagamento=GastoFixo.FormaPagamento.CARTAO,
        mes_referencia=mes,
    ).select_related("gasto_fixo")
    fixos = [
        {
            "id": m.id,
            "descricao": m.gasto_fixo.descricao,
            "valor": m.valor_efetivo or Decimal("0.00"),
            "status": m.status,
            "checked": m.status == GastoFixoMensal.Status.PAGO,
        }
        for m in fixos_qs
    ]
    subtotal_fixos = sum((f["valor"] for f in fixos), Decimal("0.00"))

    # 2. Parcelas de dívidas que caem nesta fatura (RF-043).
    parcelas_qs = Parcela.objects.filter(fatura=fatura).select_related("divida")
    parcelas = [
        {
            "id": p.id,
            "descricao": p.divida.descricao,
            "numero": p.numero,
            "total_parcelas": p.divida.numero_parcelas,
            "valor": p.valor,
            "valor_compra": p.divida.valor_total,
            "status": p.status,
        }
        for p in parcelas_qs
    ]
    subtotal_parcelas = sum((p["valor"] for p in parcelas), Decimal("0.00"))

    # 3. Gastos variáveis no crédito deste cartão no mês.
    variaveis_qs = Gasto.objects.filter(
        cartao=cartao,
        mes_referencia=mes,
        forma_pagamento=Gasto.FormaPagamento.CREDITO,
    )
    variaveis = [
        {"id": g.id, "descricao": g.descricao, "valor": g.valor} for g in variaveis_qs
    ]
    subtotal_variaveis = sum((g["valor"] for g in variaveis), Decimal("0.00"))

    total = subtotal_fixos + subtotal_parcelas + subtotal_variaveis

    return {
        "fixos": fixos,
        "parcelas": parcelas,
        "variaveis": variaveis,
        "subtotais": {
            "fixos": subtotal_fixos,
            "parcelas": subtotal_parcelas,
            "variaveis": subtotal_variaveis,
        },
        "total": total,
        "limite_total": cartao.limite_total,
        "limite_usado": total,
        "limite_disponivel": cartao.limite_total - total,
    }
