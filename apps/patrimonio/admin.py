from django.contrib import admin

from .models import Bem, PatrimonioSnapshot


@admin.register(Bem)
class BemAdmin(admin.ModelAdmin):
    list_display = ["descricao", "usuario", "tipo", "valor_estimado"]
    list_filter = ["tipo"]
    search_fields = ["descricao", "usuario__email"]
    raw_id_fields = ["usuario"]


@admin.register(PatrimonioSnapshot)
class PatrimonioSnapshotAdmin(admin.ModelAdmin):
    list_display = [
        "usuario",
        "mes_referencia",
        "total_ativos",
        "total_passivos",
        "patrimonio_liquido",
    ]
    search_fields = ["usuario__email"]
    raw_id_fields = ["usuario"]
    date_hierarchy = "mes_referencia"
