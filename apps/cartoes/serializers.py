from rest_framework import serializers

from .models import Cartao, Fatura


class CartaoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cartao
        fields = [
            "id",
            "nome",
            "cor",
            "limite_total",
            "dia_fechamento",
            "dia_vencimento",
            "status",
        ]


class FaturaSerializer(serializers.ModelSerializer):
    # Total derivado **ao vivo** da composição — não o cache `Fatura.total`, que
    # só é atualizado em `composicao`/`pagar` e fica defasado após criar gasto,
    # parcela ou fixo no cartão (a lista de cartões mostraria limite intacto).
    # Mesma estratégia do dashboard (`f.composicao()["total"]`).
    total = serializers.SerializerMethodField()

    class Meta:
        model = Fatura
        fields = [
            "id",
            "cartao",
            "mes_referencia",
            "total",
            "status",
            "data_pagamento",
            "valor_pago",
        ]
        # Estrutura gerada/derivada pelo sistema; o cliente só paga (ver ação).
        read_only_fields = [
            "id",
            "cartao",
            "mes_referencia",
            "status",
            "data_pagamento",
            "valor_pago",
        ]

    def get_total(self, fatura):
        # str(Decimal) preserva o contrato (DecimalField já serializava string).
        return str(fatura.composicao()["total"])


class PagamentoFaturaSerializer(serializers.Serializer):
    """Marca a fatura como paga (RN-042)."""

    data_pagamento = serializers.DateField()
    # Default: valor total da fatura.
    valor_pago = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False
    )

    def update(self, fatura, validated_data):
        fatura.status = Fatura.Status.PAGA
        fatura.data_pagamento = validated_data["data_pagamento"]
        fatura.valor_pago = validated_data.get("valor_pago", fatura.total)
        fatura.save(
            update_fields=["status", "data_pagamento", "valor_pago", "updated_at"]
        )
        return fatura
