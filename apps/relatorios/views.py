from datetime import datetime

from django.http import HttpResponse
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response

from .pdf import gerar_pdf_relatorio
from .services import montar_relatorio


def _mes_do_request(request):
    mes_param = request.query_params.get("mes")
    if mes_param:
        try:
            return datetime.strptime(mes_param, "%Y-%m-%d").date().replace(day=1)
        except ValueError:
            raise ValidationError({"mes": "Use o formato AAAA-MM-DD."})
    return timezone.localdate().replace(day=1)


class GastosPorCategoriaView(GenericAPIView):
    """
    Gastos por categoria do mês (RF-100): total, comparação com o mês anterior
    e o detalhamento por categoria (variáveis + fixos pagos).

    `GET /api/relatorios/gastos-por-categoria/?mes=AAAA-MM-DD` (padrão: mês corrente).
    """

    def get(self, request):
        return Response(montar_relatorio(request.user, _mes_do_request(request)))


class GastosPorCategoriaPDFView(GenericAPIView):
    """Exporta o relatório de gastos por categoria em PDF (RF-101).

    `GET /api/relatorios/gastos-por-categoria/pdf/?mes=AAAA-MM-DD`.
    """

    def get(self, request):
        mes = _mes_do_request(request)
        dados = montar_relatorio(request.user, mes)
        nome = getattr(request.user, "nome", "") or ""
        pdf = gerar_pdf_relatorio(dados, nome_usuario=nome)
        resp = HttpResponse(pdf, content_type="application/pdf")
        resp["Content-Disposition"] = (
            f'attachment; filename="relatorio-{mes.strftime("%Y-%m")}.pdf"'
        )
        return resp
