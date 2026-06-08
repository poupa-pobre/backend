from rest_framework import serializers

from apps.cartoes.models import Cartao
from apps.categorias.models import Categoria, Subcategoria, Tag
from apps.vinculos.models import Vinculo

from .models import Gasto


class GastoSerializer(serializers.ModelSerializer):
    tags = serializers.PrimaryKeyRelatedField(
        many=True, required=False, queryset=Tag.objects.all()
    )

    class Meta:
        model = Gasto
        fields = [
            "id",
            "descricao",
            "valor",
            "data",
            "categoria",
            "subcategoria",
            "forma_pagamento",
            "cartao",
            "compartilhado",
            "vinculo",
            "valor_dono",
            "valor_vinculado",
            "observacao",
            "origem",
            "tags",
            "mes_referencia",
        ]
        # mes_referencia é derivado (competência); o cliente não o envia.
        read_only_fields = ["mes_referencia"]

    def _usuario(self):
        return self.context["request"].user

    # --- Validações de pertencimento (scoping por dono) ---

    def validate_categoria(self, categoria):
        if categoria.usuario_id != self._usuario().id or not categoria.ativa:
            raise serializers.ValidationError("Categoria não encontrada.")
        return categoria

    def validate_subcategoria(self, subcategoria):
        if subcategoria.categoria.usuario_id != self._usuario().id:
            raise serializers.ValidationError("Subcategoria não encontrada.")
        return subcategoria

    def validate_cartao(self, cartao):
        if cartao.usuario_id != self._usuario().id or cartao.status != Cartao.Status.ATIVO:
            raise serializers.ValidationError("Cartão não encontrado.")
        return cartao

    def validate_vinculo(self, vinculo):
        if vinculo is None:
            return None
        usuario = self._usuario()
        participa = usuario.id in (vinculo.solicitante_id, vinculo.destinatario_id)
        if not participa or vinculo.status != Vinculo.Status.ACEITO:
            raise serializers.ValidationError("Vínculo não encontrado ou não aceito.")
        return vinculo

    def validate_tags(self, tags):
        usuario_id = self._usuario().id
        if any(tag.usuario_id != usuario_id for tag in tags):
            raise serializers.ValidationError("Tag não encontrada.")
        return tags

    # --- Regras de negócio (cross-field) ---

    def _valor_efetivo(self, attrs, campo):
        """Valor final do campo considerando parcial (PATCH) + instância."""
        if campo in attrs:
            return attrs[campo]
        return getattr(self.instance, campo, None)

    def validate(self, attrs):
        forma = self._valor_efetivo(attrs, "forma_pagamento")
        cartao = self._valor_efetivo(attrs, "cartao")
        subcategoria = self._valor_efetivo(attrs, "subcategoria")
        categoria = self._valor_efetivo(attrs, "categoria")

        # RN-020: cartão obrigatório no crédito e proibido fora dele.
        if forma == Gasto.FormaPagamento.CREDITO:
            if cartao is None:
                raise serializers.ValidationError(
                    {"cartao": "Cartão é obrigatório para gastos no crédito."}
                )
        elif cartao is not None:
            raise serializers.ValidationError(
                {"cartao": "Cartão só se aplica a gastos no crédito."}
            )

        # Subcategoria precisa pertencer à categoria escolhida.
        if subcategoria is not None and categoria is not None:
            if subcategoria.categoria_id != categoria.id:
                raise serializers.ValidationError(
                    {"subcategoria": "Subcategoria não pertence à categoria."}
                )

        self._validar_compartilhamento(attrs)
        return attrs

    def _validar_compartilhamento(self, attrs):
        """RN-021: compartilhado exige vínculo aceito e rateio que fecha o total."""
        compartilhado = self._valor_efetivo(attrs, "compartilhado")
        vinculo = self._valor_efetivo(attrs, "vinculo")
        valor = self._valor_efetivo(attrs, "valor")
        valor_dono = self._valor_efetivo(attrs, "valor_dono")
        valor_vinculado = self._valor_efetivo(attrs, "valor_vinculado")

        if not compartilhado:
            # Sem compartilhamento, zera os campos de rateio.
            attrs["vinculo"] = None
            attrs["valor_dono"] = None
            attrs["valor_vinculado"] = None
            return

        if vinculo is None:
            raise serializers.ValidationError(
                {"vinculo": "Vínculo é obrigatório para gasto compartilhado."}
            )
        if valor_dono is None or valor_vinculado is None:
            raise serializers.ValidationError(
                {"valor_dono": "Informe o rateio (valor_dono e valor_vinculado)."}
            )
        if valor_dono + valor_vinculado != valor:
            raise serializers.ValidationError(
                {"valor_dono": "valor_dono + valor_vinculado deve ser igual ao valor."}
            )

    # --- Persistência (M:N de tags) ---

    def create(self, validated_data):
        tags = validated_data.pop("tags", [])
        gasto = Gasto.objects.create(usuario=self._usuario(), **validated_data)
        gasto.tags.set(tags)
        return gasto

    def update(self, instance, validated_data):
        tags = validated_data.pop("tags", None)
        for campo, valor in validated_data.items():
            setattr(instance, campo, valor)
        instance.save()
        if tags is not None:
            instance.tags.set(tags)
        return instance
