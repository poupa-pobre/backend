from django.contrib import admin

from .models import Gasto, GastoTag


class GastoTagInline(admin.TabularInline):
    model = GastoTag
    extra = 0
    raw_id_fields = ["tag"]


@admin.register(Gasto)
class GastoAdmin(admin.ModelAdmin):
    list_display = [
        "descricao",
        "usuario",
        "valor",
        "data",
        "categoria",
        "forma_pagamento",
        "compartilhado",
        "mes_referencia",
    ]
    list_filter = ["forma_pagamento", "origem", "compartilhado"]
    search_fields = ["descricao", "usuario__email"]
    raw_id_fields = ["usuario", "categoria", "subcategoria", "cartao", "vinculo"]
    date_hierarchy = "data"
    inlines = [GastoTagInline]
