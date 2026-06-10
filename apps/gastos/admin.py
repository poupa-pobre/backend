from django.contrib import admin

from .models import CompraDetalhada, Gasto, GastoTag, ItemCompra


class GastoTagInline(admin.TabularInline):
    model = GastoTag
    extra = 0
    raw_id_fields = ["tag"]


class ItemCompraInline(admin.TabularInline):
    model = ItemCompra
    extra = 0
    raw_id_fields = ["categoria"]


@admin.register(CompraDetalhada)
class CompraDetalhadaAdmin(admin.ModelAdmin):
    list_display = ["gasto", "estabelecimento", "origem"]
    list_filter = ["origem"]
    search_fields = ["estabelecimento", "gasto__descricao"]
    raw_id_fields = ["gasto"]
    inlines = [ItemCompraInline]


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
