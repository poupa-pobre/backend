from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Usuario


@admin.register(Usuario)
class UsuarioAdmin(BaseUserAdmin):
    ordering = ["nome"]
    list_display = ["email", "nome", "is_staff", "is_active"]
    search_fields = ["email", "nome"]
    list_filter = ["is_staff", "is_active"]

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Pessoal", {"fields": ("nome",)}),
        ("Permissões", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Datas", {"fields": ("last_login", "created_at", "updated_at")}),
    )
    readonly_fields = ["last_login", "created_at", "updated_at"]
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "nome", "password1", "password2"),
        }),
    )
