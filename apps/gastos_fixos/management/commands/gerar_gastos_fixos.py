"""
RN-030: pré-cria as instâncias mensais (`pendente`) de todos os gastos fixos
ativos. Idempotente (`UNIQUE(gasto_fixo, mes_referencia)` + get_or_create).

Uso: `python manage.py gerar_gastos_fixos [--mes AAAA-MM-01]`
(sem `--mes`, usa o 1º dia do mês corrente). Pensado para rodar via cron mensal.
"""

from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.gastos_fixos.models import GastoFixo


class Command(BaseCommand):
    help = "Pré-cria as instâncias mensais dos gastos fixos ativos (RN-030)."

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

        criados = 0
        ativos = GastoFixo.objects.filter(ativo=True)
        for gasto_fixo in ativos:
            _, created = gasto_fixo.mensais.get_or_create(mes_referencia=mes)
            criados += int(created)

        self.stdout.write(
            self.style.SUCCESS(
                f"{mes:%m/%Y}: {criados} criado(s), "
                f"{ativos.count() - criados} já existente(s)."
            )
        )
