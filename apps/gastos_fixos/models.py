"""
Gastos fixos — RF-030, RF-031, RN-030, RN-031, RN-032.

`GastoFixo` é o **template** do compromisso recorrente do dono (soft delete via
`ativo`). Dois tipos: **A** (valor fixo) e **B** (valor estimado, valor real
informado no mês). `GastoFixoMensal` é a **instância** mensal, pré-criada pelo
job mensal (RN-030) como `pendente`, com `UNIQUE(gasto_fixo, mes_referencia)`.
O check (RN-031) marca `pago`; o vencimento vencido sem check vira `atrasado`
(RN-032). Pode ser compartilhado via vínculo (modelo-de-dados §1).
"""

import calendar
from datetime import date

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.common.models import OwnedModel, TimeStampedModel


def _dia_no_mes(mes_referencia, dia):
    """Data do `dia` dentro do mês de `mes_referencia`, limitada ao último dia."""
    ultimo = calendar.monthrange(mes_referencia.year, mes_referencia.month)[1]
    return mes_referencia.replace(day=min(dia, ultimo))


class GastoFixo(OwnedModel):
    class Tipo(models.TextChoices):
        FIXO = "A", "Tipo A — fixo"
        ESTIMADO = "B", "Tipo B — estimado"

    class FormaPagamento(models.TextChoices):
        CARTAO = "cartao", "Cartão"
        DEBITO = "debito", "Débito"
        PIX = "pix", "Pix"
        BOLETO = "boleto", "Boleto"

    descricao = models.CharField("descrição", max_length=120)
    tipo = models.CharField("tipo", max_length=1, choices=Tipo.choices)
    valor = models.DecimalField(
        "valor", max_digits=12, decimal_places=2, null=True, blank=True
    )  # obrigatório no tipo A
    valor_estimado = models.DecimalField(
        "valor estimado", max_digits=12, decimal_places=2, null=True, blank=True
    )  # referência no tipo B
    dia_vencimento = models.PositiveSmallIntegerField(
        "dia de vencimento",
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(31)],
    )
    categoria = models.ForeignKey(
        "categorias.Categoria",
        on_delete=models.PROTECT,  # categoria usa soft delete
        related_name="gastos_fixos",
        verbose_name="categoria",
    )
    forma_pagamento = models.CharField(
        "forma de pagamento",
        max_length=15,
        choices=FormaPagamento.choices,
        null=True,
        blank=True,
    )
    cartao = models.ForeignKey(
        "cartoes.Cartao",
        on_delete=models.PROTECT,  # cartão usa soft delete
        null=True,
        blank=True,
        related_name="gastos_fixos",
        verbose_name="cartão",
    )
    # Compartilhamento (ver CLAUDE.md › Conventions e modelo-de-dados §1).
    compartilhado = models.BooleanField("compartilhado", default=False)
    vinculo = models.ForeignKey(
        "vinculos.Vinculo",
        on_delete=models.SET_NULL,  # RN-002: desfazer vínculo não apaga o template
        null=True,
        blank=True,
        related_name="gastos_fixos",
        verbose_name="vínculo",
    )
    valor_dono = models.DecimalField(
        "valor do dono", max_digits=12, decimal_places=2, null=True, blank=True
    )
    valor_vinculado = models.DecimalField(
        "valor do vinculado", max_digits=12, decimal_places=2, null=True, blank=True
    )
    ativo = models.BooleanField("ativo", default=True)  # soft delete

    class Meta:
        verbose_name = "gasto fixo"
        verbose_name_plural = "gastos fixos"
        ordering = ["descricao"]

    def __str__(self):
        return f"{self.descricao} ({self.get_tipo_display()})"

    @property
    def valor_base(self):
        """Valor de referência do template: fixo (A) ou estimado (B)."""
        return self.valor if self.tipo == self.Tipo.FIXO else self.valor_estimado

    def gerar_mensal(self, mes_referencia):
        """Cria (idempotente) a instância mensal `pendente` deste fixo (RN-030)."""
        instancia, _ = self.mensais.get_or_create(mes_referencia=mes_referencia)
        return instancia


class GastoFixoMensal(TimeStampedModel):
    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        PAGO = "pago", "Pago"
        ATRASADO = "atrasado", "Atrasado"

    gasto_fixo = models.ForeignKey(
        GastoFixo,
        on_delete=models.CASCADE,
        related_name="mensais",
        verbose_name="gasto fixo",
    )
    mes_referencia = models.DateField("mês de referência")  # 1º dia do mês
    valor_real = models.DecimalField(
        "valor real", max_digits=12, decimal_places=2, null=True, blank=True
    )  # informado no check do tipo B
    status = models.CharField(
        "status", max_length=10, choices=Status.choices, default=Status.PENDENTE
    )
    data_pagamento = models.DateField("data de pagamento", null=True, blank=True)
    checked_at = models.DateTimeField("check em", null=True, blank=True)

    class Meta:
        verbose_name = "gasto fixo mensal"
        verbose_name_plural = "gastos fixos mensais"
        ordering = ["-mes_referencia", "gasto_fixo__descricao"]
        constraints = [
            models.UniqueConstraint(
                fields=["gasto_fixo", "mes_referencia"],
                name="gastofixomensal_unico_por_mes",
            ),
        ]

    def __str__(self):
        return f"{self.gasto_fixo.descricao} — {self.mes_referencia:%m/%Y} ({self.status})"

    @property
    def valor_efetivo(self):
        """Valor que entra nos totais: `valor_real` se informado, senão o do template."""
        if self.valor_real is not None:
            return self.valor_real
        return self.gasto_fixo.valor_base

    @property
    def data_vencimento(self):
        """Vencimento desta instância: `dia_vencimento` do template no mês."""
        dia = self.gasto_fixo.dia_vencimento
        if not dia:
            return None
        return _dia_no_mes(self.mes_referencia, dia)

    def esta_atrasado(self, hoje=None):
        """RN-032: pendente cujo vencimento já passou."""
        if self.status != self.Status.PENDENTE:
            return False
        venc = self.data_vencimento
        return bool(venc and (hoje or date.today()) > venc)
