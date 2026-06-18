from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.categorias.models import Categoria
from apps.gastos.models import Gasto
from apps.receitas.models import Receita

from .models import Importacao, MovimentacaoDetectada
from .parsers import ArquivoInvalido, parsear_csv, parsear_ofx
from .pix import identificar_banco, parsear_notificacao

Usuario = get_user_model()


class PixNotificacaoTest(SimpleTestCase):
    def test_nubank_recebido_com_nome(self):
        r = parsear_notificacao(
            titulo="Transferência recebida",
            texto="Você recebeu uma transferência de R$2,00 de Fulano de Tal",
        )
        self.assertEqual(r["tipo"], "recebido")
        self.assertEqual(r["valor"], 2.0)
        self.assertEqual(r["contraparte"], "Fulano de Tal")

    def test_nubank_recebido_sem_nome(self):
        r = parsear_notificacao(texto="Recebemos sua transferência de R$ 50,00")
        self.assertEqual(r["tipo"], "recebido")
        self.assertEqual(r["valor"], 50.0)
        self.assertIsNone(r["contraparte"])

    def test_enviado_com_nome_e_valor_grande(self):
        r = parsear_notificacao(texto="Pix enviado: R$ 1.234,56 para Maria Souza")
        self.assertEqual(r["tipo"], "enviado")
        self.assertEqual(r["valor"], 1234.56)
        self.assertEqual(r["contraparte"], "Maria Souza")

    def test_nao_e_pix(self):
        r = parsear_notificacao(texto="Sua fatura fecha amanhã")
        self.assertIsNone(r["tipo"])

    def test_identificar_banco_por_pacote(self):
        self.assertEqual(identificar_banco("com.nu.production"), "Nubank")
        self.assertIsNone(identificar_banco("com.whatsapp"))


