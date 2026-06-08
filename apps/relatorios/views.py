from datetime import datetime

from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response

from .services import montar_relatorio


class GastosPorCategoriaView(GenericAPIView):
    """
    Gastos por categoria do mês (RF-100): total, comparação com o mês anterior
    e o detalhamento por categoria (variáveis + fixos pagos).

    `GET /api/relatorios/gastos-por-categoria/?mes=AAAA-MM-DD` (padrão: mês corrente).
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
        return Response(montar_relatorio(request.user, mes))
