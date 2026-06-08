from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework import serializers

from apps.usuarios.serializers import UsuarioSerializer

from .models import Vinculo

Usuario = get_user_model()


class VinculoSerializer(serializers.ModelSerializer):
    """Leitura: mostra ambas as pontas e, por conveniência, a outra ponta
    relativa a quem está consultando."""

    solicitante = UsuarioSerializer(read_only=True)
    destinatario = UsuarioSerializer(read_only=True)
    outro_usuario = serializers.SerializerMethodField()
    sou_solicitante = serializers.SerializerMethodField()

    class Meta:
        model = Vinculo
        fields = [
            "id",
            "solicitante",
            "destinatario",
            "status",
            "accepted_at",
            "outro_usuario",
            "sou_solicitante",
            "created_at",
        ]

    def _request_user(self):
        return self.context["request"].user

    def get_outro_usuario(self, obj):
        return UsuarioSerializer(obj.outro(self._request_user())).data

    def get_sou_solicitante(self, obj):
        return obj.solicitante_id == self._request_user().id


class VinculoCreateSerializer(serializers.Serializer):
    """Cria o convite a partir do email do destinatário."""

    email = serializers.EmailField(write_only=True)

    def validate(self, attrs):
        solicitante = self.context["request"].user
        try:
            destinatario = Usuario.objects.get(
                email__iexact=attrs["email"], is_active=True
            )
        except Usuario.DoesNotExist:
            raise serializers.ValidationError(
                {"email": "Não há usuário ativo com este email."}
            )
        if destinatario == solicitante:
            raise serializers.ValidationError(
                {"email": "Você não pode se vincular a si mesmo."}
            )

        existente = Vinculo.objects.filter(
            Q(solicitante=solicitante, destinatario=destinatario)
            | Q(solicitante=destinatario, destinatario=solicitante)
        ).first()
        if existente and existente.status == Vinculo.Status.ACEITO:
            raise serializers.ValidationError("Vocês já estão vinculados.")
        if existente and existente.status == Vinculo.Status.PENDENTE:
            raise serializers.ValidationError(
                "Já existe um convite pendente entre vocês."
            )

        attrs["solicitante"] = solicitante
        attrs["destinatario"] = destinatario
        attrs["existente"] = existente  # recusado → será reaberto
        return attrs

    def create(self, validated_data):
        solicitante = validated_data["solicitante"]
        destinatario = validated_data["destinatario"]
        existente = validated_data["existente"]
        if existente is not None:
            # Reabre um convite antes recusado como novo convite deste solicitante.
            existente.solicitante = solicitante
            existente.destinatario = destinatario
            existente.status = Vinculo.Status.PENDENTE
            existente.accepted_at = None
            existente.save()
            return existente
        return Vinculo.objects.create(
            solicitante=solicitante, destinatario=destinatario
        )

    def to_representation(self, instance):
        return VinculoSerializer(instance, context=self.context).data
