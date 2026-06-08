from django.contrib import admin

from .models import Receita


@admin.register(Receita)
class ReceitaAdmin(admin.ModelAdmin):
    list_display = [
        "descricao",
        "usuario",
        "valor",
        "data_prevista",
        "data_real",
        "tipo",
        "recorrente",
        "compartilhada",
        "mes_referencia",
    ]
    list_filter = ["tipo", "recorrente", "compartilhada"]
    search_fields = ["descricao", "usuario__email"]
    raw_id_fields = ["usuario", "vinculo"]
    date_hierarchy = "data_prevista"
