from django.contrib import admin

from .models import Cartao, Fatura


@admin.register(Cartao)
class CartaoAdmin(admin.ModelAdmin):
    list_display = ["nome", "usuario", "limite_total", "dia_fechamento", "dia_vencimento", "status"]
    list_filter = ["status"]
    search_fields = ["nome", "usuario__email"]
    raw_id_fields = ["usuario"]


@admin.register(Fatura)
class FaturaAdmin(admin.ModelAdmin):
    list_display = ["cartao", "mes_referencia", "total", "status", "data_pagamento"]
    list_filter = ["status"]
    search_fields = ["cartao__nome", "cartao__usuario__email"]
    raw_id_fields = ["cartao"]
    date_hierarchy = "mes_referencia"
