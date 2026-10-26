from django import forms
from django.core.exceptions import ValidationError

from apps.academics.models import ClassGroup
from apps.core.models import User
from apps.registry.models import Enrollment, GuardianLink, Student

from . import access as acc
from .models import Announcement, ServiceRequest


class ThreadForm(forms.Form):
    """Nova conversa: responsável escolhe profissional; profissional escolhe
    responsável. As opções respeitam as permissões do usuário."""

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user.role == "responsavel":
            self.fields["recipient"] = forms.ModelChoiceField(
                label="Profissional",
                queryset=acc.professional_recipients(user),
                empty_label=None,
            )
            children = Student.objects.filter(
                pk__in=acc._guardian_child_ids(user)
            ).order_by("first_name", "last_name")
            self.fields["student"] = forms.ModelChoiceField(
                label="Estudante (opcional)",
                queryset=children,
                required=False,
                empty_label="— conversa geral —",
            )
        else:
            self.fields["recipient"] = forms.ModelChoiceField(
                label="Responsável",
                queryset=acc.guardian_recipients(user),
                empty_label=None,
            )
            allowed_students = Student.objects.filter(school=user.school)
            if user.role == "professor":
                allowed_students = allowed_students.filter(
                    pk__in=acc._teacher_student_ids(user)
                )
            self.fields["student"] = forms.ModelChoiceField(
                label="Estudante (opcional)",
                queryset=allowed_students,
                required=False,
                empty_label="— conversa geral —",
            )
        self.fields["title"] = forms.CharField(label="Assunto", max_length=200)
        self.fields["body"] = forms.CharField(
            label="Mensagem inicial",
            widget=forms.Textarea(attrs={"rows": 4}),
        )

    def clean_recipient(self):
        recipient = self.cleaned_data["recipient"]
        if recipient.pk == self.user.pk:
            raise ValidationError("Você não pode abrir conversa consigo mesmo(a).")
        if not acc.can_message_user(self.user, recipient):
            raise ValidationError("Escolha um profissional/responsável permitido da mesma escola.")
        return recipient


class ReplyForm(forms.Form):
    body = forms.CharField(
        label="Sua resposta",
        widget=forms.Textarea(attrs={"rows": 3}),
    )


class AnnouncementForm(forms.ModelForm):
    class Meta:
        model = Announcement
        fields = ["scope", "audience", "class_group", "student", "title", "body"]
        widgets = {"body": forms.Textarea(attrs={"rows": 5})}
        labels = {
            "scope": "Abrangência",
            "audience": "Público",
            "class_group": "Turma",
            "student": "Estudante",
            "title": "Título",
            "body": "Texto",
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user is not None:
            school = user.school
            self.fields["class_group"].queryset = ClassGroup.objects.filter(school=school)
            students = Student.objects.filter(school=school)
            if user.role == "professor":
                self.fields["class_group"].queryset = self.fields[
                    "class_group"
                ].queryset.filter(pk__in=acc._teacher_class_ids(user))
                students = students.filter(pk__in=acc._teacher_student_ids(user))
            self.fields["student"].queryset = students
        self.fields["scope"].required = False
        self.fields["scope"].initial = Announcement.Scope.INSTITUCIONAL
        self.fields["audience"].required = False
        self.fields["audience"].initial = Announcement.Audience.FAMILIA

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        scope = cleaned.get("scope") or Announcement.Scope.INSTITUCIONAL
        class_group = cleaned.get("class_group")
        student = cleaned.get("student")
        if not acc.can_create_announcement(self.user, scope, class_group, student):
            raise ValidationError("Você não tem permissão para criar este comunicado.")
        if scope == Announcement.Scope.TURMA and not class_group:
            self.add_error("class_group", "Informe a turma para um comunicado por turma.")
        if scope == Announcement.Scope.INDIVIDUAL and not student:
            self.add_error("student", "Informe o estudante para um comunicado individual.")
        return cleaned


class ServiceRequestForm(forms.ModelForm):
    class Meta:
        model = ServiceRequest
        fields = ["student", "category", "title", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}
        labels = {
            "student": "Estudante (opcional)",
            "category": "Categoria",
            "title": "Assunto",
            "description": "Detalhes",
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user is not None:
            self.fields["student"].queryset = Student.objects.filter(
                pk__in=acc._guardian_child_ids(user)
            ).order_by("first_name", "last_name")
            self.fields["student"].required = False
            self.fields["category"].required = False
            self.fields["category"].initial = ServiceRequest.Category.OUTRO


class RequestResolutionForm(forms.ModelForm):
    class Meta:
        model = ServiceRequest
        fields = ["status", "response"]
        widgets = {"response": forms.Textarea(attrs={"rows": 3})}
        labels = {"status": "Situação", "response": "Resposta da equipe"}


def thread_queryset(user):
    """Conversas do usuário, com filtro opcional por estudante."""
    qs = user.threads.select_related("student").prefetch_related("participants")
    return qs