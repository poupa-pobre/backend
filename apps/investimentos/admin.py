from django.contrib import admin

from .models import Investimento


@admin.register(Investimento)
class InvestimentoAdmin(admin.ModelAdmin):
    list_display = [
        "usuario",
        "tipo",
        "instituicao",
        "valor_aportado",
        "data_aporte",
    ]
    list_filter = ["tipo"]
    search_fields = ["instituicao", "descricao", "usuario__email"]
    raw_id_fields = ["usuario"]
    date_hierarchy = "data_aporte"
