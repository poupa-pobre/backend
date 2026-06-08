from rest_framework.routers import DefaultRouter

from .views import GastoViewSet

app_name = "gastos"

router = DefaultRouter()
router.register(r"gastos", GastoViewSet, basename="gasto")

urlpatterns = router.urls
