from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Categoria, Subcategoria, Tag
from .serializers import (
    CategoriaSerializer,
    SubcategoriaSerializer,
    TagSerializer,
)


class CategoriaViewSet(viewsets.ModelViewSet):
    """
    CRUD de categorias do usuário. Predefinidas podem ser renomeadas mas não
    excluídas; customizadas têm soft delete (`ativa=False`) e podem ser
    restauradas. A listagem oculta inativas por padrão (`?incluir_inativas=true`
    para ver todas).
    """

    serializer_class = CategoriaSerializer

    def get_queryset(self):
        qs = Categoria.objects.filter(usuario=self.request.user)
        incluir = self.request.query_params.get("incluir_inativas") == "true"
        if self.action == "list" and not incluir:
            qs = qs.filter(ativa=True)
        return qs

    def perform_create(self, serializer):
        # Cliente nunca cria predefinida; o seed cuida disso (RF-021).
        serializer.save(usuario=self.request.user, predefinida=False)

    def destroy(self, request, *args, **kwargs):
        categoria = self.get_object()
        if categoria.predefinida:
            return Response(
                {"detail": "Categorias pré-definidas não podem ser excluídas."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # RF-021: com lançamentos vinculados, exige reatribuição antes de excluir.
        if categoria.gastos.exists():
            destino = self._categoria_destino(request, categoria)
            if isinstance(destino, Response):
                return destino
            categoria.gastos.update(categoria=destino)

        categoria.ativa = False
        categoria.save(update_fields=["ativa", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _categoria_destino(self, request, categoria):
        """Resolve a categoria de reatribuição (`reatribuir_para`) ou devolve a
        resposta de erro pedindo-a (RF-021)."""
        destino_id = request.data.get("reatribuir_para") or request.query_params.get(
            "reatribuir_para"
        )
        if not destino_id:
            return Response(
                {
                    "detail": "Categoria possui lançamentos. Informe "
                    "`reatribuir_para` com a categoria de destino.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        destino = (
            Categoria.objects.filter(usuario=request.user, ativa=True)
            .exclude(pk=categoria.pk)
            .filter(pk=destino_id)
            .first()
        )
        if destino is None:
            return Response(
                {"reatribuir_para": "Categoria de destino inválida."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return destino

    @action(detail=True, methods=["post"])
    def restaurar(self, request, pk=None):
        categoria = self.get_object()
        categoria.ativa = True
        categoria.save(update_fields=["ativa", "updated_at"])
        return Response(self.get_serializer(categoria).data)


class SubcategoriaViewSet(viewsets.ModelViewSet):
    serializer_class = SubcategoriaSerializer

    def get_queryset(self):
        qs = Subcategoria.objects.filter(categoria__usuario=self.request.user)
        categoria = self.request.query_params.get("categoria")
        if categoria:
            qs = qs.filter(categoria_id=categoria)
        return qs.select_related("categoria")


class TagViewSet(viewsets.ModelViewSet):
    serializer_class = TagSerializer

    def get_queryset(self):
        return Tag.objects.filter(usuario=self.request.user)

    def perform_create(self, serializer):
        serializer.save(usuario=self.request.user)
