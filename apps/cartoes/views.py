from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Cartao, Fatura
from .serializers import (
    CartaoSerializer,
    FaturaSerializer,
    PagamentoFaturaSerializer,
)


class CartaoViewSet(viewsets.ModelViewSet):
    """
    CRUD de cartões. Exclusão é soft delete (`status=inativo`); a listagem
    oculta inativos por padrão (`?incluir_inativos=true` para ver todos).
    """

    serializer_class = CartaoSerializer

    def get_queryset(self):
        qs = Cartao.objects.filter(usuario=self.request.user)
        incluir = self.request.query_params.get("incluir_inativos") == "true"
        if self.action == "list" and not incluir:
            qs = qs.filter(status=Cartao.Status.ATIVO)
        return qs

    def perform_create(self, serializer):
        serializer.save(usuario=self.request.user)

    def destroy(self, request, *args, **kwargs):
        cartao = self.get_object()
        cartao.status = Cartao.Status.INATIVO
        cartao.save(update_fields=["status", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def reativar(self, request, pk=None):
        cartao = self.get_object()
        cartao.status = Cartao.Status.ATIVO
        cartao.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(cartao).data)


class FaturaViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """
    Faturas dos cartões do usuário (somente leitura — são geradas pelo
    sistema). A ação `pagar` registra o pagamento (RN-042).
    """

    serializer_class = FaturaSerializer

    def get_queryset(self):
        qs = Fatura.objects.filter(cartao__usuario=self.request.user).select_related(
            "cartao"
        )
        cartao = self.request.query_params.get("cartao")
        if cartao:
            qs = qs.filter(cartao_id=cartao)
        status_q = self.request.query_params.get("status")
        if status_q:
            qs = qs.filter(status=status_q)
        return qs

    @action(detail=True, methods=["get"])
    def composicao(self, request, pk=None):
        """Composição da fatura (RF-041..043): fixos + parcelas + variáveis,
        subtotais, total e limite usado × disponível. Atualiza o cache `total`."""
        fatura = self.get_object()
        return Response(fatura.recompor())

    @action(detail=True, methods=["post"])
    def pagar(self, request, pk=None):
        fatura = self.get_object()
        # Garante o total atualizado antes de usá-lo como padrão do pagamento.
        fatura.recompor()
        if fatura.status == Fatura.Status.PAGA:
            return Response(
                {"detail": "Fatura já está paga."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = PagamentoFaturaSerializer(
            instance=fatura, data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(FaturaSerializer(fatura).data)
