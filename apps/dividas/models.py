"""
Dívidas e parcelamentos — RF-050, RN-050, RN-051.

`Divida` é o cadastro do parcelamento/dívida do dono. Ao criar, o sistema
**gera automaticamente** todas as `Parcela`s com datas e valores (RN-050),
ligando cada uma à `Fatura` do cartão quando for parcelamento no cartão. A
projeção de quitação (mês/ano, pago, restante) é derivada em consulta (RN-051).
Pode ser compartilhada via vínculo (modelo-de-dados §1).
"""

import calendar
from decimal import Decimal

from django.db import models

from apps.common.models import OwnedModel, TimeStampedModel


def _soma_meses(data, meses):
    """`data` somada de `meses` meses, com o dia limitado ao último do mês destino."""
    total = data.month - 1 + meses
    ano = data.year + total // 12
    mes = total % 12 + 1
    ultimo = calendar.monthrange(ano, mes)[1]
    return data.replace(year=ano, month=mes, day=min(data.day, ultimo))


class Divida(OwnedModel):
    class Tipo(models.TextChoices):
        PARCELAMENTO_CARTAO = "parcelamento_cartao", "Parcelamento no cartão"
        FINANCIAMENTO = "financiamento", "Financiamento"
        EMPRESTIMO = "emprestimo", "Empréstimo"
        INFORMAL = "informal", "Dívida informal"

    descricao = models.CharField("descrição", max_length=120)
    tipo = models.CharField("tipo", max_length=20, choices=Tipo.choices)
    valor_total = models.DecimalField("valor total", max_digits=12, decimal_places=2)
    numero_parcelas = models.PositiveSmallIntegerField("número de parcelas")
    valor_parcela = models.DecimalField(
        "valor da parcela", max_digits=12, decimal_places=2
    )
    parcela_inicial = models.PositiveSmallIntegerField("parcela inicial", default=1)
    data_primeira_parcela = models.DateField("data da primeira parcela")
    juros = models.DecimalField(
        "juros (%)", max_digits=6, decimal_places=3, null=True, blank=True
    )
    cartao = models.ForeignKey(
        "cartoes.Cartao",
        on_delete=models.PROTECT,  # cartão usa soft delete
        null=True,
        blank=True,
        related_name="dividas",
        verbose_name="cartão",
    )
    # Compartilhamento (ver CLAUDE.md › Conventions e modelo-de-dados §1).
    compartilhado = models.BooleanField("compartilhado", default=False)
    vinculo = models.ForeignKey(
        "vinculos.Vinculo",
        on_delete=models.SET_NULL,  # RN-002: desfazer vínculo não apaga a dívida
        null=True,
        blank=True,
        related_name="dividas",
        verbose_name="vínculo",
    )
    valor_dono = models.DecimalField(
        "valor do dono", max_digits=12, decimal_places=2, null=True, blank=True
    )
    valor_vinculado = models.DecimalField(
        "valor do vinculado", max_digits=12, decimal_places=2, null=True, blank=True
    )

    class Meta:
        verbose_name = "dívida"
        verbose_name_plural = "dívidas"
        ordering = ["-data_primeira_parcela", "-id"]

    def __str__(self):
        return f"{self.descricao} ({self.numero_parcelas}x)"

    def gerar_parcelas(self):
        """
        RN-050: cria as parcelas de `parcela_inicial` até `numero_parcelas`, uma
        por mês a partir de `data_primeira_parcela`. No parcelamento no cartão,
        liga cada parcela à fatura do mês correspondente. Idempotente: não recria
        se já houver parcelas.
        """
        if self.parcelas.exists():
            return
        parcelas = []
        for offset in range(self.numero_parcelas - self.parcela_inicial + 1):
            vencimento = _soma_meses(self.data_primeira_parcela, offset)
            mes_referencia = vencimento.replace(day=1)
            fatura = None
            if self.cartao_id:
                fatura, _ = self.cartao.faturas.get_or_create(
                    mes_referencia=mes_referencia
                )
            parcelas.append(
                Parcela(
                    divida=self,
                    numero=self.parcela_inicial + offset,
                    valor=self.valor_parcela,
                    mes_referencia=mes_referencia,
                    data_vencimento=vencimento,
                    fatura=fatura,
                )
            )
        Parcela.objects.bulk_create(parcelas)

    # --- Projeção de quitação (RN-051), derivada em consulta ---

    @property
    def valor_pago(self):
        return self.parcelas.filter(status=Parcela.Status.PAGA).aggregate(
            t=models.Sum("valor")
        )["t"] or Decimal("0.00")

    @property
    def valor_restante(self):
        return self.parcelas.filter(status=Parcela.Status.PENDENTE).aggregate(
            t=models.Sum("valor")
        )["t"] or Decimal("0.00")

    @property
    def mes_quitacao(self):
        """Mês de referência da última parcela (estimativa de quitação)."""
        ultima = self.parcelas.order_by("-mes_referencia").first()
        return ultima.mes_referencia if ultima else None


class Parcela(TimeStampedModel):
    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        PAGA = "paga", "Paga"

    divida = models.ForeignKey(
        Divida,
        on_delete=models.CASCADE,
        related_name="parcelas",
        verbose_name="dívida",
    )
    numero = models.PositiveSmallIntegerField("número")
    valor = models.DecimalField("valor", max_digits=12, decimal_places=2)
    mes_referencia = models.DateField("mês de referência")  # 1º dia do mês
    data_vencimento = models.DateField("data de vencimento")
    status = models.CharField(
        "status", max_length=10, choices=Status.choices, default=Status.PENDENTE
    )
    fatura = models.ForeignKey(
        "cartoes.Fatura",
        on_delete=models.SET_NULL,  # fatura é gerada; remover não apaga a parcela
        null=True,
        blank=True,
        related_name="parcelas",
        verbose_name="fatura",
    )

    class Meta:
        verbose_name = "parcela"
        verbose_name_plural = "parcelas"
        ordering = ["divida", "numero"]
        constraints = [
            models.UniqueConstraint(
                fields=["divida", "numero"], name="parcela_unica_por_divida"
            ),
        ]

    def __str__(self):
        return f"{self.divida.descricao} — {self.numero}/{self.divida.numero_parcelas}"
