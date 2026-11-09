"""Reserva de espaços e equipamentos (sala de informática, quadra, laboratório, projetor...).

Cada recurso é uma unidade: três projetores são três recursos, cada um com a sua agenda. Duas reservas ativas do
mesmo recurso não se sobrepõem no mesmo dia (conferido ao salvar, dentro de uma transação).
"""

from django.conf import settings
from django.db import models

from apps.core.models import School


class Resource(models.Model):
    class Kind(models.TextChoices):
        SPACE = "espaco", "Espaço"
        EQUIPMENT = "equipamento", "Equipamento"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="booking_resources")
    name = models.CharField("nome", max_length=80, help_text="Ex.: Sala de informática, Quadra, Projetor 1.")
    kind = models.CharField("tipo", max_length=12, choices=Kind.choices, default=Kind.SPACE)
    notes = models.CharField("observações", max_length=200, blank=True,
                             help_text="Onde fica, capacidade, como retirar o equipamento.")
    active = models.BooleanField("disponível para reserva", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["kind", "name"]
        verbose_name = "espaço ou equipamento"
        verbose_name_plural = "espaços e equipamentos"
        constraints = [models.UniqueConstraint(fields=["school", "name"], name="uniq_booking_resource_name")]

    def __str__(self):
        return self.name


class Booking(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="bookings")
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name="bookings",
                                 verbose_name="espaço ou equipamento")
    day = models.DateField("dia")
    start = models.TimeField("início")
    end = models.TimeField("fim")
    class_group = models.ForeignKey("academics.ClassGroup", on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+", verbose_name="turma (opcional)")
    purpose = models.CharField("para quê", max_length=150, blank=True)
    booked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    canceled_at = models.DateTimeField(null=True, blank=True)
    canceled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+")

    class Meta:
        ordering = ["day", "start"]
        verbose_name = "reserva"
        verbose_name_plural = "reservas"
        indexes = [models.Index(fields=["resource", "day"])]

    def __str__(self):
        return f"{self.resource} · {self.day:%d/%m} {self.start:%H:%M}–{self.end:%H:%M}"

    @property
    def active(self):
        return self.canceled_at is None
