from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Gasto
from .parser import parsear_cupom
from .serializers import GastoSerializer


class LinhaOcrSerializer(serializers.Serializer):
    """Um fragmento de texto do OCR com sua geometria (bounding box do ML Kit)."""

    text = serializers.CharField(allow_blank=True)
    x = serializers.FloatField(required=False, default=0)
    y = serializers.FloatField(required=False, default=0)
    h = serializers.FloatField(required=False, default=0)
    w = serializers.FloatField(required=False, default=0)


class ParsearCupomSerializer(serializers.Serializer):
    """Payload do preview: texto e/ou geometria do OCR e/ou a URL do QR (ao menos um)."""

    texto_ocr = serializers.CharField(required=False, allow_blank=True, default="")
    # Fragmentos com posição — quando vêm, o backend reconstrói as linhas reais.
    linhas_ocr = LinhaOcrSerializer(many=True, required=False)
    url_qr = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def validate(self, attrs):
        if not attrs.get("texto_ocr") and not attrs.get("linhas_ocr") and not attrs.get("url_qr"):
            raise serializers.ValidationError(
                "Envie o texto/linhas do cupom ou a URL do QR."
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
        texto = entrada.validated_data.get("texto_ocr", "")
        linhas = entrada.validated_data.get("linhas_ocr") or None
        url = entrada.validated_data.get("url_qr") or None
        # DEBUG TEMPORÁRIO: salva texto cru + geometria pra calibrar o parser.
        try:
            import json

            from .ocr_layout import reconstruir_texto

            with open("/app/_ocr_debug.txt", "a", encoding="utf-8") as fh:
                fh.write(f"\n===== {url=} | linhas={len(linhas) if linhas else 0} =====\n")
                fh.write("--- texto cru ---\n" + texto + "\n")
                if linhas:
                    fh.write("--- reconstruido ---\n" + reconstruir_texto(linhas) + "\n")
                    fh.write("--- geometria ---\n" + json.dumps(linhas, ensure_ascii=False) + "\n")
        except OSError:
            pass
        preview = parsear_cupom(texto_ocr=texto, url_qr=url, linhas_ocr=linhas)
        return Response(preview)
