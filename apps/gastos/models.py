"""
Gastos do dia a dia — RF-020, RN-020, RN-021.

`Gasto` é o lançamento variável do usuário (quem gastou é o dono). No crédito,
o `cartao` é obrigatório e o `mes_referencia` segue a **competência** pelo dia
de fechamento (RN-040, via `Cartao.competencia_de`); nas demais formas, é o 1º
dia do mês da `data`. Pode ser **compartilhado** com um vínculo aceito, rateando
`valor_dono + valor_vinculado = valor` (RN-021) — sem duplicar o item.

Tags são N:M via `GastoTag`. O detalhamento por scanner (`CompraDetalhada`,
`ItemCompra`) é da Fase 5.
"""

from django.db import models

from apps.common.models import OwnedModel


class Gasto(OwnedModel):
    class FormaPagamento(models.TextChoices):
        DINHEIRO = "dinheiro", "Dinheiro"
        PIX = "pix", "Pix"
        DEBITO = "debito", "Débito"
        CREDITO = "credito", "Crédito"

    class Origem(models.TextChoices):
        MANUAL = "manual", "Manual"
        QR = "qr", "QR Code"
        OCR = "ocr", "OCR"

    descricao = models.CharField("descrição", max_length=120)
    valor = models.DecimalField("valor", max_digits=12, decimal_places=2)
    data = models.DateField("data")
    categoria = models.ForeignKey(
        "categorias.Categoria",
        on_delete=models.PROTECT,  # categoria usa soft delete; nunca apaga histórico
        related_name="gastos",
        verbose_name="categoria",
    )
    subcategoria = models.ForeignKey(
        "categorias.Subcategoria",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="gastos",
        verbose_name="subcategoria",
    )
    forma_pagamento = models.CharField(
        "forma de pagamento", max_length=15, choices=FormaPagamento.choices
    )
    cartao = models.ForeignKey(
        "cartoes.Cartao",
        on_delete=models.PROTECT,  # cartão usa soft delete
        null=True,
        blank=True,
        related_name="gastos",
        verbose_name="cartão",
    )
    # Compartilhamento (ver CLAUDE.md › Conventions e modelo-de-dados §1).
    compartilhado = models.BooleanField("compartilhado", default=False)
    vinculo = models.ForeignKey(
        "vinculos.Vinculo",
        on_delete=models.SET_NULL,  # RN-002: desfazer vínculo não apaga o gasto
        null=True,
        blank=True,
        related_name="gastos",
        verbose_name="vínculo",
    )
    valor_dono = models.DecimalField(
        "valor do dono", max_digits=12, decimal_places=2, null=True, blank=True
    )
    valor_vinculado = models.DecimalField(
        "valor do vinculado", max_digits=12, decimal_places=2, null=True, blank=True
    )
    observacao = models.TextField("observação", null=True, blank=True)
    origem = models.CharField(
        "origem", max_length=10, choices=Origem.choices, default=Origem.MANUAL
    )
    tags = models.ManyToManyField(
        "categorias.Tag",
        through="GastoTag",
        related_name="gastos",
        blank=True,
        verbose_name="tags",
    )
    mes_referencia = models.DateField("mês de referência")  # 1º dia do mês

    class Meta:
        verbose_name = "gasto"
        verbose_name_plural = "gastos"
        ordering = ["-data", "-id"]

    def __str__(self):
        return f"{self.descricao} — R$ {self.valor}"

    def competencia(self):
        """`mes_referencia` deste gasto: competência do cartão no crédito (RN-040),
        senão o 1º dia do mês da data."""
        if self.forma_pagamento == self.FormaPagamento.CREDITO and self.cartao_id:
            return self.cartao.competencia_de(self.data)
        return self.data.replace(day=1)

    def save(self, *args, **kwargs):
        self.mes_referencia = self.competencia()
        super().save(*args, **kwargs)
        # Garante a fatura do mês para a composição do cartão (Fase 3).
        if self.forma_pagamento == self.FormaPagamento.CREDITO and self.cartao_id:
            self.cartao.fatura_do_mes(self.data)


class GastoTag(models.Model):
    """Junção N:M entre `Gasto` e `Tag` (RF-020)."""

    gasto = models.ForeignKey(Gasto, on_delete=models.CASCADE)
    tag = models.ForeignKey("categorias.Tag", on_delete=models.CASCADE)

    class Meta:
        verbose_name = "tag do gasto"
        verbose_name_plural = "tags do gasto"
        constraints = [
            models.UniqueConstraint(fields=["gasto", "tag"], name="gastotag_unico"),
        ]

    def __str__(self):
        return f"{self.gasto_id} · {self.tag_id}"
