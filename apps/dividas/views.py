from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Divida, Parcela
from .serializers import DividaSerializer, ParcelaSerializer


class DividaViewSet(viewsets.ModelViewSet):
    """
    CRUD de dívidas/parcelamentos. As parcelas são geradas ao criar (RN-050) e
    a projeção de quitação (RN-051) vem derivada no serializer.
    """

    serializer_class = DividaSerializer

    def get_queryset(self):
        return (
            Divida.objects.filter(usuario=self.request.user)
            .select_related("cartao", "vinculo")
            .prefetch_related("parcelas")
        )


class ParcelaViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """
    Parcelas das dívidas do usuário (somente leitura — geradas pelo sistema).
    Filtros por `mes_referencia`/`status`/`divida`. A ação `pagar` quita a parcela.
    """

    serializer_class = ParcelaSerializer

    def get_queryset(self):
        qs = Parcela.objects.filter(
            divida__usuario=self.request.user
        ).select_related("divida", "fatura")
        params = self.request.query_params
        if mes := params.get("mes_referencia"):
            qs = qs.filter(mes_referencia=mes)
        if status_q := params.get("status"):
            qs = qs.filter(status=status_q)
        if divida := params.get("divida"):
            qs = qs.filter(divida_id=divida)
        return qs

    @action(detail=True, methods=["post"])
    def pagar(self, request, pk=None):
        parcela = self.get_object()
        if parcela.status == Parcela.Status.PAGA:
            return Response(
                {"detail": "Parcela já está paga."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        parcela.status = Parcela.Status.PAGA
        parcela.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(parcela).data)
