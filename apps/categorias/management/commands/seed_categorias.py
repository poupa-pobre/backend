"""Backfill das 12 categorias pré-definidas para usuários que ainda não as têm.

Idempotente: só cria para quem não possui nenhuma predefinida. Útil para
usuários criados antes do app `categorias` existir.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.categorias.models import CATEGORIAS_PREDEFINIDAS, Categoria


class Command(BaseCommand):
    help = "Cria as 12 categorias pré-definidas para usuários que não as têm."

    def handle(self, *args, **options):
        Usuario = get_user_model()
        criados = 0
        for usuario in Usuario.objects.all():
            if Categoria.objects.filter(usuario=usuario, predefinida=True).exists():
                continue
            Categoria.objects.bulk_create(
                [
                    Categoria(usuario=usuario, nome=nome, predefinida=True)
                    for nome in CATEGORIAS_PREDEFINIDAS
                ]
            )
            criados += 1
            self.stdout.write(f"  + {usuario.email}: 12 categorias criadas")
        self.stdout.write(
            self.style.SUCCESS(f"Concluído. {criados} usuário(s) atualizado(s).")
        )
