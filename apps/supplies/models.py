"""Lista de materiais.

Uma lista por série ou turma, para um ano letivo. O professor monta (ou cola a lista que já tem) e envia para a
coordenação; a gestão confere e publica. Publicada, a lista aparece para todas as famílias da escola (o material da
série seguinte também interessa) e as famílias das turmas vinculadas recebem o aviso. Cada família marca, só para
si, o que já providenciou.
"""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models import School


class SupplyList(models.Model):
    class Status(models.TextChoices):
        DRAFT = "rascunho", "Rascunho"
        REVIEW = "revisao", "Enviada para revisão"
        PUBLISHED = "publicada", "Publicada"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="supply_lists", verbose_name="escola")
    school_year = models.ForeignKey("academics.SchoolYear", on_delete=models.CASCADE, related_name="supply_lists",
                                    verbose_name="ano letivo", help_text="O ano em que o material será usado.")
    title = models.CharField("título", max_length=120, help_text="Ex.: Lista de materiais — 2º ano")
    grade = models.CharField("ano/série", max_length=40, blank=True, help_text="Ex.: 2º ano, Maternal II.")
    class_groups = models.ManyToManyField("academics.ClassGroup", blank=True, related_name="supply_lists",
                                          verbose_name="turmas",
                                          help_text="As famílias destas turmas recebem o aviso quando a lista for "
                                                    "publicada. Turma do ano que vem ainda não criada? Publique "
                                                    "assim mesmo: a lista aparece para todas as famílias da escola.")
    intro = models.TextField("orientações", blank=True,
                             help_text="Ex.: identificar tudo com o nome; o material do ano anterior em bom estado "
                                       "pode ser reaproveitado; entregar na primeira semana de aula.")
    deliver_by = models.DateField("entregar até", null=True, blank=True)
    status = models.CharField("situação", max_length=10, choices=Status.choices, default=Status.DRAFT)
    review_note = models.CharField("observação da revisão", max_length=300, blank=True)
    #: Sobe cada vez que as famílias são avisadas (publicação ou mudança), para o aviso não se repetir.
    revision = models.PositiveSmallIntegerField(default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="+")
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "lista de materiais"
        verbose_name_plural = "listas de materiais"
        ordering = ["-school_year__name", "grade", "title"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("supplies:detail", args=[self.pk])


class SupplyItem(models.Model):
    supply_list = models.ForeignKey(SupplyList, on_delete=models.CASCADE, related_name="items")
    name = models.CharField("material", max_length=160, help_text="Ex.: caderno brochura de 96 folhas")
    quantity = models.PositiveSmallIntegerField("quantidade", default=1,
                                                validators=[MinValueValidator(1), MaxValueValidator(999)])
    unit = models.CharField("unidade", max_length=30, blank=True, help_text="Ex.: caixa, pacote, folhas. Em "
                                                                             "branco: unidades.")
    notes = models.CharField("observação", max_length=200, blank=True,
                             help_text="Ex.: sem ponta; pode ser o do ano passado. Marca só como sugestão.")
    optional = models.BooleanField("opcional", default=False)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "material"
        verbose_name_plural = "materiais"
        ordering = ["position", "pk"]

    def __str__(self):
        return self.name


class SupplyCheck(models.Model):
    """"Já tenho": anotação da família, só para ela. A escola não usa para cobrar ninguém."""

    item = models.ForeignKey(SupplyItem, on_delete=models.CASCADE, related_name="checks")
    student = models.ForeignKey("registry.Student", on_delete=models.CASCADE, related_name="+")
    checked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["item", "student"], name="uniq_supply_check")]
