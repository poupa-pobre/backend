from rest_framework import serializers

from apps.vinculos.models import Vinculo

from .models import Receita


class ReceitaSerializer(serializers.ModelSerializer):
    status = serializers.CharField(read_only=True)

    class Meta:
        model = Receita
        fields = [
            "id",
            "descricao",
            "valor",
            "data_prevista",
            "data_real",
            "tipo",
            "recorrente",
            "compartilhada",
            "vinculo",
            "valor_dono",
            "valor_vinculado",
            "mes_referencia",
            "status",
        ]
        # mes_referencia é derivado da data_prevista; status, de data_real.
        read_only_fields = ["mes_referencia", "status"]

    def _usuario(self):
        return self.context["request"].user

    # --- Validações de pertencimento (scoping por dono) ---

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
        """Valor final do campo considerando parcial (PATCH) + instância."""
        if campo in attrs:
            return attrs[campo]
        return getattr(self.instance, campo, None)

    def validate(self, attrs):
        self._validar_compartilhamento(attrs)
        return attrs

    def _validar_compartilhamento(self, attrs):
        """§1: compartilhada exige vínculo aceito e rateio que fecha o total."""
        compartilhada = self._valor_efetivo(attrs, "compartilhada")
        vinculo = self._valor_efetivo(attrs, "vinculo")
        valor = self._valor_efetivo(attrs, "valor")
        valor_dono = self._valor_efetivo(attrs, "valor_dono")
        valor_vinculado = self._valor_efetivo(attrs, "valor_vinculado")

        if not compartilhada:
            # Sem compartilhamento, zera os campos de rateio.
            attrs["vinculo"] = None
            attrs["valor_dono"] = None
            attrs["valor_vinculado"] = None
            return

        if vinculo is None:
            raise serializers.ValidationError(
                {"vinculo": "Vínculo é obrigatório para receita compartilhada."}
            )
        if valor_dono is None or valor_vinculado is None:
            raise serializers.ValidationError(
                {"valor_dono": "Informe o rateio (valor_dono e valor_vinculado)."}
            )
        if valor_dono + valor_vinculado != valor:
            raise serializers.ValidationError(
                {"valor_dono": "valor_dono + valor_vinculado deve ser igual ao valor."}
            )

    # --- Persistência (RN-011: recorrência) ---

    def create(self, validated_data):
        receita = Receita.objects.create(usuario=self._usuario(), **validated_data)
        # RN-011: pré-cria a do mês seguinte (a cópia não cascateia).
        receita.criar_recorrencia()
        return receita
