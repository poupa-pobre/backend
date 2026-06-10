from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Gasto
from .parser import parsear_cupom
from .serializers import GastoSerializer


class ParsearCupomSerializer(serializers.Serializer):
    """Payload do preview: o texto do OCR e/ou a URL do QR (ao menos um)."""

    texto_ocr = serializers.CharField(required=False, allow_blank=True, default="")
    url_qr = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def validate(self, attrs):
        if not attrs.get("texto_ocr") and not attrs.get("url_qr"):
            raise serializers.ValidationError(
                "Envie o texto do cupom (texto_ocr) ou a URL do QR (url_qr)."
            )
        return attrs


class GastoViewSet(viewsets.ModelViewSet):
    """
    CRUD de gastos do usuário. Filtros opcionais por `mes_referencia`,
    `categoria`, `cartao` e `forma_pagamento` — a visão do mês é a consulta
    central do sistema. A action `parsear-cupom` faz o preview do scanner.
    """

    serializer_class = GastoSerializer

    def get_queryset(self):
        qs = (
            Gasto.objects.filter(usuario=self.request.user)
            .select_related("categoria", "subcategoria", "cartao", "vinculo")
            .prefetch_related("tags", "compra_detalhada__itens")
        )
        params = self.request.query_params
        if mes := params.get("mes_referencia"):
            qs = qs.filter(mes_referencia=mes)
        if categoria := params.get("categoria"):
            qs = qs.filter(categoria_id=categoria)
        if cartao := params.get("cartao"):
            qs = qs.filter(cartao_id=cartao)
        if forma := params.get("forma_pagamento"):
            qs = qs.filter(forma_pagamento=forma)
        return qs

    @action(detail=False, methods=["post"], url_path="parsear-cupom")
    def parsear_cupom(self, request):
        """RF-025: recebe o texto do OCR e/ou a URL do QR e devolve o preview dos
        itens para a tela de revisão. **Não persiste** nada."""
        entrada = ParsearCupomSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        preview = parsear_cupom(
            texto_ocr=entrada.validated_data.get("texto_ocr", ""),
            url_qr=entrada.validated_data.get("url_qr") or None,
        )
        return Response(preview)
