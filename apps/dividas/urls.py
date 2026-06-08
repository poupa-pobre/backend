from rest_framework.routers import DefaultRouter

from .views import DividaViewSet, ParcelaViewSet

app_name = "dividas"

router = DefaultRouter()
router.register(r"dividas", DividaViewSet, basename="divida")
router.register(r"parcelas", ParcelaViewSet, basename="parcela")

urlpatterns = router.urls
