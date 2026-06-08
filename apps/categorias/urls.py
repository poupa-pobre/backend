from rest_framework.routers import DefaultRouter

from .views import CategoriaViewSet, SubcategoriaViewSet, TagViewSet

app_name = "categorias"

router = DefaultRouter()
router.register(r"categorias", CategoriaViewSet, basename="categoria")
router.register(r"subcategorias", SubcategoriaViewSet, basename="subcategoria")
router.register(r"tags", TagViewSet, basename="tag")

urlpatterns = router.urls
