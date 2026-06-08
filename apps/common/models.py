"""
Modelos base reutilizados por todos os apps.

- `TimeStampedModel`: carimba `created_at`/`updated_at`.
- `OwnedModel`: adiciona o FK `usuario` (dono) e um manager que filtra
  toda query pelo dono — base do scoping descrito em CLAUDE.md › Conventions.

O compartilhamento entre usuários acontece **apenas** via `Vinculo` (app
`vinculos`, Fase 1): a entrada nunca é duplicada, ela referencia o vínculo e
fica visível (somente leitura) para a outra parte. Por isso o filtro padrão é
só pelo dono; a visibilidade compartilhada é resolvida nas consultas dos apps.
"""

from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    """Mixin abstrato com timestamps de criação e atualização."""

    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        abstract = True


class OwnedQuerySet(models.QuerySet):
    def do_usuario(self, usuario):
        """Restringe a query às linhas cujo dono é `usuario`."""
        return self.filter(usuario=usuario)


class OwnedManager(models.Manager.from_queryset(OwnedQuerySet)):
    pass


class OwnedModel(TimeStampedModel):
    """
    Base para entidades privadas: pertencem a um `usuario` e são sempre
    filtradas por ele. Use `Modelo.objects.do_usuario(request.user)`.
    """

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="%(class)ss",
        verbose_name="dono",
    )

    objects = OwnedManager()

    class Meta:
        abstract = True
