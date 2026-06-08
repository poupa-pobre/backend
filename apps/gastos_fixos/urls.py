from rest_framework.routers import DefaultRouter

from .views import GastoFixoMensalViewSet, GastoFixoViewSet

app_name = "gastos_fixos"

router = DefaultRouter()
router.register(r"gastos-fixos", GastoFixoViewSet, basename="gastofixo")
router.register(
    r"gastos-fixos-mensais", GastoFixoMensalViewSet, basename="gastofixomensal"
)

urlpatterns = router.urls
