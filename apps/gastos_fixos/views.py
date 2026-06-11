from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import GastoFixo, GastoFixoMensal
from .serializers import (
    CheckGastoFixoSerializer,
    GastoFixoMensalSerializer,
    GastoFixoSerializer,
)


class GastoFixoViewSet(viewsets.ModelViewSet):
    """
    CRUD dos templates de gasto fixo. Exclusão é soft delete (`ativo=False`);
    a listagem oculta inativos por padrão (`?incluir_inativos=true` para ver todos).
    """

    serializer_class = GastoFixoSerializer

    def get_queryset(self):
        qs = GastoFixo.objects.filter(usuario=self.request.user).select_related(
            "categoria", "cartao", "vinculo"
        )
        incluir = self.request.query_params.get("incluir_inativos") == "true"
        if self.action == "list" and not incluir:
            qs = qs.filter(ativo=True)
        return qs

    def perform_create(self, serializer):
        """Cria o template e já gera a instância mensal do mês corrente (RN-030),
        para o fixo aparecer no mês em que foi cadastrado (o job mensal cobre os
        meses seguintes). Idempotente via UNIQUE(gasto_fixo, mes_referencia)."""
        gasto_fixo = serializer.save()
        mes = timezone.localdate().replace(day=1)
        gasto_fixo.mensais.get_or_create(mes_referencia=mes)

    def destroy(self, request, *args, **kwargs):
        gasto_fixo = self.get_object()
        gasto_fixo.ativo = False
        gasto_fixo.save(update_fields=["ativo", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def reativar(self, request, pk=None):
        gasto_fixo = self.get_object()
        gasto_fixo.ativo = True
        gasto_fixo.save(update_fields=["ativo", "updated_at"])
        return Response(self.get_serializer(gasto_fixo).data)


class GastoFixoMensalViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """
    Instâncias mensais dos gastos fixos (somente leitura — geradas pelo job
    mensal). Filtros por `mes_referencia`/`status`. A ação `pagar` dá o check
    (RN-031); tipo B exige `valor_real`.
    """

    serializer_class = GastoFixoMensalSerializer

    def get_queryset(self):
        qs = GastoFixoMensal.objects.filter(
            gasto_fixo__usuario=self.request.user
        ).select_related("gasto_fixo")
        params = self.request.query_params
        if mes := params.get("mes_referencia"):
            qs = qs.filter(mes_referencia=mes)
        if status_q := params.get("status"):
            qs = qs.filter(status=status_q)
        return qs

    @action(detail=True, methods=["post"])
    def pagar(self, request, pk=None):
        """RN-031: marca como pago, registra check; tipo B informa `valor_real`."""
        mensal = self.get_object()
        if mensal.status == GastoFixoMensal.Status.PAGO:
            return Response(
                {"detail": "Gasto fixo já está pago."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = CheckGastoFixoSerializer(
            data=request.data, context={"mensal": mensal}
        )
        serializer.is_valid(raise_exception=True)
        dados = serializer.validated_data

        if "valor_real" in dados:
            mensal.valor_real = dados["valor_real"]
        mensal.status = GastoFixoMensal.Status.PAGO
        mensal.data_pagamento = dados.get("data_pagamento") or timezone.localdate()
        mensal.checked_at = timezone.now()
        mensal.save(
            update_fields=[
                "valor_real",
                "status",
                "data_pagamento",
                "checked_at",
                "updated_at",
            ]
        )
        return Response(self.get_serializer(mensal).data)

    @action(detail=True, methods=["post"])
    def desmarcar(self, request, pk=None):
        """Reverte o check (marcou errado): volta a pendente/atrasado e limpa o
        pagamento (data, hora e o `valor_real` informado no tipo B)."""
        mensal = self.get_object()
        if mensal.status != GastoFixoMensal.Status.PAGO:
            return Response(
                {"detail": "Este gasto fixo não está pago."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        mensal.valor_real = None
        mensal.data_pagamento = None
        mensal.checked_at = None
        mensal.status = GastoFixoMensal.Status.PENDENTE
        if mensal.esta_atrasado():
            mensal.status = GastoFixoMensal.Status.ATRASADO
        mensal.save(
            update_fields=[
                "valor_real",
                "status",
                "data_pagamento",
                "checked_at",
                "updated_at",
            ]
        )
        return Response(self.get_serializer(mensal).data)
