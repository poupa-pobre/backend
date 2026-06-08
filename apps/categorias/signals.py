"""Seed das 12 categorias pré-definidas a cada novo usuário (RF-021)."""

from .models import CATEGORIAS_PREDEFINIDAS, Categoria


def criar_categorias_predefinidas(sender, instance, created, **kwargs):
    if not created:
        return
    Categoria.objects.bulk_create(
        [
            Categoria(usuario=instance, nome=nome, predefinida=True)
            for nome in CATEGORIAS_PREDEFINIDAS
        ]
    )
