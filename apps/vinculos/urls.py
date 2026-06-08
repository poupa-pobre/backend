from rest_framework.routers import DefaultRouter

from .views import VinculoViewSet

app_name = "vinculos"

router = DefaultRouter()
router.register(r"", VinculoViewSet, basename="vinculo")

urlpatterns = router.urls
