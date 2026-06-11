"""
URL configuration for core project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("apps.usuarios.urls")),
    path("api/vinculos/", include("apps.vinculos.urls")),
    path("api/", include("apps.categorias.urls")),
    path("api/", include("apps.cartoes.urls")),
    path("api/", include("apps.gastos.urls")),
    path("api/", include("apps.receitas.urls")),
    path("api/", include("apps.gastos_fixos.urls")),
    path("api/", include("apps.dividas.urls")),
    path("api/", include("apps.metas.urls")),
    path("api/", include("apps.investimentos.urls")),
    path("api/", include("apps.patrimonio.urls")),
    path("api/", include("apps.dashboard.urls")),
    path("api/", include("apps.relatorios.urls")),
    path("api/", include("apps.importacao.urls")),
]
