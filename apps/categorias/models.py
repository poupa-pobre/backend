"""
Categorização por usuário — RF-021.

Cada usuário tem o seu conjunto: 12 categorias **pré-definidas** (não
excluíveis, apenas renomeáveis) + até 10 **customizadas**. Subcategorias são
livres dentro de uma categoria; tags são rótulos soltos do usuário.

Exclusão de categoria é **soft delete** (`ativa = False`) para não quebrar
lançamentos antigos — predefinidas nunca são excluídas.
"""

from django.db import models

from apps.common.models import OwnedModel, TimeStampedModel

# As 12 categorias fixas (RF-021), criadas para cada novo usuário.
CATEGORIAS_PREDEFINIDAS = [
    "Moradia",
    "Alimentação",
    "Transporte",
    "Saúde",
    "Educação",
    "Lazer",
    "Vestuário",
    "Assinaturas",
    "Comunicação",
    "Pets",
    "Beleza",
    "Impostos e taxas",
]

MAX_CATEGORIAS_CUSTOMIZADAS = 10


class Categoria(OwnedModel):
    nome = models.CharField("nome", max_length=60)
    cor = models.CharField("cor", max_length=7, null=True, blank=True)  # #RRGGBB
    icone = models.CharField("ícone", max_length=40, null=True, blank=True)
    predefinida = models.BooleanField("predefinida", default=False)
    ativa = models.BooleanField("ativa", default=True)  # soft delete

    class Meta:
        verbose_name = "categoria"
        verbose_name_plural = "categorias"
        ordering = ["-predefinida", "nome"]

    def __str__(self):
        return self.nome


class Subcategoria(TimeStampedModel):
    categoria = models.ForeignKey(
        Categoria,
        on_delete=models.CASCADE,
        related_name="subcategorias",
        verbose_name="categoria",
    )
    nome = models.CharField("nome", max_length=60)

    class Meta:
        verbose_name = "subcategoria"
        verbose_name_plural = "subcategorias"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class Tag(OwnedModel):
    nome = models.CharField("nome", max_length=40)

    class Meta:
        verbose_name = "tag"
        verbose_name_plural = "tags"
        ordering = ["nome"]

    def __str__(self):
        return self.nome
