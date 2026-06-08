"""
Receitas / renda do usuário — RF-010, RF-011, RN-010, RN-011.

`Receita` é a entrada de renda do dono. O `mes_referencia` é o 1º dia do mês
da `data_prevista`. O **status** é derivado: `recebida` quando `data_real` está
preenchida, senão `prevista` (RF-011). Pode ser **compartilhada** com um vínculo
aceito, rateando `valor_dono + valor_vinculado = valor` (RN-021/§1) — sem
duplicar o item. Recorrentes pré-criam a receita do mês seguinte (RN-011); o
gatilho de cobertura ao receber salário vive na view (RN-010).
"""

from django.db import models

from apps.common.models import OwnedModel


class Receita(OwnedModel):
    class Tipo(models.TextChoices):
        SALARIO = "salario", "Salário"
        FREELANCE = "freelance", "Freelance"
        ALUGUEL = "aluguel", "Aluguel"
        BONUS = "bonus", "Bônus"
        OUTRO = "outro", "Outro"

    class Status(models.TextChoices):
        PREVISTA = "prevista", "Prevista"
        RECEBIDA = "recebida", "Recebida"

    descricao = models.CharField("descrição", max_length=120)
    valor = models.DecimalField("valor", max_digits=12, decimal_places=2)
    data_prevista = models.DateField("data prevista")
    data_real = models.DateField("data real", null=True, blank=True)
    tipo = models.CharField("tipo", max_length=20, choices=Tipo.choices)
    recorrente = models.BooleanField("recorrente", default=False)
    # Compartilhamento (ver CLAUDE.md › Conventions e modelo-de-dados §1).
    compartilhada = models.BooleanField("compartilhada", default=False)
    vinculo = models.ForeignKey(
        "vinculos.Vinculo",
        on_delete=models.SET_NULL,  # RN-002: desfazer vínculo não apaga a receita
        null=True,
        blank=True,
        related_name="receitas",
        verbose_name="vínculo",
    )
    valor_dono = models.DecimalField(
        "valor do dono", max_digits=12, decimal_places=2, null=True, blank=True
    )
    valor_vinculado = models.DecimalField(
        "valor do vinculado", max_digits=12, decimal_places=2, null=True, blank=True
    )
    mes_referencia = models.DateField("mês de referência")  # 1º dia do mês

    class Meta:
        verbose_name = "receita"
        verbose_name_plural = "receitas"
        ordering = ["-data_prevista", "-id"]

    def __str__(self):
        return f"{self.descricao} — R$ {self.valor}"

    @property
    def status(self):
        """RF-011: derivado de `data_real`."""
        return self.Status.RECEBIDA if self.data_real else self.Status.PREVISTA

    @property
    def porcao_dono(self):
        """Parte que entra no saldo do dono: rateio se compartilhada, senão total."""
        if self.compartilhada and self.valor_dono is not None:
            return self.valor_dono
        return self.valor

    def save(self, *args, **kwargs):
        self.mes_referencia = self.data_prevista.replace(day=1)
        super().save(*args, **kwargs)

    def proximo_mes(self):
        """1º dia do mês seguinte à `data_prevista` desta receita."""
        d = self.data_prevista
        ano, mes = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
        return d.replace(year=ano, month=mes, day=1)

    def criar_recorrencia(self):
        """
        RN-011: pré-cria a mesma receita para o mês seguinte com status
        **prevista** (sem `data_real`), copiando os demais campos. Idempotente:
        não duplica se já existir a recorrência daquele mês. A cópia não dispara
        nova recorrência (a cadeia avança um mês por vez, ao receber/cadastrar).
        """
        if not self.recorrente:
            return None
        prox = self.proximo_mes()
        existente = Receita.objects.filter(
            usuario=self.usuario,
            descricao=self.descricao,
            tipo=self.tipo,
            recorrente=True,
            mes_referencia=prox,
        ).first()
        if existente:
            return existente
        data_prevista = self.data_prevista.replace(
            year=prox.year, month=prox.month, day=min(self.data_prevista.day, 28)
        )
        return Receita.objects.create(
            usuario=self.usuario,
            descricao=self.descricao,
            valor=self.valor,
            data_prevista=data_prevista,
            data_real=None,
            tipo=self.tipo,
            recorrente=True,
            compartilhada=self.compartilhada,
            vinculo=self.vinculo,
            valor_dono=self.valor_dono,
            valor_vinculado=self.valor_vinculado,
        )
