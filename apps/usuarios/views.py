from django.conf import settings
from django.core.mail import send_mail
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import (
    LogoutSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    RegistroSerializer,
    UsuarioSerializer,
    make_reset_tokens,
)


class RegistroView(generics.CreateAPIView):
    """Cadastro de novo usuário (público)."""

    serializer_class = RegistroSerializer
    permission_classes = [AllowAny]


class MeView(generics.RetrieveAPIView):
    """Dados do usuário autenticado."""

    serializer_class = UsuarioSerializer

    def get_object(self):
        return self.request.user


class LogoutView(APIView):
    """Invalida o refresh token (rotação + blacklist do SimpleJWT)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(status=status.HTTP_205_RESET_CONTENT)


class PasswordResetRequestView(APIView):
    """Dispara o email de recuperação. Resposta é sempre 200 (não vaza emails)."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        usuario = serializer.get_usuario()
        if usuario is not None:
            uid, token = make_reset_tokens(usuario)
            link = f"{settings.FRONTEND_PASSWORD_RESET_URL}?uid={uid}&token={token}"
            send_mail(
                subject="Recuperação de senha — Poupar Pobre",
                message=(
                    f"Olá, {usuario.nome}.\n\n"
                    f"Para definir uma nova senha, acesse:\n{link}\n\n"
                    "Se você não solicitou, ignore este email."
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[usuario.email],
            )
        return Response(
            {"detail": "Se o email existir, enviaremos as instruções."},
            status=status.HTTP_200_OK,
        )


class PasswordResetConfirmView(APIView):
    """Confirma a nova senha a partir de uid + token."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"detail": "Senha redefinida com sucesso."})
