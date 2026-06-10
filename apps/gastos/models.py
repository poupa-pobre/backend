"""
Gastos do dia a dia — RF-020, RN-020, RN-021.

`Gasto` é o lançamento variável do usuário (quem gastou é o dono). No crédito,
o `cartao` é obrigatório e o `mes_referencia` segue a **competência** pelo dia
de fechamento (RN-040, via `Cartao.competencia_de`); nas demais formas, é o 1º
dia do mês da `data`. Pode ser **compartilhado** com um vínculo aceito, rateando
`valor_dono + valor_vinculado = valor` (RN-021) — sem duplicar o item.

Tags são N:M via `GastoTag`. O detalhamento por scanner (`CompraDetalhada`,
`ItemCompra`) — RF-022..025 — é o cupom escaneado/manual aninhado num `Gasto`:
um único `Gasto` carrega a lista de itens (RN-023). O parsing do texto do OCR
em itens vive em `parser.py` (a action `parsear-cupom` só faz preview).
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


class CompraDetalhada(models.Model):
    """Detalhamento de um `Gasto` em itens (RF-022/023). 1:1 com o gasto: o gasto
    guarda o total e a categoria geral; aqui ficam o estabelecimento, a origem
    (manual/QR/OCR) e a `url_nfce` da identidade da nota (RN-024)."""

    gasto = models.OneToOneField(
        Gasto,
        on_delete=models.CASCADE,
        related_name="compra_detalhada",
        verbose_name="gasto",
    )
    estabelecimento = models.CharField(
        "estabelecimento", max_length=120, null=True, blank=True
    )
    origem = models.CharField(
        "origem", max_length=10, choices=Gasto.Origem.choices, default=Gasto.Origem.MANUAL
    )
    url_nfce = models.URLField("URL da NFC-e", max_length=500, null=True, blank=True)

    class Meta:
        verbose_name = "compra detalhada"
        verbose_name_plural = "compras detalhadas"

    def __str__(self):
        return f"Compra #{self.gasto_id} — {self.estabelecimento or 'sem nome'}"


class ItemCompra(models.Model):
    """Item de uma `CompraDetalhada`. `identificado=False` marca o que o OCR não
    leu com confiança, para a pessoa revisar antes de salvar."""

    compra = models.ForeignKey(
        CompraDetalhada,
        on_delete=models.CASCADE,
        related_name="itens",
        verbose_name="compra",
    )
    nome = models.CharField("nome", max_length=120)
    codigo = models.CharField("código", max_length=40, null=True, blank=True)
    quantidade = models.DecimalField(
        "quantidade", max_digits=10, decimal_places=3, null=True, blank=True
    )
    unidade = models.CharField("unidade", max_length=10, null=True, blank=True)
    valor_unitario = models.DecimalField(
        "valor unitário", max_digits=12, decimal_places=2, null=True, blank=True
    )
    valor = models.DecimalField("valor", max_digits=12, decimal_places=2)
    categoria = models.ForeignKey(
        "categorias.Categoria",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="itens_compra",
        verbose_name="categoria",
    )
    identificado = models.BooleanField("identificado", default=True)

    class Meta:
        verbose_name = "item de compra"
        verbose_name_plural = "itens de compra"
        ordering = ["id"]

    def __str__(self):
        return f"{self.nome} — R$ {self.valor}"


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
