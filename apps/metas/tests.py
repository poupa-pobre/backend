from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import AporteMeta, Meta

Usuario = get_user_model()


def criar_usuario(email, nome="User"):
    return Usuario.objects.create_user(email=email, nome=nome, password="senha-forte-123")


def criar_meta(usuario, **kwargs):
    defaults = {
        "nome": "Reserva de emergência",
        "valor_alvo": Decimal("12000.00"),
    }
    defaults.update(kwargs)
    return Meta.objects.create(usuario=usuario, **defaults)


class MetaProgressoTest(APITestCase):
    def setUp(self):
        self.ana = criar_usuario("ana@x.com", "Ana")

    def test_percentual_e_restante(self):
        meta = criar_meta(self.ana, valor_atual=Decimal("3000.00"))
        p = meta.progresso()
        self.assertEqual(p["percentual_concluido"], Decimal("25.00"))
        self.assertEqual(p["valor_restante"], Decimal("9000.00"))
        self.assertFalse(p["concluida"])

    def test_meta_concluida(self):
        meta = criar_meta(self.ana, valor_atual=Decimal("12000.00"))
        p = meta.progresso()
        self.assertTrue(p["concluida"])
        self.assertEqual(p["valor_restante"], Decimal("0.00"))

    def test_no_ritmo_com_contribuicao_planejada(self):
        meta = criar_meta(
            self.ana,
            valor_atual=Decimal("0.00"),
            data_alvo=date(2026, 12, 1),
            contribuicao_mensal_planejada=Decimal("2000.00"),
        )
        # De junho a dezembro/2026 = 6 meses; necessário 12000/6 = 2000.
        p = meta.progresso(hoje=date(2026, 6, 1))
        self.assertEqual(p["meses_restantes"], 6)
        self.assertEqual(p["aporte_mensal_necessario"], Decimal("2000.00"))
        self.assertTrue(p["no_ritmo"])

    def test_fora_do_ritmo(self):
        meta = criar_meta(
            self.ana,
            data_alvo=date(2026, 12, 1),
            contribuicao_mensal_planejada=Decimal("500.00"),
        )
        p = meta.progresso(hoje=date(2026, 6, 1))
        self.assertFalse(p["no_ritmo"])

    def test_prazo_esgotado(self):
        meta = criar_meta(self.ana, data_alvo=date(2026, 5, 1))
        p = meta.progresso(hoje=date(2026, 6, 1))
        self.assertEqual(p["meses_restantes"], 0)
        self.assertFalse(p["no_ritmo"])


class MetaAPITest(APITestCase):
    def setUp(self):
        self.ana = criar_usuario("ana@x.com", "Ana")
        self.bia = criar_usuario("bia@x.com", "Bia")
        self.client.force_authenticate(self.ana)

    def test_criar_meta(self):
        resp = self.client.post(
            reverse("metas:meta-list"),
            {"nome": "Viagem", "valor_alvo": "5000.00"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Meta.objects.get().usuario, self.ana)

    def test_lista_so_do_dono(self):
        criar_meta(self.ana)
        criar_meta(self.bia)
        resp = self.client.get(reverse("metas:meta-list"))
        self.assertEqual(len(resp.data["results"]), 1)

    def test_progresso_no_payload(self):
        criar_meta(self.ana, valor_atual=Decimal("6000.00"))
        resp = self.client.get(reverse("metas:meta-list"))
        self.assertEqual(resp.data["results"][0]["percentual_concluido"], Decimal("50.00"))


class AporteMetaAPITest(APITestCase):
    def setUp(self):
        self.ana = criar_usuario("ana@x.com", "Ana")
        self.bia = criar_usuario("bia@x.com", "Bia")
        self.meta = criar_meta(self.ana)
        self.client.force_authenticate(self.ana)

    def test_aporte_incrementa_valor_atual(self):
        resp = self.client.post(
            reverse("metas:aporte-meta-list"),
            {"meta": self.meta.id, "valor": "500.00", "data": "2026-06-05"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.meta.refresh_from_db()
        self.assertEqual(self.meta.valor_atual, Decimal("500.00"))

    def test_excluir_aporte_decrementa(self):
        self.client.post(
            reverse("metas:aporte-meta-list"),
            {"meta": self.meta.id, "valor": "500.00", "data": "2026-06-05"},
            format="json",
        )
        aporte = AporteMeta.objects.get()
        self.client.delete(reverse("metas:aporte-meta-detail", args=[aporte.id]))
        self.meta.refresh_from_db()
        self.assertEqual(self.meta.valor_atual, Decimal("0.00"))

    def test_nao_aporta_em_meta_de_outro(self):
        meta_bia = criar_meta(self.bia)
        resp = self.client.post(
            reverse("metas:aporte-meta-list"),
            {"meta": meta_bia.id, "valor": "100.00", "data": "2026-06-05"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_valor_negativo_rejeitado(self):
        resp = self.client.post(
            reverse("metas:aporte-meta-list"),
            {"meta": self.meta.id, "valor": "-10.00", "data": "2026-06-05"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
