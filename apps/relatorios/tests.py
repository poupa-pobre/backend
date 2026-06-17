from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.categorias.models import Categoria
from apps.gastos.models import Gasto

from .pdf import _brl, gerar_pdf_relatorio

Usuario = get_user_model()


class PdfRelatorioTest(SimpleTestCase):
    def test_brl_formata_milhar(self):
        self.assertEqual(_brl(Decimal("1234567.8")), "R$ 1.234.567,80")
        self.assertEqual(_brl(0), "R$ 0,00")

    def test_gera_pdf_valido(self):
        dados = {
            "mes_referencia": date(2024, 1, 1),
            "total": Decimal("150.00"),
            "total_mes_anterior": Decimal("100.00"),
            "categorias": [
                {"categoria": 1, "nome": "Mercado", "cor": "#fff", "total": Decimal("150.00")},
            ],
        }
        pdf = gerar_pdf_relatorio(dados, nome_usuario="Fulano")
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 800)

    def test_gera_pdf_sem_categorias(self):
        dados = {
            "mes_referencia": date(2024, 1, 1),
            "total": Decimal("0.00"),
            "total_mes_anterior": Decimal("0.00"),
            "categorias": [],
        }
        self.assertTrue(gerar_pdf_relatorio(dados).startswith(b"%PDF"))


class PdfEndpointTest(APITestCase):
    def setUp(self):
        self.user = Usuario.objects.create_user(email="r@x.com", password="x", nome="R")
        self.client.force_authenticate(self.user)
        self.cat = Categoria.objects.create(usuario=self.user, nome="Mercado")
        Gasto.objects.create(
            usuario=self.user, descricao="Compras", valor=Decimal("80.00"),
            data=date(2024, 1, 10), categoria=self.cat, forma_pagamento="debito",
        )

    def test_pdf_endpoint_devolve_pdf(self):
        resp = self.client.get(
            reverse("relatorios:gastos-por-categoria-pdf"), {"mes": "2024-01-01"}
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertIn("attachment", resp["Content-Disposition"])
        self.assertTrue(resp.content.startswith(b"%PDF"))

    def test_pdf_exige_autenticacao(self):
        self.client.force_authenticate(None)
        resp = self.client.get(reverse("relatorios:gastos-por-categoria-pdf"))
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
