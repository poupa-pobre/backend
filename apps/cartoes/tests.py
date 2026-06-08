from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Cartao, Fatura, competencia

Usuario = get_user_model()


def criar_usuario(email, nome="User"):
    return Usuario.objects.create_user(email=email, nome=nome, password="senha-forte-123")


def criar_cartao(usuario, **kwargs):
    defaults = {
        "nome": "Nubank",
        "limite_total": Decimal("5000.00"),
        "dia_fechamento": 10,
        "dia_vencimento": 17,
    }
    defaults.update(kwargs)
    return Cartao.objects.create(usuario=usuario, **defaults)


class CompetenciaTest(APITestCase):
    def test_antes_do_fechamento_mes_atual(self):
        self.assertEqual(competencia(date(2026, 3, 5), 10), date(2026, 3, 1))

    def test_no_dia_do_fechamento_mes_atual(self):
        self.assertEqual(competencia(date(2026, 3, 10), 10), date(2026, 3, 1))

    def test_apos_o_fechamento_mes_seguinte(self):
        self.assertEqual(competencia(date(2026, 3, 15), 10), date(2026, 4, 1))

    def test_virada_de_ano(self):
        self.assertEqual(competencia(date(2026, 12, 20), 10), date(2027, 1, 1))

    def test_fechamento_31_em_fevereiro_clampa(self):
        # fechamento 31, fev tem 28 -> qualquer dia <= 28 cai no mês atual
        self.assertEqual(competencia(date(2026, 2, 28), 31), date(2026, 2, 1))

    def test_metodo_do_cartao(self):
        cartao = criar_cartao(criar_usuario("a@x.com"), dia_fechamento=10)
        self.assertEqual(cartao.competencia_de(date(2026, 3, 15)), date(2026, 4, 1))


class FaturaModelTest(APITestCase):
    def setUp(self):
        self.cartao = criar_cartao(criar_usuario("a@x.com"))

    def test_unica_por_mes(self):
        Fatura.objects.create(cartao=self.cartao, mes_referencia=date(2026, 3, 1))
        with self.assertRaises(IntegrityError), transaction.atomic():
            Fatura.objects.create(cartao=self.cartao, mes_referencia=date(2026, 3, 1))

    def test_fatura_do_mes_get_or_create(self):
        f1 = self.cartao.fatura_do_mes(date(2026, 3, 15))  # após fechamento -> abril
        self.assertEqual(f1.mes_referencia, date(2026, 4, 1))
        f2 = self.cartao.fatura_do_mes(date(2026, 4, 2))  # mesma competência
        self.assertEqual(f1.id, f2.id)
        self.assertEqual(self.cartao.faturas.count(), 1)


