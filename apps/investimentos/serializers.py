from rest_framework import serializers

from .models import Investimento


class InvestimentoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Investimento
        fields = [
            "id",
            "tipo",
            "instituicao",
            "descricao",
            "valor_aportado",
            "data_aporte",
        ]

    def validate_valor_aportado(self, valor):
        if valor <= 0:
            raise serializers.ValidationError("O valor aportado deve ser positivo.")
        return valor
