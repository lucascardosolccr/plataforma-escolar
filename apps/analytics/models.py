"""Metas da escola: um indicador já calculado pelos painéis, um valor-alvo e um prazo.

O resultado nunca é digitado: é recalculado a cada consulta com as mesmas fórmulas do
painel institucional (``goals.progress``), do início da meta até hoje (ou até o prazo).
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


class SchoolGoal(models.Model):
    class Indicator(models.TextChoices):
        ATTENDANCE = "frequencia", "Frequência média (%)"
        AVERAGE = "media_geral", "Média geral dos estudantes"
        DELIVERY = "entregas", "Atividades de casa entregues (%)"
        SKILLS = "habilidades", "Habilidades consolidadas ou em consolidação (%)"

    school = models.ForeignKey("core.School", on_delete=models.CASCADE, related_name="goals")
    title = models.CharField("título", max_length=160, blank=True,
                             help_text="Em branco: usa o nome do indicador.")
    indicator = models.CharField("indicador", max_length=12, choices=Indicator.choices)
    class_group = models.ForeignKey("academics.ClassGroup", on_delete=models.CASCADE, null=True, blank=True,
                                    verbose_name="turma", help_text="Em branco: a escola toda.")
    target = models.DecimalField("valor-alvo", max_digits=6, decimal_places=2)
    starts_on = models.DateField("início", default=timezone.localdate)
    deadline = models.DateField("prazo")
    notes = models.TextField("como a escola pretende chegar lá", blank=True)
    active = models.BooleanField("ativa", default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["deadline", "pk"]
        verbose_name = "meta da escola"
        verbose_name_plural = "metas da escola"

    def __str__(self):
        return self.label

    @property
    def label(self):
        return self.title or self.get_indicator_display()
