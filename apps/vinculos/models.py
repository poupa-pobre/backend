"""
Vínculo entre dois usuários — RF-002, RN-002.

Conexão criada por convite (`solicitante` → `destinatario`) que só passa a
valer quando o destinatário **aceita**. Não há conta compartilhada nem
hierarquia: o vínculo apenas habilita o compartilhamento item a item (cada
lançamento compartilhável referencia um vínculo aceito).
"""

from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel


class Vinculo(TimeStampedModel):
    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        ACEITO = "aceito", "Aceito"
        RECUSADO = "recusado", "Recusado"

    solicitante = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="vinculos_enviados",
        verbose_name="solicitante",
    )
    destinatario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="vinculos_recebidos",
        verbose_name="destinatário",
    )
    status = models.CharField(
        "status", max_length=10, choices=Status.choices, default=Status.PENDENTE
    )
    accepted_at = models.DateTimeField("aceito em", null=True, blank=True)

    class Meta:
        verbose_name = "vínculo"
        verbose_name_plural = "vínculos"
        ordering = ["-created_at"]
        constraints = [
            # Sem convites duplicados na mesma direção (RN-002).
            models.UniqueConstraint(
                fields=["solicitante", "destinatario"], name="vinculo_par_unico"
            ),
            # Ninguém se vincula a si mesmo.
            models.CheckConstraint(
                condition=~models.Q(solicitante=models.F("destinatario")),
                name="vinculo_sem_auto",
            ),
        ]

    def __str__(self):
        return f"{self.solicitante_id} → {self.destinatario_id} ({self.status})"

    def outro(self, usuario):
        """Retorna a outra ponta do vínculo em relação a `usuario`."""
        return self.destinatario if self.solicitante_id == usuario.id else self.solicitante
