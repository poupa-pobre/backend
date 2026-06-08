from django.contrib import admin

from .models import AporteMeta, Meta


class AporteMetaInline(admin.TabularInline):
    model = AporteMeta
    extra = 0
    fields = ["valor", "data", "observacao"]


@admin.register(Meta)
class MetaAdmin(admin.ModelAdmin):
    list_display = [
        "nome",
        "usuario",
        "valor_alvo",
        "valor_atual",
        "data_alvo",
    ]
    search_fields = ["nome", "usuario__email"]
    raw_id_fields = ["usuario"]
    inlines = [AporteMetaInline]


@admin.register(AporteMeta)
class AporteMetaAdmin(admin.ModelAdmin):
    list_display = ["meta", "valor", "data"]
    search_fields = ["meta__nome"]
    raw_id_fields = ["meta"]
    date_hierarchy = "data"
