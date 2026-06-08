from django.contrib.auth import get_user_model
from django.core import mail
from django.db import IntegrityError, transaction
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Vinculo

Usuario = get_user_model()


def criar_usuario(email, nome):
    return Usuario.objects.create_user(email=email, nome=nome, password="senha-forte-123")


class VinculoModelTest(APITestCase):
    def setUp(self):
        self.ana = criar_usuario("ana@x.com", "Ana")
        self.bia = criar_usuario("bia@x.com", "Bia")

    def test_par_unico_na_mesma_direcao(self):
        Vinculo.objects.create(solicitante=self.ana, destinatario=self.bia)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Vinculo.objects.create(solicitante=self.ana, destinatario=self.bia)

    def test_nao_pode_se_auto_vincular(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Vinculo.objects.create(solicitante=self.ana, destinatario=self.ana)

    def test_outro_retorna_a_ponta_oposta(self):
        v = Vinculo.objects.create(solicitante=self.ana, destinatario=self.bia)
        self.assertEqual(v.outro(self.ana), self.bia)
        self.assertEqual(v.outro(self.bia), self.ana)


class VinculoEndpointsTest(APITestCase):
    def setUp(self):
        self.ana = criar_usuario("ana@x.com", "Ana")
        self.bia = criar_usuario("bia@x.com", "Bia")
        self.client.force_authenticate(self.ana)

    def test_convite_cria_pendente_e_envia_email(self):
        resp = self.client.post(reverse("vinculos:vinculo-list"), {"email": "bia@x.com"})
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["status"], "pendente")
        self.assertEqual(resp.data["outro_usuario"]["email"], "bia@x.com")
        self.assertTrue(resp.data["sou_solicitante"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("bia@x.com", mail.outbox[0].to)

    def test_nao_convida_a_si_mesmo(self):
        resp = self.client.post(reverse("vinculos:vinculo-list"), {"email": "ana@x.com"})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_nao_convida_email_inexistente(self):
        resp = self.client.post(reverse("vinculos:vinculo-list"), {"email": "ninguem@x.com"})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_convite_duplicado_pendente_bloqueado(self):
        self.client.post(reverse("vinculos:vinculo-list"), {"email": "bia@x.com"})
        resp = self.client.post(reverse("vinculos:vinculo-list"), {"email": "bia@x.com"})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_convite_reverso_pendente_bloqueado(self):
        # Ana convida Bia; depois Bia tenta convidar Ana -> mesmo par.
        self.client.post(reverse("vinculos:vinculo-list"), {"email": "bia@x.com"})
        self.client.force_authenticate(self.bia)
        resp = self.client.post(reverse("vinculos:vinculo-list"), {"email": "ana@x.com"})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_destinatario_aceita(self):
        v = Vinculo.objects.create(solicitante=self.ana, destinatario=self.bia)
        self.client.force_authenticate(self.bia)
        resp = self.client.post(reverse("vinculos:vinculo-aceitar", args=[v.id]))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        v.refresh_from_db()
        self.assertEqual(v.status, Vinculo.Status.ACEITO)
        self.assertIsNotNone(v.accepted_at)

    def test_solicitante_nao_pode_aceitar(self):
        v = Vinculo.objects.create(solicitante=self.ana, destinatario=self.bia)
        resp = self.client.post(reverse("vinculos:vinculo-aceitar", args=[v.id]))
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_destinatario_recusa(self):
        v = Vinculo.objects.create(solicitante=self.ana, destinatario=self.bia)
        self.client.force_authenticate(self.bia)
        resp = self.client.post(reverse("vinculos:vinculo-recusar", args=[v.id]))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        v.refresh_from_db()
        self.assertEqual(v.status, Vinculo.Status.RECUSADO)

    def test_nao_aceita_se_nao_pendente(self):
        v = Vinculo.objects.create(
            solicitante=self.ana, destinatario=self.bia, status=Vinculo.Status.ACEITO
        )
        self.client.force_authenticate(self.bia)
        resp = self.client.post(reverse("vinculos:vinculo-aceitar", args=[v.id]))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reabre_convite_apos_recusa(self):
        v = Vinculo.objects.create(
            solicitante=self.ana, destinatario=self.bia, status=Vinculo.Status.RECUSADO
        )
        resp = self.client.post(reverse("vinculos:vinculo-list"), {"email": "bia@x.com"})
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        v.refresh_from_db()
        self.assertEqual(v.status, Vinculo.Status.PENDENTE)
        self.assertEqual(Vinculo.objects.count(), 1)

    def test_listagem_escopo_so_minhas_pontas(self):
        carol = criar_usuario("carol@x.com", "Carol")
        meu = Vinculo.objects.create(solicitante=self.ana, destinatario=self.bia)
        Vinculo.objects.create(solicitante=self.bia, destinatario=carol)  # não é minha
        resp = self.client.get(reverse("vinculos:vinculo-list"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in resp.data["results"]]
        self.assertEqual(ids, [meu.id])

    def test_desfazer_remove_vinculo(self):
        v = Vinculo.objects.create(
            solicitante=self.ana, destinatario=self.bia, status=Vinculo.Status.ACEITO
        )
        resp = self.client.delete(reverse("vinculos:vinculo-detail", args=[v.id]))
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Vinculo.objects.filter(id=v.id).exists())

    def test_nao_acessa_vinculo_de_terceiros(self):
        carol = criar_usuario("carol@x.com", "Carol")
        alheio = Vinculo.objects.create(solicitante=self.bia, destinatario=carol)
        resp = self.client.post(reverse("vinculos:vinculo-aceitar", args=[alheio.id]))
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_exige_autenticacao(self):
        self.client.force_authenticate(None)
        resp = self.client.get(reverse("vinculos:vinculo-list"))
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
