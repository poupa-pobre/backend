from datetime import date
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.cartoes.models import Cartao, Fatura
from apps.categorias.models import Categoria, Subcategoria, Tag
from apps.vinculos.models import Vinculo

from .models import CompraDetalhada, Gasto, ItemCompra
from .parser import parsear_cupom

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

    def test_local_gps_opcional(self):
        """Lat/long/nome do local são gravados e devolvidos quando enviados."""
        resp = self.client.post(
            reverse("gastos:gasto-list"),
            self._payload(
                latitude="-5.810000",
                longitude="-35.210000",
                local_nome="Extra - Av. Salgado Filho",
            ),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(resp.data["latitude"], "-5.810000")
        self.assertEqual(resp.data["longitude"], "-35.210000")
        self.assertEqual(resp.data["local_nome"], "Extra - Av. Salgado Filho")

    def test_local_ausente_fica_nulo(self):
        resp = self.client.post(reverse("gastos:gasto-list"), self._payload())
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertIsNone(resp.data["latitude"])
        self.assertIsNone(resp.data["local_nome"])

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


class ParserCupomTest(APITestCase):
    """Parser do texto do OCR em itens (RF-024/025) — sem tocar no banco."""

    def test_formato_rico_qtd_x_unit(self):
        texto = (
            "001 7891234567890 ARROZ 5KG  1 UN x 22,90  22,90\n"
            "002 LEITE 1L  3 x 4,99  14,97\n"
            "VALOR TOTAL R$ 37,87"
        )
        r = parsear_cupom(texto_ocr=texto)
        self.assertEqual(len(r["itens"]), 2)
        arroz = r["itens"][0]
        self.assertEqual(arroz["codigo"], "7891234567890")  # pega o EAN, não o seq
        self.assertEqual(arroz["valor"], 22.90)
        self.assertEqual(arroz["unidade"], "UN")
        self.assertTrue(arroz["identificado"])
        self.assertEqual(r["total"], 37.87)
        self.assertTrue(r["total_confere"])

    def test_item_simples_vem_para_revisao(self):
        r = parsear_cupom(texto_ocr="PAO FRANCES  3,20")
        self.assertEqual(len(r["itens"]), 1)
        self.assertFalse(r["itens"][0]["identificado"])  # sem qtd/unit → revisar

    def test_formato_nfce_sem_x(self):
        # Layout real (NFC-e RN, Queiroz Atacadão): "seq EAN desc QTD+UN vl_unit vl_total",
        # sem o "x", com rodapé de pagamento e desconto PIX.
        texto = (
            "QUEIROZ ATACADAO LTDA\n"
            "04/06/26 15:04:20 LJ 00014 PDV 103\n"
            "001 7891152801798 BISC RECH ANDRI MOR 1UN 2,99 2,99\n"
            "002 7891091061710 SALG PIPPOS PCT 75G 1UN 3,99 3,99\n"
            "006 78938854 BALA HALLS 28G MELANCIA 1UN 1,69 1,69\n"
            "DESCONTO -6,02% R$ -0,24 3,75\n"
            "Valor a Pagar R$ 8,43\n"
            "CARTEIRA DIGITAL 8,43"
        )
        r = parsear_cupom(texto_ocr=texto, buscar_online=False)
        self.assertEqual(len(r["itens"]), 3)  # rodapé/desconto não vazam
        bisc = r["itens"][0]
        self.assertEqual(bisc["nome"], "BISC RECH ANDRI MOR")  # sem "1UN" no nome
        self.assertEqual(bisc["codigo"], "7891152801798")
        self.assertEqual(bisc["quantidade"], 1.0)
        self.assertEqual(bisc["unidade"], "UN")
        self.assertEqual(bisc["valor_unitario"], 2.99)
        self.assertEqual(bisc["valor"], 2.99)
        self.assertTrue(bisc["identificado"])
        self.assertEqual(r["data"], "2026-06-04")
        self.assertEqual(r["desconto"], 0.24)  # 8,67 itens − 8,43 pago
        self.assertTrue(r["total_confere"])
        nomes = [i["nome"] for i in r["itens"]]
        self.assertNotIn("Valor a Pagar R$", nomes)
        self.assertNotIn("CARTEIRA DIGITAL", nomes)

    def test_codigo_grudado_e_separadores(self):
        # Testa EAN grudado e separado por vírgula na descrição
        texto1 = (
            "001 7891152801842,BISCQITO CHOC 136G 1,000 UN x 3,79 3,79\n"
            "002 7891152801842BISCQITO RECH 1 UN X 3,20 3,20\n"
            "VALOR TOTAL R$ 6,99"
        )
        r = parsear_cupom(texto_ocr=texto1, buscar_online=False)
        self.assertEqual(len(r["itens"]), 2)
        
        bisc1 = r["itens"][0]
        self.assertEqual(bisc1["codigo"], "7891152801842")
        self.assertEqual(bisc1["nome"], "BISCQITO CHOC 136G")
        self.assertEqual(bisc1["quantidade"], 1.0)
        self.assertEqual(bisc1["unidade"], "UN")
        self.assertEqual(bisc1["valor_unitario"], 3.79)
        self.assertEqual(bisc1["valor"], 3.79)
        self.assertTrue(bisc1["identificado"])

        bisc2 = r["itens"][1]
        self.assertEqual(bisc2["codigo"], "7891152801842")
        self.assertEqual(bisc2["nome"], "BISCQITO RECH")
        self.assertEqual(bisc2["quantidade"], 1.0)
        self.assertEqual(bisc2["unidade"], "UN")
        self.assertEqual(bisc2["valor_unitario"], 3.20)
        self.assertEqual(bisc2["valor"], 3.20)
        self.assertTrue(bisc2["identificado"])

    def test_fallback_robusto_e_ruido(self):
        # Testa a extração heurística/fallback para linhas com ruído de OCR
        texto2 = (
            "BISC0ITO TCHOC 136G 1,000 UN 3,79\n"
            "VALOR TOTAL R$ 3,79"
        )
        r = parsear_cupom(texto_ocr=texto2, buscar_online=False)
        self.assertEqual(len(r["itens"]), 1)
        item = r["itens"][0]
        self.assertEqual(item["nome"], "BISC0ITO TCHOC 136G")
        self.assertEqual(item["quantidade"], 1.0)
        self.assertEqual(item["unidade"], "UN")
        self.assertEqual(item["valor_unitario"], 3.79)
        self.assertEqual(item["valor"], 3.79)
        self.assertTrue(item["identificado"])

    def test_sequencial_variacoes_e_ruidos(self):
        # 1. Testar prefixos alfanuméricos como D02, U03, Q04, O01
        # 2. Separadores alternativos de quantidade H, 8, - ou omitidos (ex: "1,000UN H 6,49", "0,678KG 8 12,99", "1,000UN 3,19 F")
        # 3. Normalização de 4 casas decimais no valor unitário
        # 4. Descarte de ruídos de rodapé comuns
        texto = (
            "MEDEIROSE MAIA LTDA\n"
            "O01 7898908222050 BOLACHA JUCURUTU 250G MANTEIG\n"
            "1.000UN H 6,49\n"
            "U02 7891152801842 BISCOITO RECH RICHESTER 125G\n"
            "1,000UN 3,1900 F\n"
            "D03 826 PAO BOMDIA FRANCES KG\n"
            "0,678KG 8 12,9900 F\n"
            "004 ACHOCOLATADO EM PO ACHOCOLATI\n"
            "1,000UN - 15,98\n"
            "QTDE. TOTAL DE ITENS 4\n"
            "VALOR TOTAL R$ 34,47\n"
            "Fone:(89) 3661-362 I.€. :1.216-7\n"
            "EngePDV 1.0.2\n"
            "WegePDV 1.0\n"
            "Troco R$ 11,03\n"
            "Terminal: CAIXA03"
        )
        r = parsear_cupom(texto_ocr=texto, buscar_online=False)
        self.assertEqual(len(r["itens"]), 4)
        
        # O01 -> bolacha
        bolacha = r["itens"][0]
        self.assertEqual(bolacha["nome"], "BOLACHA JUCURUTU 250G MANTEIG")
        self.assertEqual(bolacha["quantidade"], 1.0)
        self.assertEqual(bolacha["valor_unitario"], 6.49)
        self.assertEqual(bolacha["valor"], 6.49)
        self.assertTrue(bolacha["identificado"])

        # U02 -> biscoito
        biscoito = r["itens"][1]
        self.assertEqual(biscoito["nome"], "BISCOITO RECH RICHESTER 125G")
        self.assertEqual(biscoito["quantidade"], 1.0)
        self.assertEqual(biscoito["valor_unitario"], 3.19)
        self.assertEqual(biscoito["valor"], 3.19)
        self.assertTrue(biscoito["identificado"])

        # D03 -> pao
        pao = r["itens"][2]
        self.assertEqual(pao["nome"], "PAO BOMDIA FRANCES KG")
        self.assertEqual(pao["quantidade"], 0.678)
        self.assertEqual(pao["valor_unitario"], 12.99)
        self.assertEqual(pao["valor"], 8.81)
        self.assertTrue(pao["identificado"])

        # 004 -> achocolatado
        achoc = r["itens"][3]
        self.assertEqual(achoc["nome"], "ACHOCOLATADO EM PO ACHOCOLATI")
        self.assertEqual(achoc["quantidade"], 1.0)
        self.assertEqual(achoc["valor_unitario"], 15.98)
        self.assertEqual(achoc["valor"], 15.98)
        self.assertTrue(achoc["identificado"])

        # Verificação do total e se o rodapé foi limpo
        self.assertEqual(r["total"], 34.47)
        self.assertTrue(r["total_confere"])
        
        nomes = [i["nome"] for i in r["itens"]]
        for nome in nomes:
            self.assertNotIn("Fone", nome)
            self.assertNotIn("EngePDV", nome)
            self.assertNotIn("WegePDV", nome)
            self.assertNotIn("Troco", nome)
            self.assertNotIn("Terminal", nome)

    def test_sequencial_ancora_itens_em_duas_linhas(self):
        # Layout em 2 linhas físicas: a 1ª (com o sequencial) só tem desc+EAN,
        # o valor/qtd vêm na 2ª. Ancorar no sequencial agrupa o bloco certinho.
        texto = (
            "SUPERMERCADO BOM PRECO LTDA\n"
            "001 7891000100103 LEITE INTEGRAL PIRACANJUBA\n"
            "1 UN X 4,99 4,99\n"
            "002 7896005800010 CAFE TRADICIONAL 500G\n"
            "2 UN X 12,50 25,00\n"
            "003 ARROZ BRANCO TIPO 1\n"
            "5 KG X 6,00 30,00\n"
            "VALOR TOTAL R$ 59,99"
        )
        r = parsear_cupom(texto_ocr=texto, buscar_online=False)
        self.assertEqual(len(r["itens"]), 3)
        leite = r["itens"][0]
        self.assertEqual(leite["nome"], "LEITE INTEGRAL PIRACANJUBA")
        self.assertEqual(leite["codigo"], "7891000100103")
        self.assertEqual(leite["quantidade"], 1.0)
        self.assertEqual(leite["valor"], 4.99)
        self.assertTrue(leite["identificado"])
        cafe = r["itens"][1]
        self.assertEqual(cafe["quantidade"], 2.0)
        self.assertEqual(cafe["valor"], 25.00)
        self.assertEqual(r["total"], 59.99)
        self.assertTrue(r["total_confere"])

    def test_sequencial_ignora_rodape_que_comeca_com_numero(self):
        # Garante que linhas de rodapé não viram "item 4" só por estarem após.
        texto = (
            "001 7891234567890 PRODUTO A 1 UN X 10,00 10,00\n"
            "002 7891234567891 PRODUTO B 1 UN X 5,00 5,00\n"
            "VALOR TOTAL R$ 15,00\n"
            "3 FORMAS DE PAGAMENTO ACEITAS"
        )
        r = parsear_cupom(texto_ocr=texto, buscar_online=False)
        self.assertEqual(len(r["itens"]), 2)
        nomes = " ".join(i["nome"] for i in r["itens"])
        self.assertNotIn("FORMAS", nomes)

    def test_qr_extrai_chave_e_uf(self):
        url = "https://www.fazenda.sp.gov.br/nfce?p=35240612345678000190650010000123451000123456|2|1"
        r = parsear_cupom(texto_ocr="", url_qr=url, buscar_online=False)
        self.assertEqual(r["origem"], "qr")
        self.assertEqual(r["chave"], "35240612345678000190650010000123451000123456")
        self.assertEqual(r["uf"], "SP")
        self.assertEqual(r["url_nfce"], url)

    def test_ignora_linhas_de_rodape(self):
        texto = "PAO  3,20\nTROCO  0,00\nFORMA PAGAMENTO CARTAO  3,20"
        r = parsear_cupom(texto_ocr=texto)
        nomes = [i["nome"] for i in r["itens"]]
        self.assertIn("PAO", nomes)
        self.assertNotIn("TROCO", nomes)

    def test_cabecalho_de_colunas_nao_fecha_os_itens(self):
        # O cabeçalho "...VL TOTAL" fica no topo, antes dos itens. Não pode ser
        # confundido com o rodapé de total (senão corta os itens na largada e o
        # total é lido do 1º item) — RN do parser, regressão de cupom NFC-e real.
        texto = (
            "#|COD|DESCRICAO|QTD|UN|VL UN|VL TOTAL\n"
            "001 7891234567890 BOLACHA 250G 1 UN X 6,49 6,49\n"
            "002 7891234567891 ARROZ 5KG 1 UN X 22,00 22,00\n"
            "VALOR TOTAL R$ 28,49"
        )
        r = parsear_cupom(texto_ocr=texto, buscar_online=False)
        self.assertEqual(len(r["itens"]), 2)
        self.assertEqual(r["itens"][0]["nome"], "BOLACHA 250G")
        self.assertEqual(r["total"], 28.49)
        self.assertTrue(r["total_confere"])

    def test_cabecalho_fundido_com_o_primeiro_item(self):
        # A reconstrução por Y às vezes funde a linha do cabeçalho com o 1º item
        # (ficam quase na mesma altura). Sem separar, o item abre com "#COD..." e
        # não é ancorado → é perdido. Regressão de cupom NFC-e real (Natal-RN).
        texto = (
            "#|COD|DESCRICAO|QTD|UN|VL UN|VL TOTAL  001 7898908222050 BOLACHA 250G 1 UN X 6,49 6,49\n"
            "002 7891152801842 ARROZ 5KG 1 UN X 22,00 22,00\n"
            "VALOR TOTAL R$ 28,49"
        )
        r = parsear_cupom(texto_ocr=texto, buscar_online=False)
        nomes = [i["nome"] for i in r["itens"]]
        self.assertIn("BOLACHA 250G", nomes)
        self.assertEqual(len(r["itens"]), 2)
        self.assertTrue(r["total_confere"])

    def test_rodape_embaralhado_pelo_ocr_nao_vira_item(self):
        # OCR térmico embaralha as palavras do rodapé ("TROCO"→"Iroco",
        # "DINHEIRO"→"Dirieiro"); a detecção fuzzy ainda as barra como item.
        texto = "PAO FRANCES 3,20\nIroco R$ 0,00\nDirieiro 50,00"
        r = parsear_cupom(texto_ocr=texto, buscar_online=False)
        nomes = " ".join(i["nome"] for i in r["itens"])
        self.assertIn("PAO", nomes)
        self.assertNotIn("Iroco", nomes)
        self.assertNotIn("Dirieiro", nomes)


_HTML_NFCE = """
<html><body>
  <div class="txtTopo">SUPERMERCADO X LTDA</div>
  <div>CNPJ: 12.345.678/0001-90</div>
  <table id="tabResult">
    <tr id="Item + 1">
      <td>
        <span class="txtTit">ARROZ TIO JOAO 5KG</span>
        <span class="RCod">(C&oacute;digo: 7891234567890)</span>
        <span class="Rqtd"><strong>Qtde.:</strong>1</span>
        <span class="RUN"><strong>UN: </strong>UN</span>
        <span class="RvlUnit"><strong>Vl. Unit.:</strong>&#160;22,90</span>
      </td>
      <td class="txtTit noWrap"><span class="valor">22,90</span></td>
    </tr>
    <tr id="Item + 2">
      <td>
        <span class="txtTit">LEITE INTEGRAL 1L</span>
        <span class="RCod">(C&oacute;digo: 7890000000001)</span>
        <span class="Rqtd"><strong>Qtde.:</strong>3</span>
        <span class="RUN"><strong>UN: </strong>UN</span>
        <span class="RvlUnit"><strong>Vl. Unit.:</strong>&#160;4,99</span>
      </td>
      <td class="txtTit noWrap"><span class="valor">14,97</span></td>
    </tr>
  </table>
  <div id="totalNota">
    <strong>Valor a pagar R$:</strong> <span class="totalNumb">37,87</span>
  </div>
  <div id="infos">Emiss&atilde;o: <strong>12/06/2026</strong> 10:30:00</div>
</body></html>
"""


class NfceParserTest(APITestCase):
    """Raspagem dos itens da NFC-e no portal da SEFAZ (RN-024) — sem rede."""

    def test_parsear_html_extrai_itens_estruturados(self):
        from .nfce import parsear_html

        r = parsear_html(_HTML_NFCE)
        self.assertIsNotNone(r)
        self.assertEqual(len(r["itens"]), 2)
        arroz = r["itens"][0]
        self.assertEqual(arroz["nome"], "ARROZ TIO JOAO 5KG")
        self.assertEqual(arroz["codigo"], "7891234567890")
        self.assertEqual(arroz["quantidade"], Decimal("1"))
        self.assertEqual(arroz["unidade"], "UN")
        self.assertEqual(arroz["valor_unitario"], Decimal("22.90"))
        self.assertEqual(arroz["valor"], Decimal("22.90"))
        self.assertTrue(arroz["identificado"])  # veio da SEFAZ: confiável
        self.assertEqual(r["estabelecimento"], "SUPERMERCADO X LTDA")
        self.assertEqual(r["total"], Decimal("37.87"))
        self.assertEqual(r["data"], "2026-06-12")

    def test_parsear_html_sem_itens_devolve_none(self):
        from .nfce import parsear_html

        self.assertIsNone(parsear_html("<html><body>captcha</body></html>"))

    def test_corrige_dominio_obsoleto_rn(self):
        # RN renomeou SET→SEFAZ; o QR antigo aponta pro domínio morto.
        from .nfce import corrigir_dominio

        old = "http://nfce.set.rn.gov.br/consultarNFCe.aspx?p=24|2|1"
        self.assertEqual(
            corrigir_dominio(old),
            "http://nfce.sefaz.rn.gov.br/consultarNFCe.aspx?p=24|2|1",
        )
        # Domínio de outra UF não é tocado.
        sp = "https://www.fazenda.sp.gov.br/nfce?p=35"
        self.assertEqual(corrigir_dominio(sp), sp)

    def test_url_nfce_salva_com_dominio_corrigido(self):
        url = "http://nfce.set.rn.gov.br/consultarNFCe.aspx?p=24260631737979000290652090000945991027817741|2|1"
        with mock.patch("apps.gastos.nfce.buscar_nfce", return_value=None):
            r = parsear_cupom(texto_ocr="PAO 3,20", url_qr=url)
        self.assertEqual(r["url_nfce"], url.replace("nfce.set.rn", "nfce.sefaz.rn"))
        self.assertEqual(r["uf"], "RN")

    def test_qr_usa_itens_da_nfce_quando_disponivel(self):
        url = "https://www.fazenda.sp.gov.br/nfce?p=35240612345678000190650010000123451000123456|2|1"
        with mock.patch("apps.gastos.nfce.buscar_nfce") as buscar:
            from .nfce import parsear_html

            buscar.return_value = parsear_html(_HTML_NFCE)
            r = parsear_cupom(texto_ocr="lixo de ocr 99,99", url_qr=url)
        self.assertEqual(r["origem"], "qr")
        self.assertEqual(len(r["itens"]), 2)  # da NFC-e, não do OCR
        self.assertEqual(r["estabelecimento"], "SUPERMERCADO X LTDA")
        self.assertTrue(r["itens"][0]["identificado"])
        self.assertTrue(r["total_confere"])
        self.assertEqual(r["chave"], "35240612345678000190650010000123451000123456")
        self.assertEqual(r["uf"], "SP")

    def test_cai_no_ocr_quando_nfce_falha(self):
        url = "https://www.fazenda.sp.gov.br/nfce?p=35240612345678000190650010000123451000123456|2|1"
        with mock.patch("apps.gastos.nfce.buscar_nfce", return_value=None):
            r = parsear_cupom(
                texto_ocr="001 ARROZ 5KG  1 UN x 22,90  22,90", url_qr=url
            )
        self.assertEqual(len(r["itens"]), 1)  # veio do OCR
        self.assertEqual(r["itens"][0]["nome"], "ARROZ 5KG")
        self.assertEqual(r["chave"], "35240612345678000190650010000123451000123456")


class OcrGeometriaTest(APITestCase):
    """Reconstrução por geometria + merge de item em 2 linhas (ML Kit real)."""

    def _frag(self, y, x, text):
        return {"text": text, "x": x, "y": y, "h": 20, "w": len(text) * 8}

    def _cupom_medeiros(self):
        # Como o ML Kit fragmenta: descrições/"qtd x" numa ordem e a COLUNA de
        # valores jogada no fim — cada fragmento com seu Y real.
        desc = [
            (600, 140, "001 7898908222050 BOLACHA JUCURUTU 250G MANTEIG"),
            (630, 180, "1,000UN x"), (630, 560, "F"),
            (660, 140, "002 7891152801842 BISCOITO RECH RICHESTER 125G"),
            (690, 180, "1,000UN x"), (690, 560, "F"),
            (720, 140, "005 826 PAO BOMDIA FRANCES KG"),
            (750, 180, "0,678KG x"), (750, 560, "F"),
            (820, 140, "VALOR A PAGAR R$"),
        ]
        vals = [
            (600, 720, "6,49"), (630, 400, "6,49"),
            (660, 720, "3,19"), (690, 400, "3,19"),
            (720, 720, "8,81"), (750, 400, "12,99"),
            (820, 720, "18,49"),
        ]
        return [self._frag(y, x, t) for (y, x, t) in desc + vals]

    def test_reconstroi_linhas_por_y(self):
        from .ocr_layout import reconstruir_texto

        texto = reconstruir_texto(self._cupom_medeiros())
        # O valor da 1ª linha (dumped no fim) volta pro lado da descrição.
        self.assertIn("BOLACHA JUCURUTU 250G MANTEIG  6,49", texto)
        self.assertIn("1,000UN x  6,49  F", texto)

    def test_duas_linhas_com_valor_na_linha_de_qtd(self):
        # Caso real: a reconstrução deixou a descrição SEM valor (o total foi pra
        # linha do "qtd x unit"). E "TEF" no rodapé não pode virar item.
        texto = (
            "001 7898908222050 BOLACHA JUCURUTU 250G MANTEIG\n"
            "1.000UN x 6,49  6,49\n"
            "005 826 PAO BOMDIA FRANCES KG\n"
            "0,678KG X 12,99  F  8,81\n"
            "FORMA PAGAMENTO  VALOR PAGO R$\n"
            "TEF  15,30"
        )
        r = parsear_cupom(texto_ocr=texto, buscar_online=False)
        nomes = [i["nome"] for i in r["itens"]]
        self.assertNotIn("TEF", nomes)  # rodapé de pagamento não vira item
        self.assertEqual(len(r["itens"]), 2)
        bol = r["itens"][0]
        self.assertEqual(bol["nome"], "BOLACHA JUCURUTU 250G MANTEIG")
        self.assertEqual(bol["quantidade"], 1.0)
        self.assertEqual(bol["valor"], 6.49)
        self.assertTrue(bol["identificado"])
        self.assertEqual(r["itens"][1]["valor"], 8.81)  # 0,678 x 12,99

    def test_item_em_duas_linhas_e_mesclado(self):
        r = parsear_cupom(linhas_ocr=self._cupom_medeiros(), buscar_online=False)
        self.assertEqual(len(r["itens"]), 3)  # rodapé não vira item
        bolacha = r["itens"][0]
        self.assertEqual(bolacha["nome"], "BOLACHA JUCURUTU 250G MANTEIG")
        self.assertEqual(bolacha["quantidade"], 1.0)
        self.assertEqual(bolacha["unidade"], "UN")
        self.assertEqual(bolacha["valor_unitario"], 6.49)
        self.assertEqual(bolacha["valor"], 6.49)
        self.assertTrue(bolacha["identificado"])
        # Tamanho do produto não vira quantidade.
        bisc = r["itens"][1]
        self.assertEqual(bisc["nome"], "BISCOITO RECH RICHESTER 125G")
        self.assertEqual(bisc["quantidade"], 1.0)
        # Item por peso.
        pao = r["itens"][2]
        self.assertEqual(pao["quantidade"], 0.678)
        self.assertEqual(pao["unidade"], "KG")
        self.assertEqual(pao["valor"], 8.81)
        self.assertTrue(pao["identificado"])


class CompraDetalhadaTest(APITestCase):
    """Endpoint do scanner + gravação aninhada de itens (RF-022/023/025)."""

    def setUp(self):
        self.ana = criar_usuario("ana@x.com", "Ana")
        self.client.force_authenticate(self.ana)
        self.categoria = criar_categoria(self.ana)

    def test_parsear_cupom_action(self):
        resp = self.client.post(
            reverse("gastos:gasto-parsear-cupom"),
            {"texto_ocr": "001 ARROZ 5KG  1 UN x 22,90  22,90\nVALOR TOTAL R$ 22,90"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(len(resp.data["itens"]), 1)
        self.assertEqual(resp.data["total"], 22.90)

    def test_parsear_cupom_sem_entrada_invalido(self):
        resp = self.client.post(
            reverse("gastos:gasto-parsear-cupom"), {}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cria_gasto_com_compra_detalhada(self):
        payload = {
            "descricao": "Mercado",
            "valor": "37.87",
            "data": "2026-03-05",
            "categoria": self.categoria.id,
            "forma_pagamento": "pix",
            "origem": "ocr",
            "compra_detalhada": {
                "estabelecimento": "Mercado X",
                "origem": "ocr",
                "url_nfce": None,
                "itens": [
                    {"nome": "Arroz", "valor": "22.90", "quantidade": "1", "unidade": "UN"},
                    {"nome": "Leite", "valor": "14.97", "quantidade": "3"},
                ],
            },
        }
        resp = self.client.post(
            reverse("gastos:gasto-list"), payload, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        gasto = Gasto.objects.get(id=resp.data["id"])
        self.assertEqual(gasto.compra_detalhada.itens.count(), 2)
        self.assertEqual(resp.data["compra_detalhada"]["estabelecimento"], "Mercado X")

    def test_gasto_sem_detalhamento_retorna_null(self):
        resp = self.client.post(
            reverse("gastos:gasto-list"),
            {
                "descricao": "Café",
                "valor": "5.00",
                "data": "2026-03-05",
                "categoria": self.categoria.id,
                "forma_pagamento": "pix",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertIsNone(resp.data["compra_detalhada"])

    def test_item_com_categoria_de_outro_dono_invalido(self):
        outro = criar_usuario("bob@x.com", "Bob")
        cat_alheia = criar_categoria(outro)
        payload = {
            "descricao": "Mercado",
            "valor": "10.00",
            "data": "2026-03-05",
            "categoria": self.categoria.id,
            "forma_pagamento": "pix",
            "compra_detalhada": {
                "origem": "manual",
                "itens": [{"nome": "X", "valor": "10.00", "categoria": cat_alheia.id}],
            },
        }
        resp = self.client.post(
            reverse("gastos:gasto-list"), payload, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

