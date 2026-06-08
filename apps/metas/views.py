from django.db.models import F
from rest_framework import mixins, viewsets

from .models import AporteMeta, Meta
from .serializers import AporteMetaSerializer, MetaSerializer


class MetaViewSet(viewsets.ModelViewSet):
    """
    CRUD de metas. O progresso (RN-060) vem derivado no serializer. O
    `valor_atual` é incrementado pelos aportes (RF-061), não editado à mão.
    """

    serializer_class = MetaSerializer

    def get_queryset(self):
        return Meta.objects.filter(usuario=self.request.user).prefetch_related(
            "aportes"
        )

    def perform_create(self, serializer):
        serializer.save(usuario=self.request.user)


class AporteMetaViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    Aportes às metas do usuário (RF-061). Criar/excluir um aporte ajusta o
    `valor_atual` da meta. Filtro por `meta`.
    """

    serializer_class = AporteMetaSerializer

    def get_queryset(self):
        qs = AporteMeta.objects.filter(meta__usuario=self.request.user).select_related(
            "meta"
        )
        if meta := self.request.query_params.get("meta"):
            qs = qs.filter(meta_id=meta)
        return qs

    def perform_create(self, serializer):
        aporte = serializer.save()
        # RF-061: cada aporte soma ao valor atual da meta.
        Meta.objects.filter(pk=aporte.meta_id).update(
            valor_atual=F("valor_atual") + aporte.valor
        )

    def perform_destroy(self, instance):
        Meta.objects.filter(pk=instance.meta_id).update(
            valor_atual=F("valor_atual") - instance.valor
        )
        instance.delete()
