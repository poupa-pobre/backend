from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import (
    CATEGORIAS_PREDEFINIDAS,
    MAX_CATEGORIAS_CUSTOMIZADAS,
    Categoria,
    Subcategoria,
    Tag,
)

Usuario = get_user_model()


def criar_usuario(email, nome="User"):
    return Usuario.objects.create_user(email=email, nome=nome, password="senha-forte-123")


class SeedPredefinidasTest(APITestCase):
    def test_novo_usuario_recebe_as_12(self):
        ana = criar_usuario("ana@x.com")
        qs = Categoria.objects.filter(usuario=ana, predefinida=True)
        self.assertEqual(qs.count(), 12)
        self.assertEqual(
            set(qs.values_list("nome", flat=True)), set(CATEGORIAS_PREDEFINIDAS)
        )

    def test_predefinidas_sao_por_usuario(self):
        criar_usuario("ana@x.com")
        criar_usuario("bia@x.com")
        self.assertEqual(Categoria.objects.filter(predefinida=True).count(), 24)


class CategoriaEndpointsTest(APITestCase):
    def setUp(self):
        self.ana = criar_usuario("ana@x.com", "Ana")
        self.client.force_authenticate(self.ana)

    def test_lista_so_minhas_e_ativas(self):
        bia = criar_usuario("bia@x.com", "Bia")  # tem as dela
        resp = self.client.get(reverse("categorias:categoria-list"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # só as 12 da Ana
        self.assertEqual(resp.data["count"], 12)
        donos = Categoria.objects.filter(
            id__in=[c["id"] for c in resp.data["results"]]
        ).values_list("usuario_id", flat=True)
        self.assertTrue(all(d == self.ana.id for d in donos))
        self.assertNotEqual(bia.id, self.ana.id)

    def test_cria_customizada(self):
        resp = self.client.post(
            reverse("categorias:categoria-list"),
            {"nome": "Investimentos", "cor": "#00FF00", "icone": "trending-up"},
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertFalse(resp.data["predefinida"])
        self.assertTrue(resp.data["ativa"])

    def test_limite_de_10_customizadas(self):
        for i in range(MAX_CATEGORIAS_CUSTOMIZADAS):
            Categoria.objects.create(usuario=self.ana, nome=f"C{i}", predefinida=False)
        resp = self.client.post(
            reverse("categorias:categoria-list"), {"nome": "Extra"}
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_predefinida_pode_ser_renomeada(self):
        cat = Categoria.objects.filter(usuario=self.ana, predefinida=True).first()
        resp = self.client.patch(
            reverse("categorias:categoria-detail", args=[cat.id]),
            {"nome": "Casa"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        cat.refresh_from_db()
        self.assertEqual(cat.nome, "Casa")
        self.assertTrue(cat.predefinida)  # continua predefinida

    def test_nao_exclui_predefinida(self):
        cat = Categoria.objects.filter(usuario=self.ana, predefinida=True).first()
        resp = self.client.delete(reverse("categorias:categoria-detail", args=[cat.id]))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        cat.refresh_from_db()
        self.assertTrue(cat.ativa)

    def test_exclui_customizada_e_soft_delete(self):
        cat = Categoria.objects.create(usuario=self.ana, nome="Extra", predefinida=False)
        resp = self.client.delete(reverse("categorias:categoria-detail", args=[cat.id]))
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        cat.refresh_from_db()
        self.assertFalse(cat.ativa)  # ainda existe, só inativa
        # some da listagem padrão
        lista = self.client.get(reverse("categorias:categoria-list"))
        self.assertNotIn(cat.id, [c["id"] for c in lista.data["results"]])

    def test_restaurar_customizada(self):
        cat = Categoria.objects.create(
            usuario=self.ana, nome="Extra", predefinida=False, ativa=False
        )
        resp = self.client.post(
            reverse("categorias:categoria-restaurar", args=[cat.id])
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        cat.refresh_from_db()
        self.assertTrue(cat.ativa)

    def test_incluir_inativas_na_listagem(self):
        Categoria.objects.create(
            usuario=self.ana, nome="Extra", predefinida=False, ativa=False
        )
        resp = self.client.get(
            reverse("categorias:categoria-list"), {"incluir_inativas": "true"}
        )
        self.assertEqual(resp.data["count"], 13)

    def test_nao_acessa_categoria_de_terceiro(self):
        bia = criar_usuario("bia@x.com", "Bia")
        alheia = Categoria.objects.filter(usuario=bia).first()
        resp = self.client.get(
            reverse("categorias:categoria-detail", args=[alheia.id])
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class SubcategoriaTest(APITestCase):
    def setUp(self):
        self.ana = criar_usuario("ana@x.com", "Ana")
        self.client.force_authenticate(self.ana)
        self.categoria = Categoria.objects.filter(usuario=self.ana).first()

    def test_cria_subcategoria_na_propria_categoria(self):
        resp = self.client.post(
            reverse("categorias:subcategoria-list"),
            {"categoria": self.categoria.id, "nome": "Mercado"},
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_nao_cria_em_categoria_de_terceiro(self):
        bia = criar_usuario("bia@x.com", "Bia")
        alheia = Categoria.objects.filter(usuario=bia).first()
        resp = self.client.post(
            reverse("categorias:subcategoria-list"),
            {"categoria": alheia.id, "nome": "X"},
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_filtra_por_categoria(self):
        outra = Categoria.objects.filter(usuario=self.ana)[1]
        Subcategoria.objects.create(categoria=self.categoria, nome="A")
        Subcategoria.objects.create(categoria=outra, nome="B")
        resp = self.client.get(
            reverse("categorias:subcategoria-list"), {"categoria": self.categoria.id}
        )
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["results"][0]["nome"], "A")


class TagTest(APITestCase):
    def setUp(self):
        self.ana = criar_usuario("ana@x.com", "Ana")
        self.client.force_authenticate(self.ana)

    def test_cria_e_lista_tag(self):
        self.client.post(reverse("categorias:tag-list"), {"nome": "essencial"})
        resp = self.client.get(reverse("categorias:tag-list"))
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["results"][0]["nome"], "essencial")

    def test_tag_escopo_por_usuario(self):
        bia = criar_usuario("bia@x.com", "Bia")
        Tag.objects.create(usuario=bia, nome="dela")
        resp = self.client.get(reverse("categorias:tag-list"))
        self.assertEqual(resp.data["count"], 0)


class ReatribuicaoAoExcluirTest(APITestCase):
    """RF-021: excluir categoria com lançamentos exige reatribuição."""

    def setUp(self):
        from datetime import date
        from decimal import Decimal

        from apps.gastos.models import Gasto

        self.Gasto = Gasto
        self.ana = criar_usuario("ana@x.com", "Ana")
        self.client.force_authenticate(self.ana)
        self.origem = Categoria.objects.create(usuario=self.ana, nome="Origem")
        self.destino = Categoria.objects.create(usuario=self.ana, nome="Destino")
        self.gasto = Gasto.objects.create(
            usuario=self.ana,
            descricao="x",
            valor=Decimal("10.00"),
            data=date(2026, 3, 1),
            categoria=self.origem,
            forma_pagamento=Gasto.FormaPagamento.PIX,
        )

    def _del(self, categoria, **data):
        return self.client.delete(
            reverse("categorias:categoria-detail", args=[categoria.id]), data
        )

    def test_sem_destino_pede_reatribuicao(self):
        resp = self._del(self.origem)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.origem.refresh_from_db()
        self.assertTrue(self.origem.ativa)  # não excluiu

    def test_destino_invalido_recusa(self):
        bia = criar_usuario("bia@x.com", "Bia")
        alheia = Categoria.objects.create(usuario=bia, nome="Alheia")
        resp = self._del(self.origem, reatribuir_para=alheia.id)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reatribui_e_exclui(self):
        resp = self._del(self.origem, reatribuir_para=self.destino.id)
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.origem.refresh_from_db()
        self.gasto.refresh_from_db()
        self.assertFalse(self.origem.ativa)
        self.assertEqual(self.gasto.categoria_id, self.destino.id)

    def test_sem_lancamentos_exclui_direto(self):
        vazia = Categoria.objects.create(usuario=self.ana, nome="Vazia")
        resp = self._del(vazia)
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
