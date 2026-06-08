from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.cartoes.models import Cartao
from apps.categorias.models import Categoria
from apps.gastos.models import Gasto
from apps.vinculos.models import Vinculo

from .models import Receita

Usuario = get_user_model()


def criar_usuario(email, nome="User"):
    return Usuario.objects.create_user(email=email, nome=nome, password="senha-forte-123")


class ReceitaModelTest(APITestCase):
    def setUp(self):
        self.ana = criar_usuario("ana@x.com", "Ana")

    def test_mes_referencia_pelo_1o_dia_da_data_prevista(self):
        r = Receita.objects.create(
            usuario=self.ana,
            descricao="Salário maio",
            valor=Decimal("5000.00"),
            data_prevista=date(2026, 5, 5),
            tipo=Receita.Tipo.SALARIO,
        )
        self.assertEqual(r.mes_referencia, date(2026, 5, 1))

    def test_status_derivado_de_data_real(self):
        r = Receita.objects.create(
            usuario=self.ana,
            descricao="Freela",
            valor=Decimal("800.00"),
            data_prevista=date(2026, 5, 5),
            tipo=Receita.Tipo.FREELANCE,
        )
        self.assertEqual(r.status, Receita.Status.PREVISTA)
        r.data_real = date(2026, 5, 6)
        r.save()
        self.assertEqual(r.status, Receita.Status.RECEBIDA)

    def test_recorrencia_pre_cria_proximo_mes_como_prevista(self):
        r = Receita.objects.create(
            usuario=self.ana,
            descricao="Salário",
            valor=Decimal("5000.00"),
            data_prevista=date(2026, 5, 5),
            tipo=Receita.Tipo.SALARIO,
            recorrente=True,
        )
        prox = r.criar_recorrencia()
        self.assertEqual(prox.mes_referencia, date(2026, 6, 1))
        self.assertIsNone(prox.data_real)
        self.assertEqual(prox.status, Receita.Status.PREVISTA)

    def test_recorrencia_idempotente(self):
        r = Receita.objects.create(
            usuario=self.ana,
            descricao="Salário",
            valor=Decimal("5000.00"),
            data_prevista=date(2026, 5, 5),
            tipo=Receita.Tipo.SALARIO,
            recorrente=True,
        )
        r.criar_recorrencia()
        r.criar_recorrencia()
        self.assertEqual(
            Receita.objects.filter(mes_referencia=date(2026, 6, 1)).count(), 1
        )

    def test_recorrencia_em_dezembro_vira_janeiro(self):
        r = Receita.objects.create(
            usuario=self.ana,
            descricao="Salário",
            valor=Decimal("5000.00"),
            data_prevista=date(2026, 12, 5),
            tipo=Receita.Tipo.SALARIO,
            recorrente=True,
        )
        prox = r.criar_recorrencia()
        self.assertEqual(prox.mes_referencia, date(2027, 1, 1))

    def test_nao_recorrente_nao_pre_cria(self):
        r = Receita.objects.create(
            usuario=self.ana,
            descricao="Bônus",
            valor=Decimal("1000.00"),
            data_prevista=date(2026, 5, 5),
            tipo=Receita.Tipo.BONUS,
        )
        self.assertIsNone(r.criar_recorrencia())


