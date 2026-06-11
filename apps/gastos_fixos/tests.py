from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.cartoes.models import Cartao
from apps.categorias.models import Categoria
from apps.vinculos.models import Vinculo

from .models import GastoFixo, GastoFixoMensal

Usuario = get_user_model()


def criar_usuario(email, nome="User"):
    return Usuario.objects.create_user(email=email, nome=nome, password="senha-forte-123")


def criar_fixo(usuario, categoria, **kwargs):
    defaults = {
        "descricao": "Aluguel",
        "tipo": GastoFixo.Tipo.FIXO,
        "valor": Decimal("1500.00"),
        "dia_vencimento": 10,
        "categoria": categoria,
    }
    defaults.update(kwargs)
    return GastoFixo.objects.create(usuario=usuario, **defaults)


class GastoFixoModelTest(APITestCase):
    def setUp(self):
        self.ana = criar_usuario("ana@x.com", "Ana")
        self.categoria = Categoria.objects.create(usuario=self.ana, nome="Casa")

    def test_gerar_mensal_idempotente(self):
        fixo = criar_fixo(self.ana, self.categoria)
        fixo.gerar_mensal(date(2026, 5, 1))
        fixo.gerar_mensal(date(2026, 5, 1))
        self.assertEqual(fixo.mensais.count(), 1)

    def test_valor_efetivo_tipo_a_usa_template(self):
        fixo = criar_fixo(self.ana, self.categoria, valor=Decimal("1500.00"))
        mensal = fixo.gerar_mensal(date(2026, 5, 1))
        self.assertEqual(mensal.valor_efetivo, Decimal("1500.00"))

    def test_valor_efetivo_tipo_b_usa_valor_real(self):
        fixo = criar_fixo(
            self.ana,
            self.categoria,
            tipo=GastoFixo.Tipo.ESTIMADO,
            valor=None,
            valor_estimado=Decimal("200.00"),
        )
        mensal = fixo.gerar_mensal(date(2026, 5, 1))
        self.assertEqual(mensal.valor_efetivo, Decimal("200.00"))  # cai no estimado
        mensal.valor_real = Decimal("237.45")
        self.assertEqual(mensal.valor_efetivo, Decimal("237.45"))

    def test_data_vencimento_clampa_no_ultimo_dia(self):
        fixo = criar_fixo(self.ana, self.categoria, dia_vencimento=31)
        mensal = fixo.gerar_mensal(date(2026, 2, 1))  # fevereiro
        self.assertEqual(mensal.data_vencimento, date(2026, 2, 28))

    def test_esta_atrasado(self):
        fixo = criar_fixo(self.ana, self.categoria, dia_vencimento=10)
        mensal = fixo.gerar_mensal(date(2026, 5, 1))
        self.assertFalse(mensal.esta_atrasado(date(2026, 5, 9)))
        self.assertTrue(mensal.esta_atrasado(date(2026, 5, 11)))
        mensal.status = GastoFixoMensal.Status.PAGO
        self.assertFalse(mensal.esta_atrasado(date(2026, 5, 11)))


class GerarGastosFixosCommandTest(APITestCase):
    def setUp(self):
        self.ana = criar_usuario("ana@x.com", "Ana")
        self.categoria = Categoria.objects.create(usuario=self.ana, nome="Casa")

    def test_job_pre_cria_so_ativos(self):
        criar_fixo(self.ana, self.categoria, descricao="Aluguel")
        criar_fixo(self.ana, self.categoria, descricao="Antigo", ativo=False)
        call_command("gerar_gastos_fixos", "--mes", "2026-05-01")
        self.assertEqual(
            GastoFixoMensal.objects.filter(mes_referencia=date(2026, 5, 1)).count(), 1
        )

    def test_job_idempotente(self):
        criar_fixo(self.ana, self.categoria)
        call_command("gerar_gastos_fixos", "--mes", "2026-05-01")
        call_command("gerar_gastos_fixos", "--mes", "2026-05-01")
        self.assertEqual(
            GastoFixoMensal.objects.filter(mes_referencia=date(2026, 5, 1)).count(), 1
        )

    def test_marcar_atrasos(self):
        fixo = criar_fixo(self.ana, self.categoria, dia_vencimento=10)
        # mês bem antigo garante vencimento no passado
        fixo.gerar_mensal(date(2020, 1, 1))
        call_command("marcar_atrasos")
        mensal = GastoFixoMensal.objects.get(mes_referencia=date(2020, 1, 1))
        self.assertEqual(mensal.status, GastoFixoMensal.Status.ATRASADO)


