from django.contrib import admin

from .models import GastoFixo, GastoFixoMensal


@admin.register(GastoFixo)
class GastoFixoAdmin(admin.ModelAdmin):
    list_display = [
        "descricao",
        "usuario",
        "tipo",
        "valor",
        "valor_estimado",
        "forma_pagamento",
        "dia_vencimento",
        "ativo",
    ]
    list_filter = ["tipo", "forma_pagamento", "ativo", "compartilhado"]
    search_fields = ["descricao", "usuario__email"]
    raw_id_fields = ["usuario", "categoria", "cartao", "vinculo"]


@admin.register(GastoFixoMensal)
class GastoFixoMensalAdmin(admin.ModelAdmin):
    list_display = [
        "gasto_fixo",
        "mes_referencia",
        "valor_real",
        "status",
        "data_pagamento",
    ]
    list_filter = ["status"]
    search_fields = ["gasto_fixo__descricao"]
    raw_id_fields = ["gasto_fixo"]
    date_hierarchy = "mes_referencia"
