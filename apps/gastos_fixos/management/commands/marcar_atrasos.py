"""
RN-032: marca como `atrasado` todo gasto fixo mensal `pendente` cujo dia de
vencimento já passou. Pensado para rodar via cron diário. (A notificação em si
é do módulo de Notificações, Fase 5.)

Uso: `python manage.py marcar_atrasos`
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.gastos_fixos.models import GastoFixoMensal


class Command(BaseCommand):
    help = "Marca gastos fixos mensais vencidos sem check como atrasados (RN-032)."

    def handle(self, *args, **options):
        hoje = timezone.localdate()
        pendentes = GastoFixoMensal.objects.filter(
            status=GastoFixoMensal.Status.PENDENTE
        ).select_related("gasto_fixo")
        atrasados = 0
        for mensal in pendentes:
            if mensal.esta_atrasado(hoje):
                mensal.status = GastoFixoMensal.Status.ATRASADO
                mensal.save(update_fields=["status", "updated_at"])
                atrasados += 1

        self.stdout.write(self.style.SUCCESS(f"{atrasados} marcado(s) como atrasado."))
