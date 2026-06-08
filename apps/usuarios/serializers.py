from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken, TokenError

Usuario = get_user_model()


class UsuarioSerializer(serializers.ModelSerializer):
    """Representação pública/leitura do usuário."""

    class Meta:
        model = Usuario
        fields = ["id", "nome", "email"]
        read_only_fields = fields


class RegistroSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])

    class Meta:
        model = Usuario
        fields = ["id", "nome", "email", "password"]
        read_only_fields = ["id"]

    def create(self, validated_data):
        return Usuario.objects.create_user(**validated_data)


class LogoutSerializer(serializers.Serializer):
    """Invalida o refresh token (blacklist) no logout."""

    refresh = serializers.CharField()

    def save(self, **kwargs):
        try:
            RefreshToken(self.validated_data["refresh"]).blacklist()
        except TokenError:
            raise serializers.ValidationError({"refresh": "Token inválido ou expirado."})


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def get_usuario(self):
        """Retorna o usuário ativo do email, ou None (não vaza existência)."""
        return Usuario.objects.filter(
            email__iexact=self.validated_data["email"], is_active=True
        ).first()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    password = serializers.CharField(validators=[validate_password])

    def validate(self, attrs):
        try:
            pk = force_str(urlsafe_base64_decode(attrs["uid"]))
            usuario = Usuario.objects.get(pk=pk)
        except (Usuario.DoesNotExist, ValueError, TypeError, OverflowError):
            raise serializers.ValidationError({"uid": "Identificador inválido."})
        if not default_token_generator.check_token(usuario, attrs["token"]):
            raise serializers.ValidationError({"token": "Token inválido ou expirado."})
        attrs["usuario"] = usuario
        return attrs

    def save(self, **kwargs):
        usuario = self.validated_data["usuario"]
        usuario.set_password(self.validated_data["password"])
        usuario.save(update_fields=["password"])
        return usuario


def make_reset_tokens(usuario):
    """Gera (uid, token) para o fluxo de recuperação de senha."""
    return (
        urlsafe_base64_encode(force_bytes(usuario.pk)),
        default_token_generator.make_token(usuario),
    )
