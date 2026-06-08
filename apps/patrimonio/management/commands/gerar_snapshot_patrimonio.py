"""
RF-081: persiste a foto mensal do patrimônio de cada usuário. Idempotente
(`UNIQUE(usuario, mes_referencia)` + update_or_create), pensado para rodar via
cron ao fim do mês.

Uso: `python manage.py gerar_snapshot_patrimonio [--mes AAAA-MM-01]`
(sem `--mes`, usa o 1º dia do mês corrente).
"""

from datetime import datetime

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.patrimonio.calculo import calcular_patrimonio
from apps.patrimonio.models import PatrimonioSnapshot

Usuario = get_user_model()


class Command(BaseCommand):
    help = "Persiste o snapshot mensal do patrimônio de cada usuário (RF-081)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--mes",
            help="Mês de referência (AAAA-MM-01). Padrão: mês corrente.",
        )

    def handle(self, *args, **options):
        if options.get("mes"):
            try:
                mes = datetime.strptime(options["mes"], "%Y-%m-%d").date().replace(day=1)
            except ValueError as exc:
                raise CommandError("Use o formato AAAA-MM-01 em --mes.") from exc
        else:
            mes = timezone.localdate().replace(day=1)

        total = 0
        for usuario in Usuario.objects.all():
            dados = calcular_patrimonio(usuario, mes)
            PatrimonioSnapshot.objects.update_or_create(
                usuario=usuario,
                mes_referencia=mes,
                defaults={
                    "total_ativos": dados["total_ativos"],
                    "total_passivos": dados["total_passivos"],
                    "patrimonio_liquido": dados["patrimonio_liquido"],
                },
            )
            total += 1

        self.stdout.write(
            self.style.SUCCESS(f"{mes:%m/%Y}: snapshot de {total} usuário(s).")
        )
