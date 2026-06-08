from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.cartoes.models import Cartao, Fatura
from apps.categorias.models import Categoria, Subcategoria, Tag
from apps.vinculos.models import Vinculo

from .models import Gasto

Usuario = get_user_model()


def criar_usuario(email, nome="User"):
    return Usuario.objects.create_user(email=email, nome=nome, password="senha-forte-123")


def criar_categoria(usuario, nome="Alimentação", **kwargs):
    return Categoria.objects.create(usuario=usuario, nome=nome, **kwargs)


def criar_cartao(usuario, **kwargs):
    defaults = {
        "nome": "Nubank",
        "limite_total": Decimal("5000.00"),
        "dia_fechamento": 10,
        "dia_vencimento": 17,
    }
    defaults.update(kwargs)
    return Cartao.objects.create(usuario=usuario, **defaults)


class GastoModelTest(APITestCase):
    def setUp(self):
        self.ana = criar_usuario("ana@x.com", "Ana")
        self.categoria = criar_categoria(self.ana)

    def test_mes_referencia_pelo_1o_dia_quando_nao_credito(self):
        gasto = Gasto.objects.create(
            usuario=self.ana,
            descricao="Mercado",
            valor=Decimal("80.00"),
            data=date(2026, 3, 15),
            categoria=self.categoria,
            forma_pagamento=Gasto.FormaPagamento.PIX,
        )
        self.assertEqual(gasto.mes_referencia, date(2026, 3, 1))

    def test_mes_referencia_segue_competencia_no_credito(self):
        cartao = criar_cartao(self.ana, dia_fechamento=10)
        gasto = Gasto.objects.create(
            usuario=self.ana,
            descricao="TV",
            valor=Decimal("2000.00"),
            data=date(2026, 3, 15),  # após o fechamento -> abril
            categoria=self.categoria,
            forma_pagamento=Gasto.FormaPagamento.CREDITO,
            cartao=cartao,
        )
        self.assertEqual(gasto.mes_referencia, date(2026, 4, 1))

    def test_credito_garante_fatura_do_mes(self):
        cartao = criar_cartao(self.ana, dia_fechamento=10)
        Gasto.objects.create(
            usuario=self.ana,
            descricao="TV",
            valor=Decimal("2000.00"),
            data=date(2026, 3, 15),
            categoria=self.categoria,
            forma_pagamento=Gasto.FormaPagamento.CREDITO,
            cartao=cartao,
        )
        self.assertTrue(
            Fatura.objects.filter(cartao=cartao, mes_referencia=date(2026, 4, 1)).exists()
        )


