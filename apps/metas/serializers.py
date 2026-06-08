from rest_framework import serializers

from .models import AporteMeta, Meta


class AporteMetaSerializer(serializers.ModelSerializer):
    class Meta:
        model = AporteMeta
        fields = ["id", "meta", "valor", "data", "observacao"]

    def _usuario(self):
        return self.context["request"].user

    def validate_meta(self, meta):
        if meta.usuario_id != self._usuario().id:
            raise serializers.ValidationError("Meta não encontrada.")
        return meta

    def validate_valor(self, valor):
        if valor <= 0:
            raise serializers.ValidationError("O valor do aporte deve ser positivo.")
        return valor


class MetaSerializer(serializers.ModelSerializer):
    # Progresso (RN-060), derivado.
    percentual_concluido = serializers.SerializerMethodField()
    valor_restante = serializers.SerializerMethodField()
    concluida = serializers.SerializerMethodField()
    meses_restantes = serializers.SerializerMethodField()
    aporte_mensal_necessario = serializers.SerializerMethodField()
    no_ritmo = serializers.SerializerMethodField()

    class Meta:
        model = Meta
        fields = [
            "id",
            "nome",
            "cor",
            "emoji",
            "valor_alvo",
            "valor_atual",
            "data_alvo",
            "contribuicao_mensal_planejada",
            "percentual_concluido",
            "valor_restante",
            "concluida",
            "meses_restantes",
            "aporte_mensal_necessario",
            "no_ritmo",
        ]

    def _progresso(self, meta):
        if not hasattr(meta, "_progresso_cache"):
            meta._progresso_cache = meta.progresso()
        return meta._progresso_cache

    def get_percentual_concluido(self, meta):
        return self._progresso(meta)["percentual_concluido"]

    def get_valor_restante(self, meta):
        return self._progresso(meta)["valor_restante"]

    def get_concluida(self, meta):
        return self._progresso(meta)["concluida"]

    def get_meses_restantes(self, meta):
        return self._progresso(meta)["meses_restantes"]

    def get_aporte_mensal_necessario(self, meta):
        return self._progresso(meta)["aporte_mensal_necessario"]

    def get_no_ritmo(self, meta):
        return self._progresso(meta)["no_ritmo"]
