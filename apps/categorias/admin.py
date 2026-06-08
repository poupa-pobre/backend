from django.contrib import admin

from .models import Categoria, Subcategoria, Tag


class SubcategoriaInline(admin.TabularInline):
    model = Subcategoria
    extra = 0


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ["nome", "usuario", "predefinida", "ativa"]
    list_filter = ["predefinida", "ativa"]
    search_fields = ["nome", "usuario__email"]
    raw_id_fields = ["usuario"]
    inlines = [SubcategoriaInline]


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ["nome", "usuario"]
    search_fields = ["nome", "usuario__email"]
    raw_id_fields = ["usuario"]
