from rest_framework.routers import DefaultRouter

from .views import ReceitaViewSet

app_name = "receitas"

router = DefaultRouter()
router.register(r"receitas", ReceitaViewSet, basename="receita")

urlpatterns = router.urls