class CartaoEndpointsTest(APITestCase):
    def setUp(self):
        self.ana = criar_usuario("ana@x.com", "Ana")
        self.client.force_authenticate(self.ana)

    def test_cria_cartao(self):
        resp = self.client.post(
            reverse("cartoes:cartao-list"),
            {
                "nome": "Inter",
                "limite_total": "3000.00",
                "dia_fechamento": 5,
                "dia_vencimento": 12,
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["status"], "ativo")

    def test_dia_fora_do_intervalo_invalido(self):
        resp = self.client.post(
            reverse("cartoes:cartao-list"),
            {
                "nome": "X",
                "limite_total": "100.00",
                "dia_fechamento": 32,
                "dia_vencimento": 10,
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_soft_delete_inativa(self):
        cartao = criar_cartao(self.ana)
        resp = self.client.delete(reverse("cartoes:cartao-detail", args=[cartao.id]))
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        cartao.refresh_from_db()
        self.assertEqual(cartao.status, Cartao.Status.INATIVO)
        # some da listagem padrão
        lista = self.client.get(reverse("cartoes:cartao-list"))
        self.assertEqual(lista.data["count"], 0)

    def test_reativar(self):
        cartao = criar_cartao(self.ana, status=Cartao.Status.INATIVO)
        resp = self.client.post(reverse("cartoes:cartao-reativar", args=[cartao.id]))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        cartao.refresh_from_db()
        self.assertEqual(cartao.status, Cartao.Status.ATIVO)

    def test_incluir_inativos(self):
        criar_cartao(self.ana, status=Cartao.Status.INATIVO)
        resp = self.client.get(
            reverse("cartoes:cartao-list"), {"incluir_inativos": "true"}
        )
        self.assertEqual(resp.data["count"], 1)

    def test_escopo_por_usuario(self):
        bia = criar_usuario("bia@x.com", "Bia")
        criar_cartao(bia)
        resp = self.client.get(reverse("cartoes:cartao-list"))
        self.assertEqual(resp.data["count"], 0)

    def test_nao_acessa_cartao_de_terceiro(self):
        bia = criar_usuario("bia@x.com", "Bia")
        alheio = criar_cartao(bia)
        resp = self.client.get(reverse("cartoes:cartao-detail", args=[alheio.id]))
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class FaturaEndpointsTest(APITestCase):
    def setUp(self):
        self.ana = criar_usuario("ana@x.com", "Ana")
        self.client.force_authenticate(self.ana)
        self.cartao = criar_cartao(self.ana)
        self.fatura = Fatura.objects.create(
            cartao=self.cartao, mes_referencia=date(2026, 3, 1), total=Decimal("250.00")
        )

    def test_lista_so_faturas_dos_meus_cartoes(self):
        bia = criar_usuario("bia@x.com", "Bia")
        Fatura.objects.create(cartao=criar_cartao(bia), mes_referencia=date(2026, 3, 1))
        resp = self.client.get(reverse("cartoes:fatura-list"))
        self.assertEqual(resp.data["count"], 1)

    def test_filtra_por_cartao_e_status(self):
        resp = self.client.get(
            reverse("cartoes:fatura-list"),
            {"cartao": self.cartao.id, "status": "aberta"},
        )
        self.assertEqual(resp.data["count"], 1)

    def test_pagar_usa_total_por_padrao(self):
        # O total é derivado (recomposto no pagamento): um gasto de 250 no crédito.
        from apps.categorias.models import Categoria
        from apps.gastos.models import Gasto

        categoria = Categoria.objects.create(usuario=self.ana, nome="Casa")
        Gasto.objects.create(
            usuario=self.ana,
            descricao="Compra",
            valor=Decimal("250.00"),
            data=date(2026, 3, 5),
            categoria=categoria,
            forma_pagamento=Gasto.FormaPagamento.CREDITO,
            cartao=self.cartao,
        )
        resp = self.client.post(
            reverse("cartoes:fatura-pagar", args=[self.fatura.id]),
            {"data_pagamento": "2026-03-17"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.fatura.refresh_from_db()
        self.assertEqual(self.fatura.status, Fatura.Status.PAGA)
        self.assertEqual(self.fatura.valor_pago, Decimal("250.00"))
        self.assertEqual(str(self.fatura.data_pagamento), "2026-03-17")

    def test_pagar_com_valor_parcial(self):
        resp = self.client.post(
            reverse("cartoes:fatura-pagar", args=[self.fatura.id]),
            {"data_pagamento": "2026-03-17", "valor_pago": "100.00"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.fatura.refresh_from_db()
        self.assertEqual(self.fatura.valor_pago, Decimal("100.00"))

    def test_nao_paga_duas_vezes(self):
        self.fatura.status = Fatura.Status.PAGA
        self.fatura.save(update_fields=["status"])
        resp = self.client.post(
            reverse("cartoes:fatura-pagar", args=[self.fatura.id]),
            {"data_pagamento": "2026-03-17"},
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class ComposicaoFaturaTest(APITestCase):
    """RF-041..043: agregação de fixos + parcelas + variáveis na fatura."""

    def setUp(self):
        from apps.categorias.models import Categoria

        self.ana = criar_usuario("ana@x.com", "Ana")
        self.client.force_authenticate(self.ana)
        self.cartao = criar_cartao(self.ana, dia_fechamento=10)
        self.categoria = Categoria.objects.create(usuario=self.ana, nome="Casa")
        self.mes = date(2026, 5, 1)

    def _gasto_credito(self, valor):
        from apps.gastos.models import Gasto

        Gasto.objects.create(
            usuario=self.ana,
            descricao="Compra",
            valor=Decimal(valor),
            data=date(2026, 5, 5),  # antes do fechamento → competência maio
            categoria=self.categoria,
            forma_pagamento=Gasto.FormaPagamento.CREDITO,
            cartao=self.cartao,
        )

    def _fixo_no_cartao(self, valor):
        from apps.gastos_fixos.models import GastoFixo

        fixo = GastoFixo.objects.create(
            usuario=self.ana,
            descricao="Streaming",
            tipo=GastoFixo.Tipo.FIXO,
            valor=Decimal(valor),
            dia_vencimento=8,
            categoria=self.categoria,
            forma_pagamento=GastoFixo.FormaPagamento.CARTAO,
            cartao=self.cartao,
        )
        fixo.gerar_mensal(self.mes)

    def _parcela_no_cartao(self, valor_parcela):
        from apps.dividas.models import Divida

        divida = Divida.objects.create(
            usuario=self.ana,
            descricao="TV 3x",
            tipo=Divida.Tipo.PARCELAMENTO_CARTAO,
            valor_total=Decimal(valor_parcela) * 3,
            numero_parcelas=3,
            valor_parcela=Decimal(valor_parcela),
            data_primeira_parcela=date(2026, 5, 20),
            cartao=self.cartao,
        )
        divida.gerar_parcelas()

    def _fatura_maio(self):
        return self.cartao.fatura_do_mes(date(2026, 5, 5))

    def test_total_soma_os_tres_grupos(self):
        self._gasto_credito("100.00")
        self._fixo_no_cartao("50.00")
        self._parcela_no_cartao("30.00")  # 1ª parcela cai em maio
        comp = self._fatura_maio().composicao()
        self.assertEqual(comp["subtotais"]["variaveis"], Decimal("100.00"))
        self.assertEqual(comp["subtotais"]["fixos"], Decimal("50.00"))
        self.assertEqual(comp["subtotais"]["parcelas"], Decimal("30.00"))
        self.assertEqual(comp["total"], Decimal("180.00"))

    def test_limite_usado_e_disponivel(self):
        self._gasto_credito("1000.00")
        comp = self._fatura_maio().composicao()
        self.assertEqual(comp["limite_total"], Decimal("5000.00"))
        self.assertEqual(comp["limite_usado"], Decimal("1000.00"))
        self.assertEqual(comp["limite_disponivel"], Decimal("4000.00"))

    def test_recompor_persiste_total(self):
        self._gasto_credito("100.00")
        fatura = self._fatura_maio()
        fatura.recompor()
        fatura.refresh_from_db()
        self.assertEqual(fatura.total, Decimal("100.00"))

    def test_endpoint_composicao(self):
        self._gasto_credito("100.00")
        self._fixo_no_cartao("50.00")
        fatura = self._fatura_maio()
        resp = self.client.get(
            reverse("cartoes:fatura-composicao", args=[fatura.id])
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["total"], Decimal("150.00"))
        self.assertEqual(len(resp.data["fixos"]), 1)
        self.assertTrue("checked" in resp.data["fixos"][0])

    def test_pagar_usa_total_composto_como_padrao(self):
        self._gasto_credito("250.00")
        fatura = self._fatura_maio()
        resp = self.client.post(
            reverse("cartoes:fatura-pagar", args=[fatura.id]),
            {"data_pagamento": "2026-05-17"},  # sem valor_pago → usa o total
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        fatura.refresh_from_db()
        self.assertEqual(fatura.valor_pago, Decimal("250.00"))
