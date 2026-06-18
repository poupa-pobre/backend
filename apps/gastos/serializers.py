from rest_framework import serializers

from apps.cartoes.limite import formatar_brl, limite_disponivel
from apps.cartoes.models import Cartao
from apps.categorias.models import Categoria, Subcategoria, Tag
from apps.vinculos.models import Vinculo

from .models import CompraDetalhada, Gasto, ItemCompra


class ItemCompraSerializer(serializers.ModelSerializer):
    class Meta:
        model = ItemCompra
        fields = [
            "id",
            "nome",
            "codigo",
            "quantidade",
            "unidade",
            "valor_unitario",
            "valor",
            "categoria",
            "identificado",
        ]
        read_only_fields = ["id"]


class CompraDetalhadaSerializer(serializers.ModelSerializer):
    itens = ItemCompraSerializer(many=True)

    class Meta:
        model = CompraDetalhada
        fields = ["estabelecimento", "origem", "url_nfce", "itens"]

    def validate_itens(self, itens):
        if not itens:
            raise serializers.ValidationError("Informe ao menos um item.")
        return itens

    def get_attribute(self, instance):
        # Na leitura `instance` é o Gasto; o OneToOne reverso ausente levanta
        # DoesNotExist — devolvemos None para o campo virar `null` no JSON.
        try:
            return super().get_attribute(instance)
        except CompraDetalhada.DoesNotExist:
            return None


class GastoSerializer(serializers.ModelSerializer):
    tags = serializers.PrimaryKeyRelatedField(
        many=True, required=False, queryset=Tag.objects.all()
    )
    # Detalhamento por item (RN-023): escrita aninhada; leitura no GET do gasto.
    compra_detalhada = CompraDetalhadaSerializer(required=False)

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
            "comprovante",
            "origem",
            "latitude",
            "longitude",
            "local_nome",
            "tags",
            "compra_detalhada",
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
            self._validar_limite(cartao, attrs)
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

    def _validar_limite(self, cartao, attrs):
        """RN-040: a compra no crédito não pode estourar o limite disponível.
        Na edição, ignora o próprio gasto pra não contá-lo duas vezes."""
        valor = self._valor_efetivo(attrs, "valor")
        if valor is None:
            return
        ignorar = self.instance.id if self.instance is not None else None
        disponivel = limite_disponivel(cartao, ignorar_gasto=ignorar)
        if valor > disponivel:
            raise serializers.ValidationError(
                {
                    "valor": (
                        f"Limite insuficiente no {cartao.nome}: livre "
                        f"{formatar_brl(disponivel)}, esta compra {formatar_brl(valor)}."
                    )
                }
            )

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

    def validate_compra_detalhada(self, compra):
        """Itens só podem apontar para categorias ativas do próprio dono."""
        usuario_id = self._usuario().id
        for item in compra.get("itens", []):
            categoria = item.get("categoria")
            if categoria is not None and (
                categoria.usuario_id != usuario_id or not categoria.ativa
            ):
                raise serializers.ValidationError("Categoria do item não encontrada.")
        return compra

    # --- Persistência (M:N de tags + detalhamento aninhado) ---

    def _salvar_compra(self, gasto, compra_data):
        """Cria a `CompraDetalhada` + `ItemCompra` do gasto (substitui se já existe)."""
        itens = compra_data.pop("itens", [])
        CompraDetalhada.objects.filter(gasto=gasto).delete()
        compra = CompraDetalhada.objects.create(gasto=gasto, **compra_data)
        ItemCompra.objects.bulk_create(
            [ItemCompra(compra=compra, **item) for item in itens]
        )
        return compra

    def create(self, validated_data):
        tags = validated_data.pop("tags", [])
        compra_data = validated_data.pop("compra_detalhada", None)
        gasto = Gasto.objects.create(usuario=self._usuario(), **validated_data)
        gasto.tags.set(tags)
        if compra_data is not None:
            self._salvar_compra(gasto, compra_data)
        return gasto

    def update(self, instance, validated_data):
        tags = validated_data.pop("tags", None)
        compra_data = validated_data.pop("compra_detalhada", None)
        for campo, valor in validated_data.items():
            setattr(instance, campo, valor)
        instance.save()
        if tags is not None:
            instance.tags.set(tags)
        if compra_data is not None:
            self._salvar_compra(instance, compra_data)
        return instance