class ReceitaEndpointsTest(APITestCase):
    def setUp(self):
        self.ana = criar_usuario("ana@x.com", "Ana")
        self.client.force_authenticate(self.ana)

    def _payload(self, **over):
        base = {
            "descricao": "Salário maio",
            "valor": "5000.00",
            "data_prevista": "2026-05-05",
            "tipo": "salario",
        }
        base.update(over)
        return base

    def test_cria_receita_simples(self):
        resp = self.client.post(reverse("receitas:receita-list"), self._payload())
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(resp.data["mes_referencia"], "2026-05-01")
        self.assertEqual(resp.data["status"], "prevista")

    def test_criar_recorrente_pre_cria_proximo_mes(self):
        resp = self.client.post(
            reverse("receitas:receita-list"), self._payload(recorrente=True)
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(Receita.objects.filter(usuario=self.ana).count(), 2)
        self.assertTrue(
            Receita.objects.filter(
                usuario=self.ana, mes_referencia=date(2026, 6, 1)
            ).exists()
        )

    def test_escopo_por_usuario_na_listagem(self):
        bia = criar_usuario("bia@x.com", "Bia")
        Receita.objects.create(
            usuario=bia,
            descricao="alheia",
            valor=Decimal("10.00"),
            data_prevista=date(2026, 5, 1),
            tipo=Receita.Tipo.OUTRO,
        )
        resp = self.client.get(reverse("receitas:receita-list"))
        self.assertEqual(resp.data["count"], 0)

    def test_filtra_por_status(self):
        Receita.objects.create(
            usuario=self.ana,
            descricao="recebida",
            valor=Decimal("100.00"),
            data_prevista=date(2026, 5, 1),
            data_real=date(2026, 5, 2),
            tipo=Receita.Tipo.OUTRO,
        )
        Receita.objects.create(
            usuario=self.ana,
            descricao="prevista",
            valor=Decimal("100.00"),
            data_prevista=date(2026, 5, 1),
            tipo=Receita.Tipo.OUTRO,
        )
        resp = self.client.get(
            reverse("receitas:receita-list"), {"status": "recebida"}
        )
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["results"][0]["descricao"], "recebida")

    def test_receber_marca_data_real(self):
        r = Receita.objects.create(
            usuario=self.ana,
            descricao="Freela",
            valor=Decimal("800.00"),
            data_prevista=date(2026, 5, 5),
            tipo=Receita.Tipo.FREELANCE,
        )
        resp = self.client.post(
            reverse("receitas:receita-receber", args=[r.id]),
            {"data_real": "2026-05-06"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["status"], "recebida")
        self.assertEqual(resp.data["data_real"], "2026-05-06")
        self.assertNotIn("cobertura", resp.data)  # só salário traz cobertura

    def test_receber_salario_traz_cobertura(self):
        r = Receita.objects.create(
            usuario=self.ana,
            descricao="Salário",
            valor=Decimal("5000.00"),
            data_prevista=date(2026, 5, 5),
            tipo=Receita.Tipo.SALARIO,
        )
        resp = self.client.post(reverse("receitas:receita-receber", args=[r.id]))
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertIn("cobertura", resp.data)
        self.assertTrue(resp.data["cobertura"]["coberta"])


class CoberturaTest(APITestCase):
    """RN-010: saldo disponível × faturas do mês ao receber salário."""

    def setUp(self):
        self.ana = criar_usuario("ana@x.com", "Ana")
        self.client.force_authenticate(self.ana)
        self.categoria = Categoria.objects.create(usuario=self.ana, nome="Casa")
        self.cartao = Cartao.objects.create(
            usuario=self.ana,
            nome="Nubank",
            limite_total=Decimal("5000.00"),
            dia_fechamento=10,
            dia_vencimento=17,
        )

    def _receber_salario(self, valor):
        r = Receita.objects.create(
            usuario=self.ana,
            descricao="Salário",
            valor=Decimal(valor),
            data_prevista=date(2026, 5, 5),
            tipo=Receita.Tipo.SALARIO,
        )
        resp = self.client.post(reverse("receitas:receita-receber", args=[r.id]))
        return resp.data["cobertura"]

    def _gasto(self, valor, forma, data=date(2026, 5, 5), cartao=None):
        Gasto.objects.create(
            usuario=self.ana,
            descricao="g",
            valor=Decimal(valor),
            data=data,
            categoria=self.categoria,
            forma_pagamento=forma,
            cartao=cartao,
        )

    def test_coberta_quando_saldo_cobre_fatura(self):
        self._gasto("1000.00", Gasto.FormaPagamento.CREDITO, cartao=self.cartao)
        cobertura = self._receber_salario("5000.00")
        self.assertEqual(cobertura["total_faturas"], Decimal("1000.00"))
        self.assertEqual(cobertura["saldo_disponivel"], Decimal("5000.00"))
        self.assertTrue(cobertura["coberta"])
        self.assertEqual(cobertura["falta"], Decimal("0.00"))

    def test_saldo_desconta_gastos_nao_credito(self):
        self._gasto("2000.00", Gasto.FormaPagamento.PIX)
        self._gasto("1500.00", Gasto.FormaPagamento.CREDITO, cartao=self.cartao)
        cobertura = self._receber_salario("2000.00")
        # saldo = 2000 (salário) - 2000 (pix) = 0; fatura = 1500 -> falta 1500
        self.assertEqual(cobertura["saldo_disponivel"], Decimal("0.00"))
        self.assertEqual(cobertura["total_faturas"], Decimal("1500.00"))
        self.assertFalse(cobertura["coberta"])
        self.assertEqual(cobertura["falta"], Decimal("1500.00"))


class ReceitaCompartilhadaTest(APITestCase):
    def setUp(self):
        self.ana = criar_usuario("ana@x.com", "Ana")
        self.bia = criar_usuario("bia@x.com", "Bia")
        self.client.force_authenticate(self.ana)
        self.vinculo = Vinculo.objects.create(
            solicitante=self.ana,
            destinatario=self.bia,
            status=Vinculo.Status.ACEITO,
        )

    def _payload(self, **over):
        base = {
            "descricao": "Aluguel",
            "valor": "2000.00",
            "data_prevista": "2026-05-05",
            "tipo": "aluguel",
            "compartilhada": True,
            "vinculo": self.vinculo.id,
            "valor_dono": "1200.00",
            "valor_vinculado": "800.00",
        }
        base.update(over)
        return base

    def test_rateio_que_fecha_o_total_ok(self):
        resp = self.client.post(reverse("receitas:receita-list"), self._payload())
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)

    def test_rateio_que_nao_fecha_invalido(self):
        resp = self.client.post(
            reverse("receitas:receita-list"), self._payload(valor_vinculado="500.00")
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("valor_dono", resp.data)

    def test_compartilhada_sem_vinculo_invalido(self):
        resp = self.client.post(
            reverse("receitas:receita-list"),
            self._payload(vinculo=None),
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("vinculo", resp.data)

    def test_vinculo_pendente_invalido(self):
        self.vinculo.status = Vinculo.Status.PENDENTE
        self.vinculo.save(update_fields=["status"])
        resp = self.client.post(reverse("receitas:receita-list"), self._payload())
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("vinculo", resp.data)

    def test_vinculo_de_terceiro_invalido(self):
        carla = criar_usuario("carla@x.com", "Carla")
        alheio = Vinculo.objects.create(
            solicitante=self.bia,
            destinatario=carla,
            status=Vinculo.Status.ACEITO,
        )
        resp = self.client.post(
            reverse("receitas:receita-list"), self._payload(vinculo=alheio.id)
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("vinculo", resp.data)

    def test_nao_compartilhada_zera_rateio(self):
        resp = self.client.post(
            reverse("receitas:receita-list"),
            self._payload(compartilhada=False),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertIsNone(resp.data["vinculo"])
        self.assertIsNone(resp.data["valor_dono"])
        self.assertIsNone(resp.data["valor_vinculado"])
