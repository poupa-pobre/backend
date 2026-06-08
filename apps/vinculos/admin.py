from django.contrib import admin

from .models import Vinculo


@admin.register(Vinculo)
class VinculoAdmin(admin.ModelAdmin):
    list_display = ["id", "solicitante", "destinatario", "status", "accepted_at"]
    list_filter = ["status"]
    search_fields = [
        "solicitante__email",
        "solicitante__nome",
        "destinatario__email",
        "destinatario__nome",
    ]
    raw_id_fields = ["solicitante", "destinatario"]
