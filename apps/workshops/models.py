"""Oficinas, projetos e atividades de contraturno com vagas limitadas. A família inscreve o filho; com as vagas
cheias, ele entra na lista de espera e é chamado sozinho quando alguém desiste (na ordem de inscrição)."""

from django.conf import settings
from django.db import models

from apps.core.models import School


class Workshop(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="workshops")
    title = models.CharField("nome", max_length=120, help_text="Ex.: Oficina de robótica; Coral; Xadrez.")
    description = models.TextField("sobre a atividade", help_text="O que vão fazer, o que levar, para quem é.")
    schedule = models.CharField("dias e horário", max_length=150, help_text="Ex.: terças e quintas, 14h às 15h30.")
    place = models.CharField("local", max_length=120, blank=True)
    starts_on = models.DateField("começa em")
    ends_on = models.DateField("termina em")
    capacity = models.PositiveSmallIntegerField("vagas")
    class_groups = models.ManyToManyField("academics.ClassGroup", blank=True, related_name="workshops",
                                          verbose_name="turmas que podem se inscrever",
                                          help_text="Em branco: todas as turmas do ano letivo.")
    signup_until = models.DateField("inscrições até")
    organizer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                  related_name="workshops", verbose_name="responsável")
    published_at = models.DateTimeField(null=True, blank=True)
    closed = models.BooleanField("inscrições encerradas", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-starts_on", "title"]
        verbose_name = "oficina"
        verbose_name_plural = "oficinas"

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("workshops:detail", args=[self.pk])

    def accepts(self, today):
        return bool(self.published_at) and not self.closed and today <= self.signup_until and today <= self.ends_on


class Signup(models.Model):
    class Status(models.TextChoices):
        CONFIRMED = "inscrito", "Inscrito"
        WAITING = "espera", "Na lista de espera"
        CANCELED = "cancelado", "Cancelado"

    workshop = models.ForeignKey(Workshop, on_delete=models.CASCADE, related_name="signups")
    student = models.ForeignKey("registry.Student", on_delete=models.CASCADE, related_name="workshop_signups",
                                verbose_name="estudante")
    status = models.CharField("situação", max_length=10, choices=Status.choices)
    queued_at = models.DateTimeField("inscrito em")
    signed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    canceled_at = models.DateTimeField(null=True, blank=True)
    canceled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+")
    cancel_note = models.CharField("motivo", max_length=200, blank=True)

    class Meta:
        ordering = ["queued_at", "pk"]
        verbose_name = "inscrição em oficina"
        verbose_name_plural = "inscrições em oficinas"
        constraints = [models.UniqueConstraint(fields=["workshop", "student"], name="uniq_workshop_signup")]

    def __str__(self):
        return f"{self.student} em {self.workshop}: {self.get_status_display()}"