class CaixaRevisaoEndpointTest(APITestCase):
    def setUp(self):
        self.user = Usuario.objects.create_user(email="a@x.com", password="x", nome="A")
        self.client.force_authenticate(self.user)
        self.cat = Categoria.objects.create(usuario=self.user, nome="Mercado")

    def _receber(self, **body):
        return self.client.post(reverse("importacao:movimentacaodetectada-list"), body, format="json")

    def test_nao_pix_nao_guarda(self):
        resp = self._receber(texto="Promoção imperdível!")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["ignorada"])
        self.assertEqual(MovimentacaoDetectada.objects.count(), 0)

    def test_recebido_guarda_pendente(self):
        resp = self._receber(
            pacote="com.nu.production",
            texto="Você recebeu uma transferência de R$2,00 de João",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(resp.data["tipo"], "recebido")
        self.assertEqual(Decimal(resp.data["valor"]), Decimal("2.00"))
        self.assertEqual(resp.data["contraparte"], "João")
        self.assertEqual(resp.data["banco"], "Nubank")
        self.assertEqual(resp.data["status"], "pendente")

    def test_dedupe_nao_duplica(self):
        body = dict(pacote="com.nu.production", texto="Você recebeu uma transferência de R$2,00 de João")
        self._receber(**body)
        self._receber(**body)
        self.assertEqual(MovimentacaoDetectada.objects.count(), 1)

    def test_confirmar_recebido_cria_receita(self):
        resp = self._receber(texto="Você recebeu uma transferência de R$10,00 de Ana")
        mov_id = resp.data["id"]
        resp = self.client.post(
            reverse("importacao:movimentacaodetectada-confirmar", args=[mov_id])
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["status"], "confirmada")
        self.assertIsNotNone(resp.data["receita"])
        rec = Receita.objects.get(id=resp.data["receita"])
        self.assertEqual(rec.valor, Decimal("10.00"))
        self.assertEqual(rec.descricao, "Pix de Ana")
        self.assertIsNotNone(rec.data_real)  # já recebida

    def test_confirmar_enviado_cria_gasto_pix(self):
        resp = self._receber(texto="Pix enviado R$ 25,00 para Padaria")
        mov_id = resp.data["id"]
        resp = self.client.post(
            reverse("importacao:movimentacaodetectada-confirmar", args=[mov_id]),
            {"categoria": self.cat.id},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        gasto = Gasto.objects.get(id=resp.data["gasto"])
        self.assertEqual(gasto.valor, Decimal("25.00"))
        self.assertEqual(gasto.forma_pagamento, "pix")
        self.assertEqual(gasto.categoria_id, self.cat.id)

    def test_confirmar_sem_valor_pede_valor(self):
        resp = self._receber(texto="Transferência recebida")  # sem valor
        mov_id = resp.data["id"]
        resp = self.client.post(
            reverse("importacao:movimentacaodetectada-confirmar", args=[mov_id])
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_ignorar(self):
        resp = self._receber(texto="Você recebeu uma transferência de R$5,00 de Zé")
        mov_id = resp.data["id"]
        resp = self.client.post(
            reverse("importacao:movimentacaodetectada-ignorar", args=[mov_id])
        )
        self.assertEqual(resp.data["status"], "ignorada")

    def test_escopo_por_usuario(self):
        self._receber(texto="Você recebeu uma transferência de R$5,00 de Zé")
        outro = Usuario.objects.create_user(email="b@x.com", password="x", nome="B")
        self.client.force_authenticate(outro)
        resp = self.client.get(reverse("importacao:movimentacaodetectada-list"))
        self.assertEqual(len(resp.data["results"]), 0)


OFX_EXEMPLO = """OFXHEADER:100
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><BANKTRANLIST>
<STMTTRN>
<TRNTYPE>DEBIT
<DTPOSTED>20240115120000[-3:GMT]
<TRNAMT>-45.90
<FITID>1
<NAME>SUPERMERCADO BOM PRECO
</STMTTRN>
<STMTTRN>
<TRNTYPE>CREDIT
<DTPOSTED>20240120
<TRNAMT>3000.00
<FITID>2
<MEMO>SALARIO EMPRESA XYZ
</STMTTRN>
</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>
"""


class ParserOfxCsvTest(SimpleTestCase):
    def test_ofx_extrai_gasto_e_receita(self):
        t = parsear_ofx(OFX_EXEMPLO)
        self.assertEqual(len(t), 2)
        gasto, receita = t
        self.assertEqual(gasto["tipo"], "gasto")
        self.assertEqual(gasto["valor"], Decimal("45.90"))
        self.assertEqual(gasto["data"], date(2024, 1, 15))
        self.assertEqual(gasto["descricao"], "SUPERMERCADO BOM PRECO")
        self.assertEqual(receita["tipo"], "receita")
        self.assertEqual(receita["valor"], Decimal("3000.00"))
        self.assertEqual(receita["data"], date(2024, 1, 20))

    def test_ofx_sem_transacoes_levanta(self):
        with self.assertRaises(ArquivoInvalido):
            parsear_ofx("<OFX>nada aqui</OFX>")

    def test_csv_com_cabecalho_ponto_virgula(self):
        csv = "Data;Descrição;Valor\n15/01/2024;Farmácia;-30,50\n20/01/2024;Reembolso;100,00\n"
        t = parsear_csv(csv)
        self.assertEqual(len(t), 2)
        self.assertEqual(t[0]["tipo"], "gasto")
        self.assertEqual(t[0]["valor"], Decimal("30.50"))
        self.assertEqual(t[0]["data"], date(2024, 1, 15))
        self.assertEqual(t[1]["tipo"], "receita")

    def test_csv_virgula_milhar_e_ponto_decimal(self):
        csv = "date,memo,amount\n2024-02-01,Aluguel,-1234.56\n"
        t = parsear_csv(csv)
        self.assertEqual(t[0]["valor"], Decimal("1234.56"))

    def test_csv_picpay_titulo_da_origem_e_sinal_unicode(self):
        # Layout PicPay: descrição vem de "origem / destino" (fallback "tipo"),
        # valor com o sinal Unicode − (U+2212) e "R$ 2.658,49".
        csv = (
            'data,hora,tipo,"origem / destino",valor,"forma de pagamento"\n'
            '2026-06-16,09:30,"Pagamento realizado",MIDWAY,"−R$ 74,50","Com cartão"\n'
            '2026-06-13,20:13,"Compra realizada",,"−R$ 96,99","Com saldo"\n'
            '2026-06-05,17:35,"Pagamento realizado","Fatura PicPay Card","−R$ 2.658,49","Com saldo"\n'
            '2026-06-05,17:35,"Pix recebido","PAULO HOLANDA","+R$ 183,30",\n'
        )
        csv += '2026-06-08,10:52,"Pix enviado","NUBUS S/A","−R$ 37,45","Com cartão"\n'
        t = parsear_csv(csv)
        self.assertEqual(len(t), 5)
        self.assertEqual(t[0]["descricao"], "MIDWAY")
        self.assertEqual(t[0]["valor"], Decimal("74.50"))
        self.assertEqual(t[0]["tipo"], "gasto")
        self.assertEqual(t[0]["forma"], "credito")  # "Com cartão"
        self.assertEqual(t[1]["descricao"], "Compra realizada")  # origem vazia → tipo
        self.assertEqual(t[1]["forma"], "debito")  # "Com saldo"
        self.assertEqual(t[2]["descricao"], "Fatura PicPay Card")
        self.assertEqual(t[2]["valor"], Decimal("2658.49"))
        self.assertEqual(t[3]["descricao"], "PAULO HOLANDA")
        self.assertEqual(t[3]["tipo"], "receita")  # +valor
        self.assertEqual(t[4]["forma"], "pix")  # tipo "Pix" vence o "Com cartão"


class ImportacaoEndpointTest(APITestCase):
    def setUp(self):
        self.user = Usuario.objects.create_user(email="i@x.com", password="x", nome="I")
        self.client.force_authenticate(self.user)
        self.cat = Categoria.objects.create(usuario=self.user, nome="Mercado")

    def _previa(self, conteudo, nome="extrato.ofx"):
        arq = SimpleUploadedFile(nome, conteudo.encode("utf-8"))
        return self.client.post(
            reverse("importacao:importacao-previa"), {"arquivo": arq}, format="multipart"
        )

    def test_previa_ofx_lista_transacoes(self):
        resp = self._previa(OFX_EXEMPLO)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["quantidade"], 2)
        self.assertEqual(resp.data["transacoes"][0]["tipo"], "gasto")
        self.assertIn("duplicata", resp.data["transacoes"][0])

    def test_previa_sugere_categoria_por_historico(self):
        Gasto.objects.create(
            usuario=self.user, descricao="SUPERMERCADO BOM PRECO", valor=Decimal("10"),
            data=date(2023, 12, 1), categoria=self.cat, forma_pagamento="debito",
        )
        resp = self._previa(OFX_EXEMPLO)
        self.assertEqual(resp.data["transacoes"][0]["categoria_sugerida"], self.cat.id)

    def test_previa_marca_duplicata(self):
        Gasto.objects.create(
            usuario=self.user, descricao="SUPERMERCADO BOM PRECO", valor=Decimal("45.90"),
            data=date(2024, 1, 15), categoria=self.cat, forma_pagamento="debito",
        )
        resp = self._previa(OFX_EXEMPLO)
        self.assertTrue(resp.data["transacoes"][0]["duplicata"])

    def test_previa_arquivo_invalido_400(self):
        resp = self._previa("lixo sem transacao", nome="x.ofx")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_confirmar_cria_gastos_e_receitas(self):
        payload = {
            "arquivo_nome": "extrato.ofx",
            "formato": "ofx",
            "transacoes": [
                {"data": "2024-01-15", "valor": "45.90", "descricao": "Mercado",
                 "tipo": "gasto", "categoria": self.cat.id, "forma_pagamento": "debito"},
                {"data": "2024-01-20", "valor": "3000.00", "descricao": "Salário",
                 "tipo": "receita", "tipo_receita": "salario"},
            ],
        }
        resp = self.client.post(
            reverse("importacao:importacao-confirmar"), payload, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(resp.data["criados"], {"gastos": 1, "receitas": 1})
        self.assertEqual(Gasto.objects.filter(usuario=self.user).count(), 1)
        rec = Receita.objects.get(usuario=self.user)
        self.assertIsNotNone(rec.data_real)  # extrato = já realizado
        self.assertEqual(Importacao.objects.filter(usuario=self.user).count(), 1)

    def test_confirmar_credito_sem_cartao_cai_pra_debito(self):
        payload = {
            "formato": "csv",
            "transacoes": [
                {"data": "2024-01-15", "valor": "10.00", "descricao": "X",
                 "tipo": "gasto", "categoria": self.cat.id, "forma_pagamento": "credito"},
            ],
        }
        resp = self.client.post(
            reverse("importacao:importacao-confirmar"), payload, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(Gasto.objects.get(usuario=self.user).forma_pagamento, "debito")
