from rest_framework import serializers

from .models import Bem, PatrimonioSnapshot


class BemSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bem
        fields = ["id", "descricao", "tipo", "valor_estimado"]

    def validate_valor_estimado(self, valor):
        if valor < 0:
            raise serializers.ValidationError("O valor estimado não pode ser negativo.")
        return valor


class PatrimonioSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = PatrimonioSnapshot
        fields = [
            "id",
            "mes_referencia",
            "total_ativos",
            "total_passivos",
            "patrimonio_liquido",
        ]
        read_only_fields = fields  # gerados pelo job mensal
