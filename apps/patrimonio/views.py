from datetime import datetime

from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .calculo import calcular_patrimonio
from .models import Bem, PatrimonioSnapshot
from .serializers import BemSerializer, PatrimonioSnapshotSerializer


def _mes_param(request):
    """Lê `?mes=AAAA-MM-DD` (1º do mês). Padrão: mês corrente."""
    if mes := request.query_params.get("mes"):
        return datetime.strptime(mes, "%Y-%m-%d").date().replace(day=1)
    return timezone.localdate().replace(day=1)


class BemViewSet(viewsets.ModelViewSet):
    """CRUD de bens (ativos manuais — RF-080)."""

    serializer_class = BemSerializer

    def get_queryset(self):
        return Bem.objects.filter(usuario=self.request.user)

    def perform_create(self, serializer):
        serializer.save(usuario=self.request.user)


class PatrimonioSnapshotViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """
    Histórico do patrimônio (RF-081, snapshots mensais). A ação `atual` devolve
    o cálculo **ao vivo** do patrimônio (RF-080) para o mês informado em `?mes=`.
    """

    serializer_class = PatrimonioSnapshotSerializer

    def get_queryset(self):
        return PatrimonioSnapshot.objects.filter(usuario=self.request.user)

    @action(detail=False)
    def atual(self, request):
        mes = _mes_param(request)
        return Response(calcular_patrimonio(request.user, mes))
