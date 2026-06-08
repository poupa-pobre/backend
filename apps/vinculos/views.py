from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Vinculo
from .serializers import VinculoCreateSerializer, VinculoSerializer


class VinculoViewSet(viewsets.ModelViewSet):
    """
    Convite (create), listagem das duas pontas (list/retrieve), aceitar/recusar
    pelo destinatário e desfazer (destroy) por qualquer participante.

    Sem PUT/PATCH: o vínculo só muda de estado pelas ações dedicadas.
    """

    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        usuario = self.request.user
        return (
            Vinculo.objects.filter(Q(solicitante=usuario) | Q(destinatario=usuario))
            .select_related("solicitante", "destinatario")
        )

    def get_serializer_class(self):
        if self.action == "create":
            return VinculoCreateSerializer
        return VinculoSerializer

    def perform_create(self, serializer):
        self.vinculo = serializer.save()
        self._notificar_convite(self.vinculo)

    def _notificar_convite(self, vinculo):
        send_mail(
            subject="Convite de vínculo — Poupar Pobre",
            message=(
                f"Olá, {vinculo.destinatario.nome}.\n\n"
                f"{vinculo.solicitante.nome} ({vinculo.solicitante.email}) "
                "quer se vincular a você para compartilhar lançamentos.\n"
                "Abra o app para aceitar ou recusar o convite."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[vinculo.destinatario.email],
        )

    @action(detail=True, methods=["post"])
    def aceitar(self, request, pk=None):
        vinculo = self.get_object()
        if vinculo.destinatario_id != request.user.id:
            return Response(
                {"detail": "Apenas o destinatário pode aceitar o convite."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if vinculo.status != Vinculo.Status.PENDENTE:
            return Response(
                {"detail": "Este convite não está mais pendente."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        vinculo.status = Vinculo.Status.ACEITO
        vinculo.accepted_at = timezone.now()
        vinculo.save(update_fields=["status", "accepted_at", "updated_at"])
        return Response(self.get_serializer(vinculo).data)

    @action(detail=True, methods=["post"])
    def recusar(self, request, pk=None):
        vinculo = self.get_object()
        if vinculo.destinatario_id != request.user.id:
            return Response(
                {"detail": "Apenas o destinatário pode recusar o convite."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if vinculo.status != Vinculo.Status.PENDENTE:
            return Response(
                {"detail": "Este convite não está mais pendente."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        vinculo.status = Vinculo.Status.RECUSADO
        vinculo.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(vinculo).data)