class GastoEndpointsTest(APITestCase):
    def setUp(self):
        self.ana = criar_usuario("ana@x.com", "Ana")
        self.client.force_authenticate(self.ana)
        self.categoria = criar_categoria(self.ana)
        self.cartao = criar_cartao(self.ana)

    def _payload(self, **over):
        base = {
            "descricao": "Padaria",
            "valor": "20.00",
            "data": "2026-03-05",
            "categoria": self.categoria.id,
            "forma_pagamento": "pix",
        }
        base.update(over)
        return base

    def test_cria_gasto_simples(self):
        resp = self.client.post(reverse("gastos:gasto-list"), self._payload())
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(resp.data["mes_referencia"], "2026-03-01")
        self.assertEqual(resp.data["origem"], "manual")

    def test_credito_exige_cartao(self):
        resp = self.client.post(
            reverse("gastos:gasto-list"),
            self._payload(forma_pagamento="credito"),
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("cartao", resp.data)

    def test_cartao_so_no_credito(self):
        resp = self.client.post(
            reverse("gastos:gasto-list"),
            self._payload(forma_pagamento="pix", cartao=self.cartao.id),
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("cartao", resp.data)

    def test_credito_com_cartao_ok(self):
        resp = self.client.post(
            reverse("gastos:gasto-list"),
            self._payload(forma_pagamento="credito", cartao=self.cartao.id),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)

    def test_cartao_de_terceiro_invalido(self):
        bia = criar_usuario("bia@x.com", "Bia")
        alheio = criar_cartao(bia)
        resp = self.client.post(
            reverse("gastos:gasto-list"),
            self._payload(forma_pagamento="credito", cartao=alheio.id),
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("cartao", resp.data)

    def test_categoria_de_terceiro_invalida(self):
        bia = criar_usuario("bia@x.com", "Bia")
        alheia = criar_categoria(bia)
        resp = self.client.post(
            reverse("gastos:gasto-list"), self._payload(categoria=alheia.id)
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("categoria", resp.data)

    def test_subcategoria_de_outra_categoria_invalida(self):
        outra = criar_categoria(self.ana, nome="Transporte")
        sub = Subcategoria.objects.create(categoria=outra, nome="Uber")
        resp = self.client.post(
            reverse("gastos:gasto-list"),
            self._payload(subcategoria=sub.id),  # categoria != outra
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("subcategoria", resp.data)

    def test_cria_com_tags(self):
        t1 = Tag.objects.create(usuario=self.ana, nome="essencial")
        t2 = Tag.objects.create(usuario=self.ana, nome="recorrente")
        resp = self.client.post(
            reverse("gastos:gasto-list"), self._payload(tags=[t1.id, t2.id])
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertCountEqual(resp.data["tags"], [t1.id, t2.id])

    def test_tag_de_terceiro_invalida(self):
        bia = criar_usuario("bia@x.com", "Bia")
        alheia = Tag.objects.create(usuario=bia, nome="x")
        resp = self.client.post(
            reverse("gastos:gasto-list"), self._payload(tags=[alheia.id])
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("tags", resp.data)

    def test_escopo_por_usuario_na_listagem(self):
        bia = criar_usuario("bia@x.com", "Bia")
        Gasto.objects.create(
            usuario=bia,
            descricao="alheio",
            valor=Decimal("10.00"),
            data=date(2026, 3, 1),
            categoria=criar_categoria(bia),
            forma_pagamento=Gasto.FormaPagamento.PIX,
        )
        resp = self.client.get(reverse("gastos:gasto-list"))
        self.assertEqual(resp.data["count"], 0)

    def test_filtra_por_mes_referencia(self):
        self.client.post(reverse("gastos:gasto-list"), self._payload(data="2026-03-05"))
        self.client.post(reverse("gastos:gasto-list"), self._payload(data="2026-04-05"))
        resp = self.client.get(
            reverse("gastos:gasto-list"), {"mes_referencia": "2026-03-01"}
        )
        self.assertEqual(resp.data["count"], 1)


class GastoCompartilhadoTest(APITestCase):
    def setUp(self):
        self.ana = criar_usuario("ana@x.com", "Ana")
        self.bia = criar_usuario("bia@x.com", "Bia")
        self.client.force_authenticate(self.ana)
        self.categoria = criar_categoria(self.ana)
        self.vinculo = Vinculo.objects.create(
            solicitante=self.ana,
            destinatario=self.bia,
            status=Vinculo.Status.ACEITO,
        )

    def _payload(self, **over):
        base = {
            "descricao": "Jantar",
            "valor": "100.00",
            "data": "2026-03-05",
            "categoria": self.categoria.id,
            "forma_pagamento": "pix",
            "compartilhado": True,
            "vinculo": self.vinculo.id,
            "valor_dono": "60.00",
            "valor_vinculado": "40.00",
        }
        base.update(over)
        return base

    def test_rateio_que_fecha_o_total_ok(self):
        resp = self.client.post(reverse("gastos:gasto-list"), self._payload())
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)

    def test_rateio_que_nao_fecha_invalido(self):
        resp = self.client.post(
            reverse("gastos:gasto-list"), self._payload(valor_vinculado="30.00")
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("valor_dono", resp.data)

    def test_compartilhado_sem_vinculo_invalido(self):
        resp = self.client.post(
            reverse("gastos:gasto-list"),
            self._payload(vinculo=None),
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("vinculo", resp.data)

    def test_vinculo_pendente_invalido(self):
        self.vinculo.status = Vinculo.Status.PENDENTE
        self.vinculo.save(update_fields=["status"])
        resp = self.client.post(reverse("gastos:gasto-list"), self._payload())
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("vinculo", resp.data)

    def test_nao_compartilhado_zera_rateio(self):
        resp = self.client.post(
            reverse("gastos:gasto-list"),
            self._payload(compartilhado=False),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertIsNone(resp.data["vinculo"])
        self.assertIsNone(resp.data["valor_dono"])
        self.assertIsNone(resp.data["valor_vinculado"])
