from django.conf import settings
from django.db import models


class CoordinatorAssignment(models.Model):
    """O que um coordenador pedagógico acompanha, definido pela direção.

    O alcance é a união de: turmas designadas (todas as disciplinas), os
    pares turma+disciplina dos professores designados e as disciplinas
    designadas (em todas as turmas). "Escola toda" dispensa a lista.
    Sem designação vigente, o coordenador não vê dados de estudantes.
    """

    school = models.ForeignKey("core.School", on_delete=models.CASCADE, related_name="coordinator_assignments")
    coordinator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                    related_name="coordination_assignments", verbose_name="coordenador",
                                    limit_choices_to={"role": "coordenacao"})
    area = models.CharField("área de atuação", max_length=120, blank=True,
                            help_text="Ex.: Anos iniciais; Linguagens.")
    all_school = models.BooleanField("escola toda", default=False)
    class_groups = models.ManyToManyField("academics.ClassGroup", blank=True, verbose_name="turmas acompanhadas")
    subjects = models.ManyToManyField("academics.Subject", blank=True, verbose_name="disciplinas acompanhadas")
    teachers = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="coordinated_by",
                                      verbose_name="professores acompanhados",
                                      limit_choices_to={"role": "professor"})
    starts_on = models.DateField("início")
    ends_on = models.DateField("término", null=True, blank=True)
    notes = models.CharField("observações", max_length=300, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                   related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "designação de coordenação"
        verbose_name_plural = "designações de coordenação"
        ordering = ["-starts_on"]

    def __str__(self):
        return f"{self.coordinator} · {self.area or ('escola toda' if self.all_school else 'designação')}"


class CoordinationRecord(models.Model):
    """Registro da coordenação: orientação a professor, reunião, acompanhamento
    de planejamento ou de calendário. Interno da equipe: nunca vai à família."""

    class Kind(models.TextChoices):
        GUIDANCE = "orientacao", "Orientação pedagógica"
        MEETING = "reuniao", "Reunião"
        PLANNING = "planejamento", "Acompanhamento do planejamento"
        CALENDAR = "calendario", "Acompanhamento do calendário"
        FOLLOW_UP = "acompanhamento", "Acompanhamento de estudante/turma"

    school = models.ForeignKey("core.School", on_delete=models.CASCADE, related_name="coordination_records")
    kind = models.CharField("tipo", max_length=15, choices=Kind.choices)
    date = models.DateField("data")
    title = models.CharField("assunto", max_length=150)
    notes = models.TextField("registro")
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="coordination_notes", verbose_name="professor",
                                limit_choices_to={"role": "professor"})
    class_group = models.ForeignKey("academics.ClassGroup", on_delete=models.SET_NULL, null=True, blank=True,
                                    verbose_name="turma")
    participants = models.CharField("participantes", max_length=300, blank=True)
    follow_up_on = models.DateField("retomar em", null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "registro da coordenação"
        verbose_name_plural = "registros da coordenação"
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.title} ({self.date:%d/%m/%Y})"
