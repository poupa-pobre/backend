from django.urls import path

from .views import GastosPorCategoriaPDFView, GastosPorCategoriaView

app_name = "relatorios"

urlpatterns = [
    path(
        "relatorios/gastos-por-categoria/",
        GastosPorCategoriaView.as_view(),
        name="gastos-por-categoria",
    ),
    path(
        "relatorios/gastos-por-categoria/pdf/",
        GastosPorCategoriaPDFView.as_view(),
        name="gastos-por-categoria-pdf",
    ),
]
