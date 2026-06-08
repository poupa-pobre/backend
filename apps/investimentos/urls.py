from rest_framework.routers import DefaultRouter

from .views import InvestimentoViewSet

app_name = "investimentos"

router = DefaultRouter()
router.register(r"investimentos", InvestimentoViewSet, basename="investimento")

urlpatterns = router.urls
