from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.cartoes.models import Cartao
from apps.categorias.models import Categoria
from apps.gastos.models import Gasto
from apps.gastos_fixos.models import GastoFixo, GastoFixoMensal
from apps.receitas.models import Receita

Usuario = get_user_model()
MES = date(2026, 6, 1)


def criar_usuario(email, nome="User"):
    return Usuario.objects.create_user(email=email, nome=nome, password="senha-forte-123")


class DashboardTest(APITestCase):
    def setUp(self):
        self.ana = criar_usuario("ana@x.com", "Ana")
        self.categoria = Categoria.objects.create(usuario=self.ana, nome="Mercado")
        self.client.force_authenticate(self.ana)

    def _cenario(self):
        Receita.objects.create(
            usuario=self.ana,
            descricao="Salário",
            valor=Decimal("5000.00"),
            data_prevista=date(2026, 6, 1),
            data_real=date(2026, 6, 5),
            tipo=Receita.Tipo.SALARIO,
        )
        Receita.objects.create(
            usuario=self.ana,
            descricao="Freela",
            valor=Decimal("1000.00"),
            data_prevista=date(2026, 6, 20),
            tipo=Receita.Tipo.FREELANCE,
        )
        Gasto.objects.create(
            usuario=self.ana,
            descricao="Feira",
            valor=Decimal("200.00"),
            data=date(2026, 6, 10),
            categoria=self.categoria,
            forma_pagamento=Gasto.FormaPagamento.PIX,
        )
        fixo = GastoFixo.objects.create(
            usuario=self.ana,
            descricao="Aluguel",
            tipo=GastoFixo.Tipo.FIXO,
            valor=Decimal("1500.00"),
            categoria=self.categoria,
            forma_pagamento=GastoFixo.FormaPagamento.BOLETO,
            dia_vencimento=10,
        )
        GastoFixoMensal.objects.create(gasto_fixo=fixo, mes_referencia=MES)

    def test_cards(self):
        self._cenario()
        resp = self.client.get(reverse("dashboard:dashboard"), {"mes": "2026-06-01"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        cards = resp.data["cards"]
        self.assertEqual(Decimal(cards["receitas"]["previsto"]), Decimal("6000.00"))
        self.assertEqual(Decimal(cards["receitas"]["recebido"]), Decimal("5000.00"))
        self.assertEqual(Decimal(cards["gastos_fixos"]["total"]), Decimal("1500.00"))
        self.assertEqual(cards["gastos_fixos"]["pagos"], 0)
        self.assertEqual(cards["gastos_fixos"]["quantidade"], 1)
        # Saldo: 5000 recebido − 200 variável (fixo e fatura não pagos) = 4800.
        self.assertEqual(Decimal(cards["saldo_disponivel"]), Decimal("4800.00"))
        # Economia: 5000 − (200 variável + 1500 fixo) = 3300.
        self.assertEqual(Decimal(cards["economia_do_mes"]), Decimal("3300.00"))

    def test_secoes(self):
        self._cenario()
        resp = self.client.get(reverse("dashboard:dashboard"), {"mes": "2026-06-01"})
        self.assertEqual(len(resp.data["fixos_pendentes"]), 1)
        self.assertEqual(resp.data["fixos_pendentes"][0]["descricao"], "Aluguel")
        self.assertEqual(len(resp.data["ultimos_lancamentos"]), 1)

    def test_faturas_no_dashboard(self):
        cartao = Cartao.objects.create(
            usuario=self.ana,
            nome="Nubank",
            limite_total=Decimal("5000.00"),
            dia_fechamento=10,
            dia_vencimento=17,
        )
        Gasto.objects.create(
            usuario=self.ana,
            descricao="TV",
            valor=Decimal("800.00"),
            data=date(2026, 6, 5),
            categoria=self.categoria,
            forma_pagamento=Gasto.FormaPagamento.CREDITO,
            cartao=cartao,
        )
        resp = self.client.get(reverse("dashboard:dashboard"), {"mes": "2026-06-01"})
        cartoes = resp.data["cards"]["cartoes"]
        self.assertEqual(Decimal(cartoes["total_faturas_abertas"]), Decimal("800.00"))
        self.assertEqual(len(resp.data["faturas_cartoes"]), 1)
        self.assertEqual(resp.data["faturas_cartoes"][0]["cartao"], "Nubank")

    def test_mes_vazio(self):
        resp = self.client.get(reverse("dashboard:dashboard"), {"mes": "2026-06-01"})
        self.assertEqual(Decimal(resp.data["cards"]["saldo_disponivel"]), Decimal("0.00"))
        self.assertEqual(resp.data["fixos_pendentes"], [])

    def test_mes_invalido(self):
        resp = self.client.get(reverse("dashboard:dashboard"), {"mes": "junho"})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_exige_autenticacao(self):
        self.client.force_authenticate(None)
        resp = self.client.get(reverse("dashboard:dashboard"))
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
