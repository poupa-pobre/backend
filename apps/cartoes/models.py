"""
Cartões de crédito e faturas — RF-040, RF-041, RN-040.

`Cartao` é do usuário (soft delete via `status=inativo`). `Fatura` é a
agregação mensal por cartão (uma por `mes_referencia`). A **composição** da
fatura (somar gastos fixos + parcelas + gastos variáveis) é da Fase 3; aqui
fica a estrutura + o cálculo de **competência** pelo dia de fechamento.
"""

import calendar
from datetime import date

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.common.models import OwnedModel, TimeStampedModel


def competencia(data, dia_fechamento):
    """
    Mês de referência (1º dia) ao qual um gasto pertence, dado o dia de
    fechamento do cartão (RN-040):

    - gasto **até** o dia de fechamento → fatura do mês atual;
    - gasto **após** o dia de fechamento → fatura do mês seguinte.

    O dia de fechamento é limitado ao último dia do mês (ex.: fechamento 31
    em fevereiro vira 28/29).
    """
    ultimo_dia = calendar.monthrange(data.year, data.month)[1]
    fechamento = min(dia_fechamento, ultimo_dia)
    ano, mes = data.year, data.month
    if data.day > fechamento:
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return date(ano, mes, 1)


class Cartao(OwnedModel):
    class Status(models.TextChoices):
        ATIVO = "ativo", "Ativo"
        INATIVO = "inativo", "Inativo"

    nome = models.CharField("nome", max_length=60)
    cor = models.CharField("cor", max_length=7, null=True, blank=True)  # #RRGGBB
    limite_total = models.DecimalField("limite total", max_digits=12, decimal_places=2)
    dia_fechamento = models.PositiveSmallIntegerField(
        "dia de fechamento", validators=[MinValueValidator(1), MaxValueValidator(31)]
    )
    dia_vencimento = models.PositiveSmallIntegerField(
        "dia de vencimento", validators=[MinValueValidator(1), MaxValueValidator(31)]
    )
    status = models.CharField(
        "status", max_length=10, choices=Status.choices, default=Status.ATIVO
    )

    class Meta:
        verbose_name = "cartão"
        verbose_name_plural = "cartões"
        ordering = ["nome"]

    def __str__(self):
        return self.nome

    def competencia_de(self, data):
        """`mes_referencia` da fatura em que um gasto nesta data cai (RN-040)."""
        return competencia(data, self.dia_fechamento)

    def fatura_do_mes(self, data):
        """Fatura (get_or_create) correspondente à competência da data."""
        fatura, _ = self.faturas.get_or_create(
            mes_referencia=self.competencia_de(data)
        )
        return fatura


class Fatura(TimeStampedModel):
    class Status(models.TextChoices):
        ABERTA = "aberta", "Aberta"
        FECHADA = "fechada", "Fechada"
        PAGA = "paga", "Paga"

    cartao = models.ForeignKey(
        Cartao,
        on_delete=models.CASCADE,
        related_name="faturas",
        verbose_name="cartão",
    )
    mes_referencia = models.DateField("mês de referência")  # 1º dia do mês
    # `total` é derivado da composição (Fase 3); mantido como cache opcional.
    total = models.DecimalField(
        "total", max_digits=12, decimal_places=2, default=0
    )
    status = models.CharField(
        "status", max_length=10, choices=Status.choices, default=Status.ABERTA
    )
    data_pagamento = models.DateField("data de pagamento", null=True, blank=True)
    valor_pago = models.DecimalField(
        "valor pago", max_digits=12, decimal_places=2, null=True, blank=True
    )

    class Meta:
        verbose_name = "fatura"
        verbose_name_plural = "faturas"
        ordering = ["-mes_referencia"]
        constraints = [
            models.UniqueConstraint(
                fields=["cartao", "mes_referencia"], name="fatura_unica_por_mes"
            ),
        ]

    def __str__(self):
        return f"{self.cartao.nome} — {self.mes_referencia:%m/%Y} ({self.status})"

    def composicao(self):
        """Agregação dos itens da fatura (RF-041..043). Ver `cartoes.composicao`."""
        from .composicao import compor_fatura

        return compor_fatura(self)

    def recompor(self):
        """Recalcula e persiste o cache `total` a partir da composição."""
        composicao = self.composicao()
        self.total = composicao["total"]
        self.save(update_fields=["total", "updated_at"])
        return composicao
