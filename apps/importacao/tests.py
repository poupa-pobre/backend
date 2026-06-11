from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.categorias.models import Categoria
from apps.gastos.models import Gasto
from apps.receitas.models import Receita

from .models import MovimentacaoDetectada
from .pix import identificar_banco, parsear_notificacao

Usuario = get_user_model()


class PixNotificacaoTest(SimpleTestCase):
    def test_nubank_recebido_com_nome(self):
        r = parsear_notificacao(
            titulo="Transferência recebida",
            texto="Você recebeu uma transferência de R$2,00 de Fulano de Tal",
        )
        self.assertEqual(r["tipo"], "recebido")
        self.assertEqual(r["valor"], 2.0)
        self.assertEqual(r["contraparte"], "Fulano de Tal")

    def test_nubank_recebido_sem_nome(self):
        r = parsear_notificacao(texto="Recebemos sua transferência de R$ 50,00")
        self.assertEqual(r["tipo"], "recebido")
        self.assertEqual(r["valor"], 50.0)
        self.assertIsNone(r["contraparte"])

    def test_enviado_com_nome_e_valor_grande(self):
        r = parsear_notificacao(texto="Pix enviado: R$ 1.234,56 para Maria Souza")
        self.assertEqual(r["tipo"], "enviado")
        self.assertEqual(r["valor"], 1234.56)
        self.assertEqual(r["contraparte"], "Maria Souza")

    def test_nao_e_pix(self):
        r = parsear_notificacao(texto="Sua fatura fecha amanhã")
        self.assertIsNone(r["tipo"])

    def test_identificar_banco_por_pacote(self):
        self.assertEqual(identificar_banco("com.nu.production"), "Nubank")
        self.assertIsNone(identificar_banco("com.whatsapp"))


class CaixaRevisaoEndpointTest(APITestCase):
    def setUp(self):
        self.user = Usuario.objects.create_user(email="a@x.com", password="x", nome="A")
        self.client.force_authenticate(self.user)
        self.cat = Categoria.objects.create(usuario=self.user, nome="Mercado")

    def _receber(self, **body):
        return self.client.post(reverse("importacao:movimentacaodetectada-list"), body, format="json")

    def test_nao_pix_nao_guarda(self):
        resp = self._receber(texto="Promoção imperdível!")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["ignorada"])
        self.assertEqual(MovimentacaoDetectada.objects.count(), 0)

    def test_recebido_guarda_pendente(self):
        resp = self._receber(
            pacote="com.nu.production",
            texto="Você recebeu uma transferência de R$2,00 de João",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(resp.data["tipo"], "recebido")
        self.assertEqual(Decimal(resp.data["valor"]), Decimal("2.00"))
        self.assertEqual(resp.data["contraparte"], "João")
        self.assertEqual(resp.data["banco"], "Nubank")
        self.assertEqual(resp.data["status"], "pendente")

    def test_dedupe_nao_duplica(self):
        body = dict(pacote="com.nu.production", texto="Você recebeu uma transferência de R$2,00 de João")
        self._receber(**body)
        self._receber(**body)
        self.assertEqual(MovimentacaoDetectada.objects.count(), 1)

    def test_confirmar_recebido_cria_receita(self):
        resp = self._receber(texto="Você recebeu uma transferência de R$10,00 de Ana")
        mov_id = resp.data["id"]
        resp = self.client.post(
            reverse("importacao:movimentacaodetectada-confirmar", args=[mov_id])
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["status"], "confirmada")
        self.assertIsNotNone(resp.data["receita"])
        rec = Receita.objects.get(id=resp.data["receita"])
        self.assertEqual(rec.valor, Decimal("10.00"))
        self.assertEqual(rec.descricao, "Pix de Ana")
        self.assertIsNotNone(rec.data_real)  # já recebida

    def test_confirmar_enviado_cria_gasto_pix(self):
        resp = self._receber(texto="Pix enviado R$ 25,00 para Padaria")
        mov_id = resp.data["id"]
        resp = self.client.post(
            reverse("importacao:movimentacaodetectada-confirmar", args=[mov_id]),
            {"categoria": self.cat.id},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        gasto = Gasto.objects.get(id=resp.data["gasto"])
        self.assertEqual(gasto.valor, Decimal("25.00"))
        self.assertEqual(gasto.forma_pagamento, "pix")
        self.assertEqual(gasto.categoria_id, self.cat.id)

    def test_confirmar_sem_valor_pede_valor(self):
        resp = self._receber(texto="Transferência recebida")  # sem valor
        mov_id = resp.data["id"]
        resp = self.client.post(
            reverse("importacao:movimentacaodetectada-confirmar", args=[mov_id])
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_ignorar(self):
        resp = self._receber(texto="Você recebeu uma transferência de R$5,00 de Zé")
        mov_id = resp.data["id"]
        resp = self.client.post(
            reverse("importacao:movimentacaodetectada-ignorar", args=[mov_id])
        )
        self.assertEqual(resp.data["status"], "ignorada")

    def test_escopo_por_usuario(self):
        self._receber(texto="Você recebeu uma transferência de R$5,00 de Zé")
        outro = Usuario.objects.create_user(email="b@x.com", password="x", nome="B")
        self.client.force_authenticate(outro)
        resp = self.client.get(reverse("importacao:movimentacaodetectada-list"))
        self.assertEqual(len(resp.data["results"]), 0)
