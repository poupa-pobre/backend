from rest_framework import serializers

from apps.cartoes.limite import formatar_brl, limite_disponivel
from apps.cartoes.models import Cartao
from apps.vinculos.models import Vinculo

from .models import Divida, Parcela


class ParcelaSerializer(serializers.ModelSerializer):
    total_parcelas = serializers.IntegerField(
        source="divida.numero_parcelas", read_only=True
    )
    descricao = serializers.CharField(source="divida.descricao", read_only=True)
    valor_compra = serializers.DecimalField(
        source="divida.valor_total", max_digits=12, decimal_places=2, read_only=True
    )

    class Meta:
        model = Parcela
        fields = [
            "id",
            "divida",
            "descricao",
            "numero",
            "total_parcelas",
            "valor",
            "valor_compra",
            "mes_referencia",
            "data_vencimento",
            "status",
            "fatura",
        ]
        read_only_fields = fields  # geradas pelo sistema; baixa só via ação `pagar`


class DividaSerializer(serializers.ModelSerializer):
    parcelas = ParcelaSerializer(many=True, read_only=True)
    # Projeção de quitação (RN-051), derivada.
    valor_pago = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    valor_restante = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    mes_quitacao = serializers.DateField(read_only=True)

    class Meta:
        model = Divida
        fields = [
            "id",
            "descricao",
            "tipo",
            "valor_total",
            "numero_parcelas",
            "valor_parcela",
            "parcela_inicial",
            "data_primeira_parcela",
            "juros",
            "cartao",
            "compartilhado",
            "vinculo",
            "valor_dono",
            "valor_vinculado",
            "parcelas",
            "valor_pago",
            "valor_restante",
            "mes_quitacao",
        ]

    def _usuario(self):
        return self.context["request"].user

    # --- Validações de pertencimento (scoping por dono) ---

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

    def validate_numero_parcelas(self, numero):
        if numero < 1:
            raise serializers.ValidationError("Número de parcelas deve ser ≥ 1.")
        return numero

    # --- Regras de negócio (cross-field) ---

    def _valor_efetivo(self, attrs, campo):
        if campo in attrs:
            return attrs[campo]
        return getattr(self.instance, campo, None)

    def validate(self, attrs):
        tipo = self._valor_efetivo(attrs, "tipo")
        cartao = self._valor_efetivo(attrs, "cartao")
        numero = self._valor_efetivo(attrs, "numero_parcelas")
        inicial = self._valor_efetivo(attrs, "parcela_inicial") or 1

        # Cartão obrigatório no parcelamento de cartão, e proibido fora dele.
        if tipo == Divida.Tipo.PARCELAMENTO_CARTAO:
            if cartao is None:
                raise serializers.ValidationError(
                    {"cartao": "Cartão é obrigatório no parcelamento de cartão."}
                )
            # RN-040/RN-050: o parcelamento reserva o **total** no limite do cartão.
            valor_total = self._valor_efetivo(attrs, "valor_total")
            if valor_total is not None:
                ignorar = self.instance.id if self.instance is not None else None
                disponivel = limite_disponivel(cartao, ignorar_divida=ignorar)
                if valor_total > disponivel:
                    raise serializers.ValidationError(
                        {
                            "valor_total": (
                                f"Limite insuficiente no {cartao.nome}: livre "
                                f"{formatar_brl(disponivel)}, este parcelamento "
                                f"{formatar_brl(valor_total)}."
                            )
                        }
                    )
        elif cartao is not None:
            raise serializers.ValidationError(
                {"cartao": "Cartão só se aplica ao parcelamento de cartão."}
            )

        if numero is not None and inicial > numero:
            raise serializers.ValidationError(
                {"parcela_inicial": "Parcela inicial não pode exceder o total."}
            )

        self._validar_compartilhamento(attrs)
        return attrs

    def _validar_compartilhamento(self, attrs):
        """§1: compartilhado exige vínculo aceito e rateio que fecha o total."""
        compartilhado = self._valor_efetivo(attrs, "compartilhado")
        vinculo = self._valor_efetivo(attrs, "vinculo")
        valor_total = self._valor_efetivo(attrs, "valor_total")
        valor_dono = self._valor_efetivo(attrs, "valor_dono")
        valor_vinculado = self._valor_efetivo(attrs, "valor_vinculado")

        if not compartilhado:
            attrs["vinculo"] = None
            attrs["valor_dono"] = None
            attrs["valor_vinculado"] = None
            return

        if vinculo is None:
            raise serializers.ValidationError(
                {"vinculo": "Vínculo é obrigatório para dívida compartilhada."}
            )
        if valor_dono is None or valor_vinculado is None:
            raise serializers.ValidationError(
                {"valor_dono": "Informe o rateio (valor_dono e valor_vinculado)."}
            )
        if valor_dono + valor_vinculado != valor_total:
            raise serializers.ValidationError(
                {"valor_dono": "valor_dono + valor_vinculado deve ser igual ao valor total."}
            )

    def create(self, validated_data):
        divida = Divida.objects.create(usuario=self._usuario(), **validated_data)
        divida.gerar_parcelas()  # RN-050
        return divida
