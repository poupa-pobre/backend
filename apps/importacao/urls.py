from rest_framework.routers import DefaultRouter

from .views import ImportacaoViewSet, MovimentacaoDetectadaViewSet

app_name = "importacao"

router = DefaultRouter()
router.register(
    r"movimentacoes-detectadas",
    MovimentacaoDetectadaViewSet,
    basename="movimentacaodetectada",
)
router.register(r"importacoes", ImportacaoViewSet, basename="importacao")

urlpatterns = router.urls
