"""
Patrimônio líquido — RF-080, RF-081.

`Bem` são ativos de valor estimado, informados à mão (imóvel, veículo, outro).
`PatrimonioSnapshot` é a foto mensal do patrimônio (ativos − passivos), persistida
por job ao fim do mês para o gráfico de evolução (RF-081). É a **única** grandeza
derivada que armazenamos (ver CLAUDE.md › Conventions); o cálculo ao vivo (RF-080)
fica em `calculo.calcular_patrimonio`.
"""

from django.db import models

from apps.common.models import OwnedModel


class Bem(OwnedModel):
    class Tipo(models.TextChoices):
        IMOVEL = "imovel", "Imóvel"
        VEICULO = "veiculo", "Veículo"
        OUTRO = "outro", "Outro"

    descricao = models.CharField("descrição", max_length=120)
    tipo = models.CharField("tipo", max_length=20, choices=Tipo.choices)
    valor_estimado = models.DecimalField(
        "valor estimado", max_digits=12, decimal_places=2
    )

    class Meta:
        verbose_name = "bem"
        verbose_name_plural = "bens"
        ordering = ["-id"]

    def __str__(self):
        return self.descricao


class PatrimonioSnapshot(OwnedModel):
    mes_referencia = models.DateField("mês de referência")  # 1º dia do mês
    total_ativos = models.DecimalField(
        "total de ativos", max_digits=12, decimal_places=2
    )
    total_passivos = models.DecimalField(
        "total de passivos", max_digits=12, decimal_places=2
    )
    patrimonio_liquido = models.DecimalField(
        "patrimônio líquido", max_digits=12, decimal_places=2
    )

    class Meta:
        verbose_name = "snapshot de patrimônio"
        verbose_name_plural = "snapshots de patrimônio"
        ordering = ["mes_referencia"]
        constraints = [
            models.UniqueConstraint(
                fields=["usuario", "mes_referencia"],
                name="patrimonio_snapshot_unico_por_mes",
            ),
        ]

    def __str__(self):
        return f"{self.usuario} — {self.mes_referencia:%m/%Y}: R$ {self.patrimonio_liquido}"
