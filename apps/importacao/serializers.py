from decimal import Decimal

from rest_framework import serializers

from apps.gastos.models import Gasto
from apps.receitas.models import Receita

from .models import Importacao, MovimentacaoDetectada


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


# --- Importação de arquivo (RF-111) ----------------------------------------


class PreviaImportacaoSerializer(serializers.Serializer):
    """Upload do extrato p/ prévia: arquivo + formato opcional (auto-detecta)."""

    arquivo = serializers.FileField()
    formato = serializers.ChoiceField(
        choices=["ofx", "csv"], required=False, allow_blank=True
    )


class TransacaoImportarSerializer(serializers.Serializer):
    """Uma transação revisada pelo usuário, pronta p/ virar Gasto/Receita."""

    data = serializers.DateField()
    valor = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.01")
    )
    descricao = serializers.CharField(max_length=120)
    tipo = serializers.ChoiceField(choices=["gasto", "receita"])
    # Gasto:
    categoria = serializers.IntegerField(required=False, allow_null=True)
    forma_pagamento = serializers.ChoiceField(
        choices=Gasto.FormaPagamento.choices, required=False
    )
    cartao = serializers.IntegerField(required=False, allow_null=True)
    # Receita:
    tipo_receita = serializers.ChoiceField(
        choices=Receita.Tipo.choices, required=False
    )


class ConfirmarImportacaoSerializer(serializers.Serializer):
    arquivo_nome = serializers.CharField(max_length=255, required=False, allow_blank=True)
    formato = serializers.ChoiceField(choices=["ofx", "csv"])
    transacoes = TransacaoImportarSerializer(many=True)


class ImportacaoSerializer(serializers.ModelSerializer):
    """Histórico de importações concluídas."""

    class Meta:
        model = Importacao
        fields = [
            "id", "arquivo_nome", "formato", "quantidade_transacoes", "created_at",
        ]
        read_only_fields = fields
