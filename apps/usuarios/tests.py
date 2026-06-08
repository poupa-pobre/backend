from django.contrib.auth import get_user_model
from django.core import mail
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .serializers import make_reset_tokens

Usuario = get_user_model()


class UsuarioModelTest(APITestCase):
    def test_create_user_normaliza_email_e_hash_senha(self):
        u = Usuario.objects.create_user(
            email="Ana@Exemplo.COM", nome="Ana", password="senha-forte-123"
        )
        # normalize_email só mexe no domínio; a senha é guardada como hash.
        self.assertEqual(u.email, "Ana@exemplo.com")
        self.assertNotEqual(u.password, "senha-forte-123")
        self.assertTrue(u.check_password("senha-forte-123"))
        self.assertFalse(u.is_staff)
        self.assertTrue(u.is_active)

    def test_create_user_sem_email_falha(self):
        with self.assertRaises(ValueError):
            Usuario.objects.create_user(email="", nome="X", password="x")

    def test_create_superuser(self):
        su = Usuario.objects.create_superuser(
            email="root@exemplo.com", nome="Root", password="x123456789"
        )
        self.assertTrue(su.is_staff)
        self.assertTrue(su.is_superuser)

    def test_email_unico(self):
        Usuario.objects.create_user(email="a@b.com", nome="A", password="x123456789")
        from django.db import IntegrityError, transaction

        with self.assertRaises(IntegrityError), transaction.atomic():
            Usuario.objects.create_user(email="a@b.com", nome="B", password="x123456789")

    def test_str(self):
        u = Usuario.objects.create_user(email="a@b.com", nome="Ana", password="x123456789")
        self.assertEqual(str(u), "Ana <a@b.com>")


class AuthEndpointsTest(APITestCase):
    def setUp(self):
        self.senha = "senha-forte-123"
        self.user = Usuario.objects.create_user(
            email="ana@exemplo.com", nome="Ana", password=self.senha
        )

    def test_registro_cria_usuario(self):
        resp = self.client.post(
            reverse("usuarios:registro"),
            {"nome": "Bia", "email": "bia@exemplo.com", "password": "outra-senha-456"},
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertNotIn("password", resp.data)
        self.assertTrue(Usuario.objects.filter(email="bia@exemplo.com").exists())

    def test_registro_rejeita_senha_fraca(self):
        resp = self.client.post(
            reverse("usuarios:registro"),
            {"nome": "Bia", "email": "bia@exemplo.com", "password": "123"},
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_por_email_retorna_tokens(self):
        resp = self.client.post(
            reverse("usuarios:login"),
            {"email": "ana@exemplo.com", "password": self.senha},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("access", resp.data)
        self.assertIn("refresh", resp.data)

    def test_login_senha_errada(self):
        resp = self.client.post(
            reverse("usuarios:login"),
            {"email": "ana@exemplo.com", "password": "errada"},
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_exige_autenticacao(self):
        self.assertEqual(
            self.client.get(reverse("usuarios:me")).status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_me_autenticado(self):
        self.client.force_authenticate(self.user)
        resp = self.client.get(reverse("usuarios:me"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["email"], "ana@exemplo.com")

    def _tokens(self):
        resp = self.client.post(
            reverse("usuarios:login"),
            {"email": "ana@exemplo.com", "password": self.senha},
        )
        return resp.data["access"], resp.data["refresh"]

    def test_refresh_renova_access(self):
        _, refresh = self._tokens()
        resp = self.client.post(reverse("usuarios:refresh"), {"refresh": refresh})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("access", resp.data)

    def test_logout_blacklista_refresh(self):
        access, refresh = self._tokens()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        resp = self.client.post(reverse("usuarios:logout"), {"refresh": refresh})
        self.assertEqual(resp.status_code, status.HTTP_205_RESET_CONTENT)
        # refresh já não vale mais
        self.client.credentials()
        again = self.client.post(reverse("usuarios:refresh"), {"refresh": refresh})
        self.assertEqual(again.status_code, status.HTTP_401_UNAUTHORIZED)


class PasswordResetTest(APITestCase):
    def setUp(self):
        self.user = Usuario.objects.create_user(
            email="ana@exemplo.com", nome="Ana", password="senha-antiga-123"
        )

    def test_request_envia_email(self):
        resp = self.client.post(
            reverse("usuarios:senha-recuperar"), {"email": "ana@exemplo.com"}
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("ana@exemplo.com", mail.outbox[0].to)

    def test_request_email_inexistente_nao_vaza(self):
        resp = self.client.post(
            reverse("usuarios:senha-recuperar"), {"email": "ninguem@exemplo.com"}
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 0)

    def test_confirm_redefine_senha(self):
        uid, token = make_reset_tokens(self.user)
        resp = self.client.post(
            reverse("usuarios:senha-confirmar"),
            {"uid": uid, "token": token, "password": "senha-nova-456"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("senha-nova-456"))

    def test_confirm_token_invalido(self):
        uid, _ = make_reset_tokens(self.user)
        resp = self.client.post(
            reverse("usuarios:senha-confirmar"),
            {"uid": uid, "token": "token-falso", "password": "senha-nova-456"},
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
