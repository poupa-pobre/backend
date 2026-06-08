"""
Metas de economia — RF-060, RF-061, RN-060.

`Meta` é o objetivo de poupança do dono (valor alvo, opcionalmente com data alvo
e contribuição mensal planejada). `AporteMeta` é cada contribuição registrada;
ao criar um aporte o sistema **incrementa** o `valor_atual` da meta (RF-061).

O progresso (RN-060) — percentual, quanto falta e se o ritmo de aportes basta
para a data alvo — é derivado em consulta (ver `progresso()`).
"""

from decimal import Decimal

from django.db import models

from apps.common.models import OwnedModel, TimeStampedModel


def _meses_entre(inicio, fim):
    """Número de meses cheios de `inicio` até `fim` (>= 0)."""
    meses = (fim.year - inicio.year) * 12 + (fim.month - inicio.month)
    return max(meses, 0)


class Meta(OwnedModel):
    nome = models.CharField("nome", max_length=100)
    cor = models.CharField("cor", max_length=7, null=True, blank=True)  # #RRGGBB
    emoji = models.CharField("emoji", max_length=8, null=True, blank=True)
    valor_alvo = models.DecimalField("valor alvo", max_digits=12, decimal_places=2)
    valor_atual = models.DecimalField(
        "valor atual", max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    data_alvo = models.DateField("data alvo", null=True, blank=True)
    contribuicao_mensal_planejada = models.DecimalField(
        "contribuição mensal planejada",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "meta"
        verbose_name_plural = "metas"
        ordering = ["-id"]

    def __str__(self):
        return self.nome

    # --- Progresso (RN-060), derivado em consulta ---

    def progresso(self, hoje=None):
        """
        RN-060: percentual concluído, quanto falta e — havendo data alvo — se o
        ritmo de aportes é suficiente para atingi-la no prazo.

        O ritmo de referência é a `contribuicao_mensal_planejada` quando
        informada; senão, a média mensal dos aportes já feitos.
        """
        from django.utils import timezone

        hoje = hoje or timezone.localdate()
        alvo = self.valor_alvo or Decimal("0.00")
        atual = self.valor_atual or Decimal("0.00")

        percentual = (atual / alvo * 100) if alvo else Decimal("0.00")
        percentual = percentual.quantize(Decimal("0.01"))
        restante = max(alvo - atual, Decimal("0.00"))
        concluida = restante <= 0

        meses_restantes = None
        aporte_mensal_necessario = None
        no_ritmo = None
        if self.data_alvo and not concluida:
            meses_restantes = _meses_entre(hoje, self.data_alvo)
            if meses_restantes > 0:
                aporte_mensal_necessario = (restante / meses_restantes).quantize(
                    Decimal("0.01")
                )
                ritmo = self.contribuicao_mensal_planejada or self._ritmo_aportes(hoje)
                no_ritmo = ritmo >= aporte_mensal_necessario
            else:
                # Prazo esgotado e meta não atingida.
                aporte_mensal_necessario = restante
                no_ritmo = False

        return {
            "percentual_concluido": percentual,
            "valor_restante": restante,
            "concluida": concluida,
            "meses_restantes": meses_restantes,
            "aporte_mensal_necessario": aporte_mensal_necessario,
            "no_ritmo": no_ritmo,
        }

    def _ritmo_aportes(self, hoje):
        """Média mensal dos aportes desde o primeiro registrado."""
        primeiro = self.aportes.order_by("data").first()
        if primeiro is None:
            return Decimal("0.00")
        total = self.aportes.aggregate(t=models.Sum("valor"))["t"] or Decimal("0.00")
        meses = _meses_entre(primeiro.data, hoje) + 1  # inclui o mês corrente
        return (total / meses).quantize(Decimal("0.01"))


class AporteMeta(TimeStampedModel):
    meta = models.ForeignKey(
        Meta,
        on_delete=models.CASCADE,
        related_name="aportes",
        verbose_name="meta",
    )
    valor = models.DecimalField("valor", max_digits=12, decimal_places=2)
    data = models.DateField("data")
    observacao = models.CharField(
        "observação", max_length=255, null=True, blank=True
    )

    class Meta:
        verbose_name = "aporte de meta"
        verbose_name_plural = "aportes de meta"
        ordering = ["-data", "-id"]

    def __str__(self):
        return f"{self.meta.nome} — R$ {self.valor}"
