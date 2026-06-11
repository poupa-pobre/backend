"""
Caixa de revisão de movimentações detectadas por **notificação** (Pix).

O app Android lê a notificação do banco e manda pra cá; o backend parseia
(`pix.parsear_notificacao`) e guarda como `MovimentacaoDetectada` **pendente**.
Nada vira Receita/Gasto automaticamente — o usuário **confirma** (evita duplicar
com o OFX e lançar lixo). Ao confirmar, cria-se a Receita (recebido) ou o Gasto
(enviado) e a movimentação fica ligada a ela.
"""

from django.db import models

from apps.common.models import OwnedModel


class MovimentacaoDetectada(OwnedModel):
    class Tipo(models.TextChoices):
        RECEBIDO = "recebido", "Recebido"
        ENVIADO = "enviado", "Enviado"

    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        CONFIRMADA = "confirmada", "Confirmada"
        IGNORADA = "ignorada", "Ignorada"

    tipo = models.CharField("tipo", max_length=10, choices=Tipo.choices)
    valor = models.DecimalField(
        "valor", max_digits=12, decimal_places=2, null=True, blank=True
    )
    contraparte = models.CharField("contraparte", max_length=120, null=True, blank=True)
    banco = models.CharField("banco", max_length=60, null=True, blank=True)
    pacote = models.CharField("pacote do app", max_length=120, null=True, blank=True)
    texto_bruto = models.TextField("texto da notificação")
    status = models.CharField(
        "status", max_length=12, choices=Status.choices, default=Status.PENDENTE
    )
    # Lançamento criado na confirmação (um ou outro, conforme o tipo).
    gasto = models.ForeignKey(
        "gastos.Gasto", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    receita = models.ForeignKey(
        "receitas.Receita", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        verbose_name = "movimentação detectada"
        verbose_name_plural = "movimentações detectadas"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.tipo} R$ {self.valor} ({self.status})"
