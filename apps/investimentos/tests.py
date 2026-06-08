from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Investimento

Usuario = get_user_model()


def criar_usuario(email, nome="User"):
    return Usuario.objects.create_user(email=email, nome=nome, password="senha-forte-123")


def criar_aporte(usuario, **kwargs):
    defaults = {
        "tipo": Investimento.Tipo.RENDA_FIXA,
        "valor_aportado": Decimal("1000.00"),
        "data_aporte": date(2026, 6, 5),
    }
    defaults.update(kwargs)
    return Investimento.objects.create(usuario=usuario, **defaults)


class InvestimentoAPITest(APITestCase):
    def setUp(self):
        self.ana = criar_usuario("ana@x.com", "Ana")
        self.bia = criar_usuario("bia@x.com", "Bia")
        self.client.force_authenticate(self.ana)

    def test_criar_aporte(self):
        resp = self.client.post(
            reverse("investimentos:investimento-list"),
            {
                "tipo": Investimento.Tipo.ACOES,
                "valor_aportado": "500.00",
                "data_aporte": "2026-06-05",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Investimento.objects.get().usuario, self.ana)

    def test_lista_so_do_dono(self):
        criar_aporte(self.ana)
        criar_aporte(self.bia)
        resp = self.client.get(reverse("investimentos:investimento-list"))
        self.assertEqual(len(resp.data["results"]), 1)

    def test_valor_negativo_rejeitado(self):
        resp = self.client.post(
            reverse("investimentos:investimento-list"),
            {
                "tipo": Investimento.Tipo.CRIPTO,
                "valor_aportado": "0.00",
                "data_aporte": "2026-06-05",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class ConsolidadoTest(APITestCase):
    def setUp(self):
        self.ana = criar_usuario("ana@x.com", "Ana")
        self.client.force_authenticate(self.ana)

    def test_consolidado_totais(self):
        criar_aporte(self.ana, tipo=Investimento.Tipo.RENDA_FIXA, valor_aportado=Decimal("1000.00"), data_aporte=date(2026, 5, 10))
        criar_aporte(self.ana, tipo=Investimento.Tipo.RENDA_FIXA, valor_aportado=Decimal("500.00"), data_aporte=date(2026, 6, 10))
        criar_aporte(self.ana, tipo=Investimento.Tipo.ACOES, valor_aportado=Decimal("300.00"), data_aporte=date(2026, 6, 10))

        resp = self.client.get(reverse("investimentos:investimento-consolidado"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(Decimal(resp.data["total_geral"]), Decimal("1800.00"))

        por_tipo = {linha["tipo"]: Decimal(linha["total"]) for linha in resp.data["por_tipo"]}
        self.assertEqual(por_tipo["renda_fixa"], Decimal("1500.00"))
        self.assertEqual(por_tipo["acoes"], Decimal("300.00"))
        # Dois meses distintos no histórico.
        self.assertEqual(len(resp.data["por_mes"]), 2)

    def test_consolidado_vazio(self):
        resp = self.client.get(reverse("investimentos:investimento-consolidado"))
        self.assertEqual(Decimal(resp.data["total_geral"]), Decimal("0.00"))
        self.assertEqual(resp.data["por_tipo"], [])
