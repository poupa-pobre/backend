from django.contrib import admin

from .models import Divida, Parcela


class ParcelaInline(admin.TabularInline):
    model = Parcela
    extra = 0
    fields = ["numero", "valor", "mes_referencia", "data_vencimento", "status", "fatura"]
    raw_id_fields = ["fatura"]


@admin.register(Divida)
class DividaAdmin(admin.ModelAdmin):
    list_display = [
        "descricao",
        "usuario",
        "tipo",
        "valor_total",
        "numero_parcelas",
        "valor_parcela",
        "data_primeira_parcela",
    ]
    list_filter = ["tipo", "compartilhado"]
    search_fields = ["descricao", "usuario__email"]
    raw_id_fields = ["usuario", "cartao", "vinculo"]
    inlines = [ParcelaInline]


@admin.register(Parcela)
class ParcelaAdmin(admin.ModelAdmin):
    list_display = ["divida", "numero", "valor", "mes_referencia", "status"]
    list_filter = ["status"]
    search_fields = ["divida__descricao"]
    raw_id_fields = ["divida", "fatura"]
    date_hierarchy = "data_vencimento"
