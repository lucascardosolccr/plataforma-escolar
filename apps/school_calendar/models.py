"""Calendário escolar oficial: períodos letivos e eventos institucionais.

Até aqui o calendário só juntava datas de outros módulos (atividades,
avaliações...). Estes modelos guardam o que a escola define: bimestres,
férias, feriados, recessos, reuniões. A contagem de dias letivos sai daqui
(``services.school_days``), nunca da simples diferença entre duas datas.
"""

from django.conf import settings
from django.db import models


class CalendarPeriod(models.Model):
    class Kind(models.TextChoices):
        BIMESTRE = "bimestre", "Bimestre"
        TRIMESTRE = "trimestre", "Trimestre"
        SEMESTRE = "semestre", "Semestre"

    school = models.ForeignKey("core.School", on_delete=models.CASCADE, related_name="calendar_periods")
    school_year = models.ForeignKey("academics.SchoolYear", on_delete=models.CASCADE,
                                    related_name="periods", verbose_name="ano letivo")
    kind = models.CharField("tipo", max_length=10, choices=Kind.choices)
    name = models.CharField("nome", max_length=60, help_text="Ex.: 1º bimestre")
    start = models.DateField("início")
    end = models.DateField("término")

    class Meta:
        verbose_name = "período letivo"
        verbose_name_plural = "períodos letivos"
        ordering = ["start"]

    def __str__(self):
        return f"{self.name} ({self.start:%d/%m} a {self.end:%d/%m})"


class CalendarEvent(models.Model):
    class Kind(models.TextChoices):
        HOLIDAY = "feriado", "Feriado"
        RECESS = "recesso", "Recesso"
        VACATION = "ferias", "Férias"
        PLANNING = "planejamento", "Dia de planejamento"
        MEETING = "reuniao", "Reunião pedagógica"
        COUNCIL = "conselho", "Conselho de classe"
        EVENT = "evento", "Evento escolar"
        CLASSES_START = "inicio_aulas", "Início das aulas"
        CLASSES_END = "fim_aulas", "Término das aulas"
        RETURN = "retorno", "Retorno às aulas"
        SUSPENSION = "suspensao", "Suspensão de aulas"
        EXTRA_DAY = "letivo_extra", "Dia letivo extra (ex.: sábado letivo)"

    #: Tipos que, por padrão, não têm aula.
    NO_CLASS_KINDS = ("feriado", "recesso", "ferias", "planejamento", "suspensao")

    class Audience(models.TextChoices):
        ALL = "todos", "Toda a comunidade"
        STAFF = "equipe", "Só a equipe da escola"

    school = models.ForeignKey("core.School", on_delete=models.CASCADE, related_name="calendar_events")
    school_year = models.ForeignKey("academics.SchoolYear", on_delete=models.CASCADE, null=True, blank=True,
                                    related_name="calendar_events", verbose_name="ano letivo")
    kind = models.CharField("tipo", max_length=14, choices=Kind.choices)
    title = models.CharField("título", max_length=120)
    start = models.DateField("data")
    end = models.DateField("até", null=True, blank=True, help_text="Em branco: um dia só.")
    no_classes = models.BooleanField(
        "sem aula nestes dias", default=False,
        help_text="Marcado: os dias não contam como letivos.",
    )
    audience = models.CharField("quem vê", max_length=7, choices=Audience.choices, default=Audience.ALL)
    description = models.TextField("descrição", blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "evento do calendário"
        verbose_name_plural = "eventos do calendário"
        ordering = ["start"]

    def __str__(self):
        return f"{self.title} ({self.start:%d/%m/%Y})"

    @property
    def last_day(self):
        return self.end or self.start

    def covers(self, day):
        return self.start <= day <= self.last_day


class CalendarPublication(models.Model):
    """Marca o calendário de um ano letivo como conferido e oficial.

    Sem publicação, a plataforma não mostra contagem de dias letivos: diz
    que o calendário ainda não foi validado, em vez de inventar números.
    """

    school_year = models.OneToOneField("academics.SchoolYear", on_delete=models.CASCADE,
                                       related_name="calendar_publication")
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                     related_name="+")
    published_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "publicação do calendário"
        verbose_name_plural = "publicações do calendário"
