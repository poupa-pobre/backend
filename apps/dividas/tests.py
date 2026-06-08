from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.cartoes.models import Cartao
from apps.vinculos.models import Vinculo

from .models import Divida, Parcela

Usuario = get_user_model()


def criar_usuario(email, nome="User"):
    return Usuario.objects.create_user(email=email, nome=nome, password="senha-forte-123")


def criar_cartao(usuario, **kwargs):
    defaults = {
        "nome": "Nubank",
        "limite_total": Decimal("10000.00"),
        "dia_fechamento": 10,
        "dia_vencimento": 17,
    }
    defaults.update(kwargs)
    return Cartao.objects.create(usuario=usuario, **defaults)


def criar_divida(usuario, **kwargs):
    defaults = {
        "descricao": "iPhone 15",
        "tipo": Divida.Tipo.EMPRESTIMO,
        "valor_total": Decimal("1200.00"),
        "numero_parcelas": 12,
        "valor_parcela": Decimal("100.00"),
        "data_primeira_parcela": date(2026, 5, 20),
    }
    defaults.update(kwargs)
    return Divida.objects.create(usuario=usuario, **defaults)


class DividaModelTest(APITestCase):
    def setUp(self):
        self.ana = criar_usuario("ana@x.com", "Ana")

    def test_gera_todas_as_parcelas(self):
        divida = criar_divida(self.ana)
        divida.gerar_parcelas()
        self.assertEqual(divida.parcelas.count(), 12)

    def test_datas_e_meses_avancam(self):
        divida = criar_divida(self.ana, numero_parcelas=3)
        divida.gerar_parcelas()
        p = list(divida.parcelas.order_by("numero"))
        self.assertEqual(p[0].data_vencimento, date(2026, 5, 20))
        self.assertEqual(p[0].mes_referencia, date(2026, 5, 1))
        self.assertEqual(p[1].data_vencimento, date(2026, 6, 20))
        self.assertEqual(p[2].mes_referencia, date(2026, 7, 1))

    def test_parcela_inicial_gera_do_meio(self):
        divida = criar_divida(self.ana, numero_parcelas=12, parcela_inicial=10)
        divida.gerar_parcelas()
        numeros = list(divida.parcelas.order_by("numero").values_list("numero", flat=True))
        self.assertEqual(numeros, [10, 11, 12])

    def test_gerar_parcelas_idempotente(self):
        divida = criar_divida(self.ana, numero_parcelas=3)
        divida.gerar_parcelas()
        divida.gerar_parcelas()
        self.assertEqual(divida.parcelas.count(), 3)

    def test_parcela_no_cartao_liga_fatura(self):
        cartao = criar_cartao(self.ana)
        divida = criar_divida(
            self.ana,
            tipo=Divida.Tipo.PARCELAMENTO_CARTAO,
            cartao=cartao,
            numero_parcelas=2,
        )
        divida.gerar_parcelas()
        for parcela in divida.parcelas.all():
            self.assertIsNotNone(parcela.fatura)
            self.assertEqual(parcela.fatura.cartao_id, cartao.id)

    def test_projecao_de_quitacao(self):
        divida = criar_divida(self.ana, numero_parcelas=3)
        divida.gerar_parcelas()
        primeira = divida.parcelas.order_by("numero").first()
        primeira.status = Parcela.Status.PAGA
        primeira.save()
        self.assertEqual(divida.valor_pago, Decimal("100.00"))
        self.assertEqual(divida.valor_restante, Decimal("200.00"))
        self.assertEqual(divida.mes_quitacao, date(2026, 7, 1))


