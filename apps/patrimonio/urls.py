from rest_framework.routers import DefaultRouter

from .views import BemViewSet, PatrimonioSnapshotViewSet

app_name = "patrimonio"

router = DefaultRouter()
router.register(r"bens", BemViewSet, basename="bem")
router.register(
    r"patrimonio-snapshots", PatrimonioSnapshotViewSet, basename="patrimonio-snapshot"
)

urlpatterns = router.urls
