"""Carteirinha do estudante e registro de entrada e saída na portaria."""

import datetime

from django.conf import settings
from django.db import models

from apps.core.models import School


class GateSettings(models.Model):
    """Horário de entrada por turno, definido pela direção, e o que a portaria faz ao registrar a chegada."""

    school = models.OneToOneField(School, on_delete=models.CASCADE, related_name="gate_settings")
    entry_morning = models.TimeField("entrada do turno da manhã", default=datetime.time(7, 30))
    entry_afternoon = models.TimeField("entrada do turno da tarde", default=datetime.time(13, 0))
    entry_full = models.TimeField("entrada do turno integral", default=datetime.time(7, 30))
    entry_night = models.TimeField("entrada do turno da noite", default=datetime.time(19, 0))
    tolerance = models.PositiveSmallIntegerField(
        "tolerância de atraso (minutos)", default=10,
        help_text="Depois do horário de entrada mais esta tolerância, a chegada é registrada como atraso.")
    fill_attendance = models.BooleanField(
        "registrar a chegada na chamada do dia", default=True,
        help_text="Marca presente (ou atraso) na chamada da turma se o professor ainda não registrou. Uma falta já "
                  "lançada vira atraso, porque o estudante chegou. Presença marcada pelo professor não muda.")
    notify_missing_after = models.PositiveSmallIntegerField(
        "avisar a família se não houver entrada até (minutos depois do horário)", null=True, blank=True,
        help_text="Em branco, não avisa. Ligue só se TODA entrada passar pela leitura da carteirinha: senão a "
                  "família recebe aviso de que o filho não chegou quando ele chegou. Quem já tem presença na "
                  "chamada ou falta justificada para o dia não gera aviso.")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "configuração da portaria"
        verbose_name_plural = "configurações da portaria"

    TURN_FIELDS = {"manha": "entry_morning", "tarde": "entry_afternoon", "integral": "entry_full",
                   "noite": "entry_night"}

    @classmethod
    def for_school(cls, school):
        return cls.objects.filter(school=school).first() or cls(school=school)

    def entry_for(self, turn):
        return getattr(self, self.TURN_FIELDS.get(turn, "entry_morning"))


class StudentCard(models.Model):
    """Carteirinha: um código único (também no código de barras) e um QR Code assinado.

    Segunda via cancela a anterior: o código antigo passa a ser recusado e a tentativa fica registrada."""

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="student_cards")
    student = models.ForeignKey("registry.Student", on_delete=models.CASCADE, related_name="cards",
                                verbose_name="estudante")
    code = models.CharField("código único", max_length=12, unique=True)
    issued_at = models.DateTimeField("emitida em", auto_now_add=True)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                  related_name="+")
    valid_until = models.DateField("válida até")
    revoked_at = models.DateTimeField("cancelada em", null=True, blank=True)
    revoked_reason = models.CharField("motivo do cancelamento", max_length=200, blank=True)

    class Meta:
        ordering = ["-issued_at"]
        verbose_name = "carteirinha"
        verbose_name_plural = "carteirinhas"

    def __str__(self):
        return f"{self.student} · {self.display_code}"

    @property
    def active(self):
        return self.revoked_at is None

    @property
    def display_code(self):
        return f"{self.code[:4]}-{self.code[4:8]}-{self.code[8:]}"


class GateEvent(models.Model):
    """Entrada ou saída registrada na portaria (uma de cada por estudante e dia)."""

    class Kind(models.TextChoices):
        ENTRY = "entrada", "Entrada"
        EXIT = "saida", "Saída"

    class Method(models.TextChoices):
        QR = "qr", "QR Code"
        BARCODE = "barras", "Código de barras"
        CODE = "codigo", "Código digitado"
        MANUAL = "manual", "Registro manual (sem carteirinha)"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="gate_events")
    student = models.ForeignKey("registry.Student", on_delete=models.CASCADE, related_name="gate_events",
                                verbose_name="estudante")
    card = models.ForeignKey(StudentCard, on_delete=models.SET_NULL, null=True, blank=True, related_name="events")
    class_group = models.ForeignKey("academics.ClassGroup", on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+")
    kind = models.CharField("tipo", max_length=8, choices=Kind.choices)
    method = models.CharField("forma de identificação", max_length=8, choices=Method.choices)
    day = models.DateField("dia", db_index=True)
    at = models.DateTimeField("horário")
    expected = models.TimeField("horário de entrada do turno", null=True, blank=True)
    late = models.BooleanField("atraso", default=False)
    minutes_late = models.PositiveSmallIntegerField("minutos de atraso", null=True, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                    related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-at"]
        verbose_name = "registro de portaria"
        verbose_name_plural = "registros de portaria"
        constraints = [models.UniqueConstraint(fields=["student", "day", "kind"], name="uniq_gate_event_per_day")]
