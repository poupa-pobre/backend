"""
Investimentos — RF-070, RF-071 (Fase 1: só aportes, sem cálculo de rendimento).

Cada `Investimento` é um **aporte** do dono. A visão consolidada (total por tipo,
total geral e histórico por mês — RF-071) é derivada em consulta, na view.
"""

from django.db import models

from apps.common.models import OwnedModel


class Investimento(OwnedModel):
    class Tipo(models.TextChoices):
        RENDA_FIXA = "renda_fixa", "Renda fixa"
        ACOES = "acoes", "Ações"
        FIIS = "fiis", "FIIs"
        CRIPTO = "cripto", "Cripto"
        TESOURO = "tesouro", "Tesouro"
        POUPANCA = "poupanca", "Poupança"
        OUTRO = "outro", "Outro"

    tipo = models.CharField("tipo", max_length=20, choices=Tipo.choices)
    instituicao = models.CharField(
        "instituição", max_length=80, null=True, blank=True
    )
    descricao = models.CharField(
        "descrição", max_length=120, null=True, blank=True
    )
    valor_aportado = models.DecimalField(
        "valor aportado", max_digits=12, decimal_places=2
    )
    data_aporte = models.DateField("data do aporte")

    class Meta:
        verbose_name = "investimento"
        verbose_name_plural = "investimentos"
        ordering = ["-data_aporte", "-id"]

    def __str__(self):
        return f"{self.get_tipo_display()} — R$ {self.valor_aportado}"