class GastoFixoEndpointsTest(APITestCase):
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

    def _payload(self, **over):
        base = {
            "descricao": "Aluguel",
            "tipo": "A",
            "valor": "1500.00",
            "dia_vencimento": 10,
            "categoria": self.categoria.id,
        }
        base.update(over)
        return base

    def test_cria_tipo_a(self):
        resp = self.client.post(reverse("gastos_fixos:gastofixo-list"), self._payload())
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)

    def test_tipo_a_exige_valor(self):
        resp = self.client.post(
            reverse("gastos_fixos:gastofixo-list"),
            self._payload(valor=None),
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("valor", resp.data)

    def test_forma_cartao_exige_cartao(self):
        resp = self.client.post(
            reverse("gastos_fixos:gastofixo-list"),
            self._payload(forma_pagamento="cartao"),
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("cartao", resp.data)

    def test_cartao_so_na_forma_cartao(self):
        resp = self.client.post(
            reverse("gastos_fixos:gastofixo-list"),
            self._payload(forma_pagamento="pix", cartao=self.cartao.id),
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("cartao", resp.data)

    def test_forma_cartao_com_cartao_ok(self):
        resp = self.client.post(
            reverse("gastos_fixos:gastofixo-list"),
            self._payload(forma_pagamento="cartao", cartao=self.cartao.id),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)

    def test_soft_delete_oculta_da_listagem(self):
        resp = self.client.post(reverse("gastos_fixos:gastofixo-list"), self._payload())
        fixo_id = resp.data["id"]
        self.client.delete(
            reverse("gastos_fixos:gastofixo-detail", args=[fixo_id])
        )
        lista = self.client.get(reverse("gastos_fixos:gastofixo-list"))
        self.assertEqual(lista.data["count"], 0)
        self.assertTrue(GastoFixo.objects.filter(id=fixo_id, ativo=False).exists())

    def test_escopo_por_usuario(self):
        bia = criar_usuario("bia@x.com", "Bia")
        criar_fixo(bia, Categoria.objects.create(usuario=bia, nome="X"))
        resp = self.client.get(reverse("gastos_fixos:gastofixo-list"))
        self.assertEqual(resp.data["count"], 0)


class CheckPagamentoTest(APITestCase):
    def setUp(self):
        self.ana = criar_usuario("ana@x.com", "Ana")
        self.client.force_authenticate(self.ana)
        self.categoria = Categoria.objects.create(usuario=self.ana, nome="Casa")

    def _mensal(self, **fixo_kwargs):
        fixo = criar_fixo(self.ana, self.categoria, **fixo_kwargs)
        return fixo.gerar_mensal(date(2026, 5, 1))

    def test_check_tipo_a_marca_pago(self):
        mensal = self._mensal()
        resp = self.client.post(
            reverse("gastos_fixos:gastofixomensal-pagar", args=[mensal.id]),
            {"data_pagamento": "2026-05-08"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["status"], "pago")
        self.assertEqual(resp.data["data_pagamento"], "2026-05-08")
        mensal.refresh_from_db()
        self.assertIsNotNone(mensal.checked_at)

    def test_check_tipo_b_exige_valor_real(self):
        mensal = self._mensal(
            tipo=GastoFixo.Tipo.ESTIMADO, valor=None, valor_estimado=Decimal("200.00")
        )
        resp = self.client.post(
            reverse("gastos_fixos:gastofixomensal-pagar", args=[mensal.id])
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("valor_real", resp.data)

    def test_check_tipo_b_com_valor_real_ok(self):
        mensal = self._mensal(
            tipo=GastoFixo.Tipo.ESTIMADO, valor=None, valor_estimado=Decimal("200.00")
        )
        resp = self.client.post(
            reverse("gastos_fixos:gastofixomensal-pagar", args=[mensal.id]),
            {"valor_real": "237.45"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["status"], "pago")
        self.assertEqual(Decimal(resp.data["valor_real"]), Decimal("237.45"))

    def test_check_duplicado_falha(self):
        mensal = self._mensal()
        url = reverse("gastos_fixos:gastofixomensal-pagar", args=[mensal.id])
        self.client.post(url, {"data_pagamento": "2026-05-08"})
        resp = self.client.post(url, {"data_pagamento": "2026-05-08"})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_desmarcar_reverte_o_check(self):
        # Tipo B: paga com valor_real e depois desmarca (marcou errado).
        mensal = self._mensal(
            tipo=GastoFixo.Tipo.ESTIMADO, valor=None, valor_estimado=Decimal("200.00")
        )
        self.client.post(
            reverse("gastos_fixos:gastofixomensal-pagar", args=[mensal.id]),
            {"valor_real": "237.45"},
        )
        resp = self.client.post(
            reverse("gastos_fixos:gastofixomensal-desmarcar", args=[mensal.id])
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        # Fixo de maio/2026 (vencido hoje) → volta como atrasado, não pago.
        self.assertEqual(resp.data["status"], "atrasado")
        mensal.refresh_from_db()
        self.assertNotEqual(mensal.status, GastoFixoMensal.Status.PAGO)
        self.assertIsNone(mensal.valor_real)
        self.assertIsNone(mensal.data_pagamento)
        self.assertIsNone(mensal.checked_at)

    def test_desmarcar_so_quando_pago(self):
        mensal = self._mensal()  # nasce pendente
        resp = self.client.post(
            reverse("gastos_fixos:gastofixomensal-desmarcar", args=[mensal.id])
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class GastoFixoCompartilhadoTest(APITestCase):
    def setUp(self):
        self.ana = criar_usuario("ana@x.com", "Ana")
        self.bia = criar_usuario("bia@x.com", "Bia")
        self.client.force_authenticate(self.ana)
        self.categoria = Categoria.objects.create(usuario=self.ana, nome="Casa")
        self.vinculo = Vinculo.objects.create(
            solicitante=self.ana,
            destinatario=self.bia,
            status=Vinculo.Status.ACEITO,
        )

    def _payload(self, **over):
        base = {
            "descricao": "Aluguel",
            "tipo": "A",
            "valor": "1500.00",
            "dia_vencimento": 10,
            "categoria": self.categoria.id,
            "compartilhado": True,
            "vinculo": self.vinculo.id,
            "valor_dono": "900.00",
            "valor_vinculado": "600.00",
        }
        base.update(over)
        return base

    def test_rateio_ok(self):
        resp = self.client.post(reverse("gastos_fixos:gastofixo-list"), self._payload())
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)

    def test_rateio_que_nao_fecha_invalido(self):
        resp = self.client.post(
            reverse("gastos_fixos:gastofixo-list"),
            self._payload(valor_vinculado="500.00"),
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("valor_dono", resp.data)

    def test_nao_compartilhado_zera_rateio(self):
        resp = self.client.post(
            reverse("gastos_fixos:gastofixo-list"),
            self._payload(compartilhado=False),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertIsNone(resp.data["vinculo"])
        self.assertIsNone(resp.data["valor_dono"])
