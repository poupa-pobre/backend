from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import TruncMonth
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Investimento
from .serializers import InvestimentoSerializer


class InvestimentoViewSet(viewsets.ModelViewSet):
    """
    CRUD de aportes (RF-070). Filtros por `tipo`. A ação `consolidado` (RF-071)
    devolve total por tipo, total geral e histórico de aportes por mês.
    """

    serializer_class = InvestimentoSerializer

    def get_queryset(self):
        qs = Investimento.objects.filter(usuario=self.request.user)
        if tipo := self.request.query_params.get("tipo"):
            qs = qs.filter(tipo=tipo)
        return qs

    def perform_create(self, serializer):
        serializer.save(usuario=self.request.user)

    @action(detail=False)
    def consolidado(self, request):
        """RF-071: total aportado por tipo, total geral e histórico por mês."""
        qs = Investimento.objects.filter(usuario=request.user)

        por_tipo = qs.values("tipo").annotate(total=Sum("valor_aportado")).order_by("-total")
        por_mes = (
            qs.annotate(mes=TruncMonth("data_aporte"))
            .values("mes")
            .annotate(total=Sum("valor_aportado"))
            .order_by("mes")
        )
        total_geral = qs.aggregate(t=Sum("valor_aportado"))["t"] or Decimal("0.00")

        return Response(
            {
                "total_geral": total_geral,
                "por_tipo": list(por_tipo),
                "por_mes": list(por_mes),
            }
        )
