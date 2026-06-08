from rest_framework.routers import DefaultRouter

from .views import AporteMetaViewSet, MetaViewSet

app_name = "metas"

router = DefaultRouter()
router.register(r"metas", MetaViewSet, basename="meta")
router.register(r"aportes-meta", AporteMetaViewSet, basename="aporte-meta")

urlpatterns = router.urls
