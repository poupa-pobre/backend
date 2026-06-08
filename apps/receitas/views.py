from datetime import date
from decimal import Decimal

from django.db.models import Case, DecimalField, F, Sum, When
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.cartoes.models import Fatura
from apps.gastos.models import Gasto

from .models import Receita
from .serializers import ReceitaSerializer

#: Expressão "porção do dono": o rateio quando compartilhado, senão o valor cheio.
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


def cobertura_do_mes(usuario, mes_referencia):
    """
    RN-010/RN-041: compara o **saldo disponível** com o total das **faturas
    abertas do mês** de todos os cartões do usuário.

    Saldo disponível = receitas recebidas (`data_real` preenchida) − gastos não
    pagos fora do crédito, ambos pela porção do dono (modelo-de-dados §1). O
    total das faturas vem da composição plena (fixos + parcelas + variáveis,
    RF-041..043) de cada fatura aberta do mês — valor cheio cobrado no cartão.
    """
    receitas = Receita.objects.filter(
        usuario=usuario, mes_referencia=mes_referencia, data_real__isnull=False
    )
    nao_credito = Gasto.objects.filter(
        usuario=usuario, mes_referencia=mes_referencia
    ).exclude(forma_pagamento=Gasto.FormaPagamento.CREDITO)

    recebido = _soma(receitas, _PORCAO_RECEITA)
    gastos_pagos = _soma(nao_credito, _PORCAO_GASTO)

    faturas = Fatura.objects.filter(
        cartao__usuario=usuario,
        mes_referencia=mes_referencia,
        status=Fatura.Status.ABERTA,
    ).select_related("cartao")
    total_faturas = sum(
        (f.composicao()["total"] for f in faturas), Decimal("0.00")
    )
    saldo = recebido - gastos_pagos
    falta = total_faturas - saldo
    coberta = falta <= 0

    if coberta:
        msg = (
            f"Salário recebido. Saldo disponível: R$ {saldo}. "
            f"Fatura(s): R$ {total_faturas}. Coberta."
        )
    else:
        msg = (
            f"Salário recebido. Saldo disponível: R$ {saldo}. "
            f"Fatura(s): R$ {total_faturas}. Atenção: falta R$ {falta}."
        )
    return {
        "saldo_disponivel": saldo,
        "total_faturas": total_faturas,
        "coberta": coberta,
        "falta": max(falta, Decimal("0.00")),
        "mensagem": msg,
    }


class ReceitaViewSet(viewsets.ModelViewSet):
    """
    CRUD de receitas do usuário. Filtros opcionais por `mes_referencia`, `tipo`
    e `status` (prevista/recebida — derivado de `data_real`). A ação `receber`
    marca a receita como recebida e, para salário, devolve a cobertura (RN-010).
    """

    serializer_class = ReceitaSerializer

    def get_queryset(self):
        qs = Receita.objects.filter(usuario=self.request.user).select_related("vinculo")
        params = self.request.query_params
        if mes := params.get("mes_referencia"):
            qs = qs.filter(mes_referencia=mes)
        if tipo := params.get("tipo"):
            qs = qs.filter(tipo=tipo)
        if status_q := params.get("status"):
            if status_q == Receita.Status.RECEBIDA:
                qs = qs.filter(data_real__isnull=False)
            elif status_q == Receita.Status.PREVISTA:
                qs = qs.filter(data_real__isnull=True)
        return qs

    @action(detail=True, methods=["post"])
    def receber(self, request, pk=None):
        """
        RN-010: marca a receita como recebida (`data_real`, padrão hoje). Para
        salário, devolve o resumo de cobertura das faturas do mês.
        """
        receita = self.get_object()
        data_real = request.data.get("data_real") or date.today().isoformat()
        receita.data_real = data_real
        receita.save(update_fields=["data_real", "updated_at"])
        # Garante a recorrência do mês seguinte (idempotente).
        receita.criar_recorrencia()

        payload = self.get_serializer(receita).data
        if receita.tipo == Receita.Tipo.SALARIO:
            payload["cobertura"] = cobertura_do_mes(
                request.user, receita.mes_referencia
            )
        return Response(payload)
