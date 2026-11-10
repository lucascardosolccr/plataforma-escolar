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


class OfficeHours(models.Model):
    """Horários que alguém da equipe abre para as famílias marcarem uma conversa (plantão de dúvidas, reunião de
    pais e mestres). Cada horário marcado vira uma reunião com os responsáveis: aviso, lembrete na véspera, registro
    e encaminhamentos seguem as regras das reuniões (``access``)."""

    SLOT_CHOICES = [(10, "10 minutos"), (15, "15 minutos"), (20, "20 minutos"), (30, "30 minutos"),
                    (45, "45 minutos"), (60, "1 hora")]

    school = models.ForeignKey(School, on_delete=models.CASCADE, verbose_name="escola")
    host = models.ForeignKey(User, on_delete=models.CASCADE, related_name="office_hours", verbose_name="quem atende")
    title = models.CharField("assunto", max_length=120,
                             help_text="Ex.: Reunião de pais do 1º bimestre; Plantão de dúvidas de Matemática.")
    day = models.DateField("dia")
    start = models.TimeField("das")
    end = models.TimeField("até")
    slot_minutes = models.PositiveSmallIntegerField("cada conversa", choices=SLOT_CHOICES, default=15)
    location = models.CharField("local ou forma", max_length=200, blank=True,
                                help_text="Ex.: sala 5; chamada de vídeo (o link vai na reunião).")
    notes = models.TextField("orientações para as famílias", blank=True)
    class_groups = models.ManyToManyField(ClassGroup, related_name="office_hours", verbose_name="turmas",
                                          help_text="As famílias dessas turmas podem marcar.")
    closed = models.BooleanField("fechado para novas marcações", default=False)
    announced_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["day", "start"]
        verbose_name = "horário de atendimento"
        verbose_name_plural = "horários de atendimento"

    def __str__(self):
        return f"{self.title} — {self.day:%d/%m/%Y}"


class OfficeSlot(models.Model):
    """Um horário dentro do atendimento. Marcado, aponta para a reunião criada com a família."""

    hours = models.ForeignKey(OfficeHours, on_delete=models.CASCADE, related_name="slots")
    starts_at = models.DateTimeField("início")
    student = models.ForeignKey(Student, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                verbose_name="estudante")
    booked_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    booked_at = models.DateTimeField(null=True, blank=True)
    topic = models.CharField("o que quer conversar", max_length=200, blank=True)
    meeting = models.OneToOneField(Meeting, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="office_slot")

    class Meta:
        ordering = ["starts_at"]
        verbose_name = "horário marcado"
        verbose_name_plural = "horários marcados"
        constraints = [
            models.UniqueConstraint(fields=["hours", "starts_at"], name="uniq_office_slot_time"),
            # Um horário por estudante em cada atendimento (estudante vazio = horário livre, não conta).
            models.UniqueConstraint(fields=["hours", "student"], name="uniq_office_slot_student"),
        ]

    def __str__(self):
        return f"{self.hours.title} {timezone.localtime(self.starts_at):%d/%m %H:%M}"

    @property
    def free(self):
        return self.student_id is None
