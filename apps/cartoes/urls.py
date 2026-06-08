from rest_framework.routers import DefaultRouter

from .views import CartaoViewSet, FaturaViewSet

app_name = "cartoes"

router = DefaultRouter()
router.register(r"cartoes", CartaoViewSet, basename="cartao")
router.register(r"faturas", FaturaViewSet, basename="fatura")

urlpatterns = router.urls
