from django.conf import settings
from django.db import models


class MealMenu(models.Model):
    """Uma refeição do cardápio escolar num dia.

    Ingredientes e alergênicos só aparecem para a comunidade quando há o nome
    de quem os validou (nutricionista ou responsável técnico): a plataforma
    nunca inventa informação nutricional.
    """

    class Meal(models.TextChoices):
        MORNING = "lanche_manha", "Lanche da manhã"
        LUNCH = "almoco", "Almoço"
        AFTERNOON = "lanche_tarde", "Lanche da tarde"
        DINNER = "jantar", "Jantar"

    school = models.ForeignKey("core.School", on_delete=models.CASCADE, related_name="menus")
    date = models.DateField("data")
    meal = models.CharField("refeição", max_length=14, choices=Meal.choices, default=Meal.MORNING)
    description = models.TextField("o que será servido")
    ingredients = models.TextField("ingredientes", blank=True)
    allergens = models.CharField("alergênicos", max_length=300, blank=True)
    validated_by = models.CharField(
        "validado por", max_length=150, blank=True,
        help_text="Nome de quem conferiu ingredientes e alergênicos. Sem isso, eles não são exibidos.",
    )
    substitution = models.CharField(
        "substituição", max_length=300, blank=True,
        help_text="Opção para quem tem restrição alimentar, se houver.",
    )
    notes = models.CharField("observações", max_length=300, blank=True)
    changed = models.BooleanField("alteração de última hora", default=False)
    change_note = models.CharField("o que mudou", max_length=300, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "cardápio"
        verbose_name_plural = "cardápios"
        ordering = ["date", "meal"]
        constraints = [
            models.UniqueConstraint(fields=["school", "date", "meal"], name="uniq_menu_meal_per_day")
        ]

    def __str__(self):
        return f"{self.get_meal_display()} de {self.date:%d/%m/%Y}"

    @property
    def show_nutrition(self):
        return bool(self.validated_by.strip())


class ClassSchedule(models.Model):
    """Uma aula no quadro de horários semanal de uma turma."""

    WEEKDAYS = [(0, "Segunda"), (1, "Terça"), (2, "Quarta"), (3, "Quinta"), (4, "Sexta"), (5, "Sábado")]

    school = models.ForeignKey("core.School", on_delete=models.CASCADE, related_name="schedules")
    class_group = models.ForeignKey("academics.ClassGroup", on_delete=models.CASCADE, related_name="schedule",
                                    verbose_name="turma")
    weekday = models.PositiveSmallIntegerField("dia da semana", choices=WEEKDAYS)
    start_time = models.TimeField("início")
    end_time = models.TimeField("término")
    subject = models.ForeignKey("academics.Subject", on_delete=models.CASCADE, verbose_name="disciplina")
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="schedule_slots", verbose_name="professor")
    room = models.CharField("sala", max_length=40, blank=True)

    class Meta:
        verbose_name = "aula do quadro de horários"
        verbose_name_plural = "quadro de horários"
        ordering = ["weekday", "start_time"]

    def __str__(self):
        return f"{self.class_group.name} · {self.get_weekday_display()} {self.start_time:%H:%M} · {self.subject}"
