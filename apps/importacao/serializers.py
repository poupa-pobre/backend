from decimal import Decimal

from rest_framework import serializers

from apps.receitas.models import Receita

from .models import MovimentacaoDetectada


class ReceberNotificacaoSerializer(serializers.Serializer):
    """Payload cru vindo do listener de notificações do Android."""

    pacote = serializers.CharField(required=False, allow_blank=True, default="")
    titulo = serializers.CharField(required=False, allow_blank=True, default="")
    texto = serializers.CharField(required=False, allow_blank=True, default="")


class MovimentacaoDetectadaSerializer(serializers.ModelSerializer):
    class Meta:
        model = MovimentacaoDetectada
        fields = [
            "id", "tipo", "valor", "contraparte", "banco", "pacote",
            "texto_bruto", "status", "gasto", "receita", "created_at",
        ]
        read_only_fields = fields


class ConfirmarMovimentacaoSerializer(serializers.Serializer):
    """Ajustes opcionais ao confirmar: valor (se faltou), categoria (gasto),
    tipo da receita (recebido)."""

    valor = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, min_value=Decimal("0.01")
    )
    categoria = serializers.IntegerField(required=False)
    tipo_receita = serializers.ChoiceField(
        choices=Receita.Tipo.choices, required=False
    )
