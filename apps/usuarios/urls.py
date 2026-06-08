from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .views import (
    LogoutView,
    MeView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    RegistroView,
)

app_name = "usuarios"

urlpatterns = [
    path("registro/", RegistroView.as_view(), name="registro"),
    path("login/", TokenObtainPairView.as_view(), name="login"),
    path("refresh/", TokenRefreshView.as_view(), name="refresh"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("me/", MeView.as_view(), name="me"),
    path("senha/recuperar/", PasswordResetRequestView.as_view(), name="senha-recuperar"),
    path("senha/confirmar/", PasswordResetConfirmView.as_view(), name="senha-confirmar"),
]
