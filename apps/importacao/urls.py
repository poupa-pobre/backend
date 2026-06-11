from rest_framework.routers import DefaultRouter

from .views import MovimentacaoDetectadaViewSet

app_name = "importacao"

router = DefaultRouter()
router.register(
    r"movimentacoes-detectadas",
    MovimentacaoDetectadaViewSet,
    basename="movimentacaodetectada",
)

urlpatterns = router.urls
