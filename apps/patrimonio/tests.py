from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.cartoes.models import Cartao
from apps.categorias.models import Categoria
from apps.dividas.models import Divida
from apps.gastos.models import Gasto
from apps.investimentos.models import Investimento
from apps.receitas.models import Receita

from .calculo import calcular_patrimonio
from .models import Bem, PatrimonioSnapshot

Usuario = get_user_model()
MES = date(2026, 6, 1)


def criar_usuario(email, nome="User"):
    return Usuario.objects.create_user(email=email, nome=nome, password="senha-forte-123")


def cenario_completo(usuario):
    """Monta ativos e passivos conhecidos para o mês de junho/2026."""
    categoria = Categoria.objects.create(usuario=usuario, nome="Mercado")
    # Ativos
    Receita.objects.create(
        usuario=usuario,
        descricao="Salário",
        valor=Decimal("5000.00"),
        data_prevista=date(2026, 6, 1),
        data_real=date(2026, 6, 5),
        tipo=Receita.Tipo.SALARIO,
    )
    Gasto.objects.create(
        usuario=usuario,
        descricao="Feira",
        valor=Decimal("200.00"),
        data=date(2026, 6, 10),
        categoria=categoria,
        forma_pagamento=Gasto.FormaPagamento.PIX,
    )
    Investimento.objects.create(
        usuario=usuario,
        tipo=Investimento.Tipo.RENDA_FIXA,
        valor_aportado=Decimal("1000.00"),
        data_aporte=date(2026, 6, 2),
    )
    Bem.objects.create(
        usuario=usuario,
        descricao="Carro",
        tipo=Bem.Tipo.VEICULO,
        valor_estimado=Decimal("30000.00"),
    )
    # Passivos
    cartao = Cartao.objects.create(
        usuario=usuario,
        nome="Nubank",
        limite_total=Decimal("5000.00"),
        dia_fechamento=10,
        dia_vencimento=17,
    )
    Gasto.objects.create(
        usuario=usuario,
        descricao="TV",
        valor=Decimal("800.00"),
        data=date(2026, 6, 5),  # antes do fechamento -> fatura de junho
        categoria=categoria,
        forma_pagamento=Gasto.FormaPagamento.CREDITO,
        cartao=cartao,
    )
    divida = Divida.objects.create(
        usuario=usuario,
        descricao="Empréstimo",
        tipo=Divida.Tipo.EMPRESTIMO,
        valor_total=Decimal("1200.00"),
        numero_parcelas=12,
        valor_parcela=Decimal("100.00"),
        data_primeira_parcela=date(2026, 6, 20),
    )
    divida.gerar_parcelas()
    return cartao


class CalculoPatrimonioTest(APITestCase):
    def setUp(self):
        self.ana = criar_usuario("ana@x.com", "Ana")

    def test_patrimonio_completo(self):
        cenario_completo(self.ana)
        dados = calcular_patrimonio(self.ana, MES)

        self.assertEqual(dados["ativos"]["saldo_disponivel"], Decimal("4800.00"))
        self.assertEqual(dados["ativos"]["total_investido"], Decimal("1000.00"))
        self.assertEqual(dados["ativos"]["total_bens"], Decimal("30000.00"))
        self.assertEqual(dados["total_ativos"], Decimal("35800.00"))

        self.assertEqual(dados["passivos"]["faturas_abertas"], Decimal("800.00"))
        self.assertEqual(dados["passivos"]["dividas_abertas"], Decimal("1200.00"))
        self.assertEqual(dados["total_passivos"], Decimal("2000.00"))

        self.assertEqual(dados["patrimonio_liquido"], Decimal("33800.00"))

    def test_patrimonio_zerado(self):
        dados = calcular_patrimonio(self.ana, MES)
        self.assertEqual(dados["patrimonio_liquido"], Decimal("0.00"))

    def test_parcela_de_cartao_nao_duplica_passivo(self):
        cartao = Cartao.objects.create(
            usuario=self.ana,
            nome="Itaú",
            limite_total=Decimal("5000.00"),
            dia_fechamento=10,
            dia_vencimento=17,
        )
        divida = Divida.objects.create(
            usuario=self.ana,
            descricao="Geladeira",
            tipo=Divida.Tipo.PARCELAMENTO_CARTAO,
            valor_total=Decimal("1000.00"),
            numero_parcelas=10,
            valor_parcela=Decimal("100.00"),
            data_primeira_parcela=date(2026, 6, 20),
            cartao=cartao,
        )
        divida.gerar_parcelas()
        dados = calcular_patrimonio(self.ana, MES)
        # Parcelas de cartão entram via fatura, não como dívida solta.
        self.assertEqual(dados["passivos"]["dividas_abertas"], Decimal("0.00"))


class BemAPITest(APITestCase):
    def setUp(self):
        self.ana = criar_usuario("ana@x.com", "Ana")
        self.bia = criar_usuario("bia@x.com", "Bia")
        self.client.force_authenticate(self.ana)

    def test_criar_bem(self):
        resp = self.client.post(
            reverse("patrimonio:bem-list"),
            {"descricao": "Apto", "tipo": Bem.Tipo.IMOVEL, "valor_estimado": "250000.00"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Bem.objects.get().usuario, self.ana)

    def test_lista_so_do_dono(self):
        Bem.objects.create(usuario=self.ana, descricao="A", tipo=Bem.Tipo.OUTRO, valor_estimado=Decimal("1.00"))
        Bem.objects.create(usuario=self.bia, descricao="B", tipo=Bem.Tipo.OUTRO, valor_estimado=Decimal("1.00"))
        resp = self.client.get(reverse("patrimonio:bem-list"))
        self.assertEqual(len(resp.data["results"]), 1)


class PatrimonioEndpointTest(APITestCase):
    def setUp(self):
        self.ana = criar_usuario("ana@x.com", "Ana")
        self.client.force_authenticate(self.ana)

    def test_atual(self):
        cenario_completo(self.ana)
        resp = self.client.get(
            reverse("patrimonio:patrimonio-snapshot-atual"), {"mes": "2026-06-01"}
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(Decimal(resp.data["patrimonio_liquido"]), Decimal("33800.00"))

    def test_historico_lista_snapshots(self):
        PatrimonioSnapshot.objects.create(
            usuario=self.ana,
            mes_referencia=MES,
            total_ativos=Decimal("100.00"),
            total_passivos=Decimal("40.00"),
            patrimonio_liquido=Decimal("60.00"),
        )
        resp = self.client.get(reverse("patrimonio:patrimonio-snapshot-list"))
        self.assertEqual(len(resp.data["results"]), 1)


class SnapshotJobTest(APITestCase):
    def setUp(self):
        self.ana = criar_usuario("ana@x.com", "Ana")

    def test_job_persiste_snapshot(self):
        cenario_completo(self.ana)
        call_command("gerar_snapshot_patrimonio", "--mes", "2026-06-01")
        snap = PatrimonioSnapshot.objects.get(usuario=self.ana, mes_referencia=MES)
        self.assertEqual(snap.patrimonio_liquido, Decimal("33800.00"))

    def test_job_idempotente(self):
        cenario_completo(self.ana)
        call_command("gerar_snapshot_patrimonio", "--mes", "2026-06-01")
        call_command("gerar_snapshot_patrimonio", "--mes", "2026-06-01")
        self.assertEqual(
            PatrimonioSnapshot.objects.filter(usuario=self.ana, mes_referencia=MES).count(),
            1,
        )
