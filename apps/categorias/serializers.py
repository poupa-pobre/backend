from rest_framework import serializers

from .models import (
    MAX_CATEGORIAS_CUSTOMIZADAS,
    Categoria,
    Subcategoria,
    Tag,
)


class CategoriaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Categoria
        fields = ["id", "nome", "cor", "icone", "predefinida", "ativa"]
        # predefinida/ativa são controladas pelo sistema, não pelo cliente.
        read_only_fields = ["predefinida", "ativa"]

    def validate(self, attrs):
        # No cadastro, respeita o teto de 10 customizadas ativas por usuário.
        if self.instance is None:
            usuario = self.context["request"].user
            ativas = Categoria.objects.filter(
                usuario=usuario, predefinida=False, ativa=True
            ).count()
            if ativas >= MAX_CATEGORIAS_CUSTOMIZADAS:
                raise serializers.ValidationError(
                    f"Limite de {MAX_CATEGORIAS_CUSTOMIZADAS} categorias "
                    "customizadas atingido."
                )
        return attrs


class SubcategoriaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subcategoria
        fields = ["id", "categoria", "nome"]

    def validate_categoria(self, categoria):
        if categoria.usuario_id != self.context["request"].user.id:
            raise serializers.ValidationError("Categoria não encontrada.")
        return categoria


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ["id", "nome"]