class DividaEndpointsTest(APITestCase):
    def setUp(self):
        self.ana = criar_usuario("ana@x.com", "Ana")
        self.client.force_authenticate(self.ana)
        self.cartao = criar_cartao(self.ana)

    def _payload(self, **over):
        base = {
            "descricao": "Notebook",
            "tipo": "emprestimo",
            "valor_total": "1200.00",
            "numero_parcelas": 12,
            "valor_parcela": "100.00",
            "data_primeira_parcela": "2026-05-20",
        }
        base.update(over)
        return base

    def test_cria_divida_gera_parcelas(self):
        resp = self.client.post(reverse("dividas:divida-list"), self._payload())
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(len(resp.data["parcelas"]), 12)
        self.assertEqual(resp.data["valor_restante"], "1200.00")

    def test_parcelamento_cartao_exige_cartao(self):
        resp = self.client.post(
            reverse("dividas:divida-list"),
            self._payload(tipo="parcelamento_cartao"),
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("cartao", resp.data)

    def test_cartao_so_no_parcelamento_cartao(self):
        resp = self.client.post(
            reverse("dividas:divida-list"),
            self._payload(tipo="emprestimo", cartao=self.cartao.id),
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("cartao", resp.data)

    def test_parcela_inicial_maior_que_total_invalido(self):
        resp = self.client.post(
            reverse("dividas:divida-list"),
            self._payload(numero_parcelas=3, parcela_inicial=5),
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("parcela_inicial", resp.data)

    def test_escopo_por_usuario(self):
        bia = criar_usuario("bia@x.com", "Bia")
        criar_divida(bia)
        resp = self.client.get(reverse("dividas:divida-list"))
        self.assertEqual(resp.data["count"], 0)

    def test_pagar_parcela(self):
        resp = self.client.post(reverse("dividas:divida-list"), self._payload())
        parcela_id = resp.data["parcelas"][0]["id"]
        pagar = self.client.post(
            reverse("dividas:parcela-pagar", args=[parcela_id])
        )
        self.assertEqual(pagar.status_code, status.HTTP_200_OK, pagar.data)
        self.assertEqual(pagar.data["status"], "paga")

    def test_pagar_parcela_duplicado_falha(self):
        resp = self.client.post(reverse("dividas:divida-list"), self._payload())
        parcela_id = resp.data["parcelas"][0]["id"]
        url = reverse("dividas:parcela-pagar", args=[parcela_id])
        self.client.post(url)
        segundo = self.client.post(url)
        self.assertEqual(segundo.status_code, status.HTTP_400_BAD_REQUEST)

    def test_filtra_parcelas_por_status(self):
        resp = self.client.post(reverse("dividas:divida-list"), self._payload())
        parcela_id = resp.data["parcelas"][0]["id"]
        self.client.post(reverse("dividas:parcela-pagar", args=[parcela_id]))
        lista = self.client.get(reverse("dividas:parcela-list"), {"status": "paga"})
        self.assertEqual(lista.data["count"], 1)


class DividaCompartilhadaTest(APITestCase):
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
            "descricao": "Viagem",
            "tipo": "emprestimo",
            "valor_total": "1200.00",
            "numero_parcelas": 12,
            "valor_parcela": "100.00",
            "data_primeira_parcela": "2026-05-20",
            "compartilhado": True,
            "vinculo": self.vinculo.id,
            "valor_dono": "700.00",
            "valor_vinculado": "500.00",
        }
        base.update(over)
        return base

    def test_rateio_ok(self):
        resp = self.client.post(reverse("dividas:divida-list"), self._payload())
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)

    def test_rateio_que_nao_fecha_invalido(self):
        resp = self.client.post(
            reverse("dividas:divida-list"), self._payload(valor_vinculado="100.00")
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("valor_dono", resp.data)

    def test_vinculo_de_terceiro_invalido(self):
        carla = criar_usuario("carla@x.com", "Carla")
        alheio = Vinculo.objects.create(
            solicitante=self.bia,
            destinatario=carla,
            status=Vinculo.Status.ACEITO,
        )
        resp = self.client.post(
            reverse("dividas:divida-list"), self._payload(vinculo=alheio.id)
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("vinculo", resp.data)
