"""Reuniões e atendimentos (Prompt 9 §8.9; Prompt 2 §6, "registro de reuniões
e encaminhamentos").

Antes, a única forma de pedir uma conversa era a solicitação "Solicitar
reunião/contato", e o que se combinava na reunião não ficava em lugar nenhum.
Aqui a reunião tem data, pauta, participantes, o registro do que foi
conversado e os encaminhamentos, cada um com responsável e prazo.

Dois textos, duas audiências: ``summary`` é o registro compartilhado com
todos os participantes (inclusive a família); ``confidential_notes`` é só da
equipe (ver ``access.can_view_confidential``).
"""

from django.db import models
from django.utils import timezone

from apps.academics.models import ClassGroup
from apps.core.models import School, User
from apps.registry.models import Student


class Meeting(models.Model):
    class Kind(models.TextChoices):
        FAMILY = "familia", "Reunião com a família"
        SERVICE = "atendimento", "Atendimento individual"
        COUNCIL = "conselho", "Conselho de classe"
        PEDAGOGICAL = "pedagogica", "Reunião pedagógica"
        OTHER = "outra", "Outra"

    class Status(models.TextChoices):
        SCHEDULED = "agendada", "Agendada"
        DONE = "realizada", "Realizada"
        CANCELED = "cancelada", "Cancelada"

    school = models.ForeignKey(School, on_delete=models.CASCADE, verbose_name="escola")
    kind = models.CharField("tipo", max_length=12, choices=Kind.choices, default=Kind.FAMILY)
    title = models.CharField("assunto", max_length=200)
    student = models.ForeignKey(
        Student, on_delete=models.PROTECT, null=True, blank=True, related_name="meetings",
        verbose_name="estudante",
        help_text="Opcional. Com estudante, os responsáveis dele podem ser convidados.",
    )
    class_group = models.ForeignKey(
        ClassGroup, on_delete=models.PROTECT, null=True, blank=True, related_name="meetings",
        verbose_name="turma",
    )
    scheduled_at = models.DateTimeField("data e hora")
    duration_minutes = models.PositiveSmallIntegerField("duração (minutos)", null=True, blank=True)
    location = models.CharField(
        "local ou forma", max_length=200, blank=True,
        help_text="Ex.: sala da coordenação, chamada de vídeo, telefone.",
    )
    agenda = models.TextField("pauta", blank=True)
    status = models.CharField("situação", max_length=10, choices=Status.choices, default=Status.SCHEDULED)
    cancel_reason = models.CharField("motivo do cancelamento", max_length=255, blank=True)
    summary = models.TextField(
        "registro da reunião", blank=True,
        help_text="O que foi conversado e combinado. Todos os participantes veem, inclusive a família.",
    )
    confidential_notes = models.TextField(
        "anotações da equipe", blank=True,
        help_text="Só a equipe da escola vê. Nunca aparece para a família nem para o estudante.",
    )
    participants = models.ManyToManyField(
        User, blank=True, related_name="meetings", verbose_name="participantes"
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="meetings_created",
        verbose_name="agendada por",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Lembrete da véspera já enviado (evita repetir a cada processo).
    reminded_for = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["-scheduled_at"]
        indexes = [models.Index(fields=["school", "scheduled_at"])]
        verbose_name = "reunião"
        verbose_name_plural = "reuniões"

    def __str__(self):
        return f"{self.title} — {timezone.localtime(self.scheduled_at):%d/%m/%Y %H:%M}"

    @property
    def is_past(self):
        return self.scheduled_at < timezone.now()


class MeetingFollowUp(models.Model):
    """Encaminhamento combinado na reunião: o que fazer, quem faz, até quando."""

    class Status(models.TextChoices):
        PENDING = "pendente", "Pendente"
        DONE = "concluido", "Concluído"
        CANCELED = "cancelado", "Cancelado"

    meeting = models.ForeignKey(
        Meeting, on_delete=models.CASCADE, related_name="follow_ups", verbose_name="reunião"
    )
    description = models.CharField("encaminhamento", max_length=300)
    responsible = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="meeting_follow_ups",
        verbose_name="responsável",
    )
    due_date = models.DateField("prazo", null=True, blank=True)
    # Encaminhamento interno (ex.: acionar a rede de proteção) não aparece à família.
    staff_only = models.BooleanField("só a equipe vê", default=False)
    status = models.CharField("situação", max_length=10, choices=Status.choices, default=Status.PENDING)
    done_note = models.CharField("como foi resolvido", max_length=300, blank=True)
    done_at = models.DateTimeField(null=True, blank=True)
    done_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["status", "due_date", "pk"]
        verbose_name = "encaminhamento"
        verbose_name_plural = "encaminhamentos"

    def __str__(self):
        return self.description

    @property
    def overdue(self):
        return self.status == self.Status.PENDING and bool(self.due_date) and self.due_date < timezone.localdate()
