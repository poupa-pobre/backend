from rest_framework import serializers

from apps.cartoes.models import Cartao
from apps.vinculos.models import Vinculo

from .models import GastoFixo, GastoFixoMensal


class GastoFixoSerializer(serializers.ModelSerializer):
    class Meta:
        model = GastoFixo
        fields = [
            "id",
            "descricao",
            "tipo",
            "valor",
            "valor_estimado",
            "dia_vencimento",
            "categoria",
            "forma_pagamento",
            "cartao",
            "compartilhado",
            "vinculo",
            "valor_dono",
            "valor_vinculado",
            "ativo",
        ]
        read_only_fields = ["ativo"]  # baixa é soft delete (DELETE/reativar)

    def _usuario(self):
        return self.context["request"].user

    # --- Validações de pertencimento (scoping por dono) ---

    def validate_categoria(self, categoria):
        if categoria.usuario_id != self._usuario().id or not categoria.ativa:
            raise serializers.ValidationError("Categoria não encontrada.")
        return categoria

    def validate_cartao(self, cartao):
        if cartao is None:
            return None
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

    # --- Regras de negócio (cross-field) ---

    def _valor_efetivo(self, attrs, campo):
        if campo in attrs:
            return attrs[campo]
        return getattr(self.instance, campo, None)

    def validate(self, attrs):
        tipo = self._valor_efetivo(attrs, "tipo")
        valor = self._valor_efetivo(attrs, "valor")
        forma = self._valor_efetivo(attrs, "forma_pagamento")
        cartao = self._valor_efetivo(attrs, "cartao")

        # RF-030: tipo A exige valor fixo.
        if tipo == GastoFixo.Tipo.FIXO and valor is None:
            raise serializers.ValidationError(
                {"valor": "Valor é obrigatório no tipo A (fixo)."}
            )

        # Cartão obrigatório quando a forma de pagamento é cartão, e proibido fora dela.
        if forma == GastoFixo.FormaPagamento.CARTAO:
            if cartao is None:
                raise serializers.ValidationError(
                    {"cartao": "Cartão é obrigatório quando a forma é cartão."}
                )
        elif cartao is not None:
            raise serializers.ValidationError(
                {"cartao": "Cartão só se aplica à forma de pagamento cartão."}
            )

        self._validar_compartilhamento(attrs)
        return attrs

    def _validar_compartilhamento(self, attrs):
        """§1: compartilhado exige vínculo aceito e rateio que fecha o total."""
        compartilhado = self._valor_efetivo(attrs, "compartilhado")
        vinculo = self._valor_efetivo(attrs, "vinculo")
        valor = self._valor_efetivo(attrs, "valor")
        valor_dono = self._valor_efetivo(attrs, "valor_dono")
        valor_vinculado = self._valor_efetivo(attrs, "valor_vinculado")

        if not compartilhado:
            attrs["vinculo"] = None
            attrs["valor_dono"] = None
            attrs["valor_vinculado"] = None
            return

        if vinculo is None:
            raise serializers.ValidationError(
                {"vinculo": "Vínculo é obrigatório para gasto fixo compartilhado."}
            )
        if valor_dono is None or valor_vinculado is None:
            raise serializers.ValidationError(
                {"valor_dono": "Informe o rateio (valor_dono e valor_vinculado)."}
            )
        # No tipo B sem valor fixo não há total a fechar; só valida quando há valor.
        if valor is not None and valor_dono + valor_vinculado != valor:
            raise serializers.ValidationError(
                {"valor_dono": "valor_dono + valor_vinculado deve ser igual ao valor."}
            )

    def create(self, validated_data):
        return GastoFixo.objects.create(usuario=self._usuario(), **validated_data)


class GastoFixoMensalSerializer(serializers.ModelSerializer):
    descricao = serializers.CharField(source="gasto_fixo.descricao", read_only=True)
    tipo = serializers.CharField(source="gasto_fixo.tipo", read_only=True)
    valor_efetivo = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    data_vencimento = serializers.DateField(read_only=True)

    class Meta:
        model = GastoFixoMensal
        fields = [
            "id",
            "gasto_fixo",
            "descricao",
            "tipo",
            "mes_referencia",
            "valor_real",
            "valor_efetivo",
            "data_vencimento",
            "status",
            "data_pagamento",
            "checked_at",
        ]
        read_only_fields = fields  # geradas/derivadas; alteração só via ação `pagar`


class CheckGastoFixoSerializer(serializers.Serializer):
    """Check de pagamento (RN-031). Tipo B exige `valor_real`."""

    valor_real = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False
    )
    data_pagamento = serializers.DateField(required=False)

    def validate(self, attrs):
        mensal = self.context["mensal"]
        if mensal.gasto_fixo.tipo == GastoFixo.Tipo.ESTIMADO:
            if attrs.get("valor_real") is None and mensal.valor_real is None:
                raise serializers.ValidationError(
                    {"valor_real": "Tipo B exige o valor real antes do check."}
                )
        return attrs
