from datetime import datetime

from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response

from .services import montar_dashboard


class DashboardView(GenericAPIView):
    """
    Visão do mês (§3): cards de receitas, fixos X/Y, faturas, saldo e economia,
    mais as seções de fixos pendentes, faturas e últimos lançamentos.

    `GET /api/dashboard/?mes=AAAA-MM-01` (padrão: mês corrente).
    """

    def get(self, request):
        mes_param = request.query_params.get("mes")
        if mes_param:
            try:
                mes = datetime.strptime(mes_param, "%Y-%m-%d").date().replace(day=1)
            except ValueError:
                raise ValidationError({"mes": "Use o formato AAAA-MM-DD."})
        else:
            mes = timezone.localdate().replace(day=1)
        return Response(montar_dashboard(request.user, mes))
