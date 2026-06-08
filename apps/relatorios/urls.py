from django.urls import path

from .views import GastosPorCategoriaView

app_name = "relatorios"

urlpatterns = [
    path(
        "relatorios/gastos-por-categoria/",
        GastosPorCategoriaView.as_view(),
        name="gastos-por-categoria",
    ),
]
