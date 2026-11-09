from django import forms
from django.core.exceptions import ValidationError

from apps.academics.models import ClassGroup
from apps.core.uploads import MAX_ATTACHMENT_SIZE_MB, validate_attachment, validate_attachment_content
from apps.registry.models import GuardianLink, Student

from . import access as acc
from .models import Announcement, ReminderPolicy, ServiceRequest


def attachment_field():
    return forms.FileField(
        label="Anexo",
        required=False,
        validators=[validate_attachment, validate_attachment_content],
        help_text=f"Opcional. Um arquivo de até {MAX_ATTACHMENT_SIZE_MB} MB: PDF, imagem, documento ou planilha.",
    )


class PersonChoiceField(forms.ModelChoiceField):
    """Pessoa pelo nome e pela função, não pelo login técnico ("demo.prof1")."""

    def label_from_instance(self, obj):
        name = obj.get_full_name() or obj.username
        return f"{name} — {obj.role_label}"


class ThreadForm(forms.Form):
    """Nova conversa: responsável escolhe profissional; profissional escolhe
    responsável. As opções respeitam as permissões do usuário."""

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user.role == "responsavel":
            self.fields["recipient"] = PersonChoiceField(
                label="Com quem você quer falar",
                queryset=acc.professional_recipients(user).order_by("first_name", "last_name"),
                empty_label="Escolha…",
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
            self.fields["recipient"] = PersonChoiceField(
                label="Responsável",
                queryset=acc.guardian_recipients(user).order_by("first_name", "last_name"),
                empty_label="Escolha…",
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
        self.fields["attachment"] = attachment_field()

    def clean_recipient(self):
        recipient = self.cleaned_data["recipient"]
        if recipient.pk == self.user.pk:
            raise ValidationError("Você não pode abrir conversa consigo mesmo(a).")
        if not acc.can_message_user(self.user, recipient):
            raise ValidationError("Escolha um profissional/responsável permitido da mesma escola.")
        return recipient

    def clean(self):
        cleaned = super().clean()
        student = cleaned.get("student")
        recipient = cleaned.get("recipient")
        if not student or not recipient:
            return cleaned
        if self.user.role == "responsavel":
            if recipient.role == "professor":
                from apps.registry.access import teacher_of_student

                if not teacher_of_student(recipient, student):
                    self.add_error(
                        "recipient",
                        "O professor escolhido não leciona para este estudante.",
                    )
        elif not GuardianLink.objects.filter(
            guardian=recipient, student=student, status="aprovado"
        ).exists():
            self.add_error(
                "recipient", "O responsável escolhido não está vinculado a este estudante."
            )
        return cleaned


class ReplyForm(forms.Form):
    body = forms.CharField(
        label="Sua resposta",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    attachment = attachment_field()


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
            elif acc._coord_scope(user) is not None:
                scope = acc._coord_scope(user)
                self.fields["class_group"].queryset = self.fields["class_group"].queryset.filter(pk__in=scope)
                students = students.filter(enrollments__class_group_id__in=scope,
                                           enrollments__status="ativo").distinct()
            self.fields["student"].queryset = students
        self.fields["scope"].required = False
        self.fields["scope"].initial = Announcement.Scope.INSTITUCIONAL
        if user is not None and acc._coord_scope(user) is not None:
            self.fields["scope"].initial = Announcement.Scope.TURMA
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
        fields = ["student", "category", "data_right", "title", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}
        labels = {
            "student": "Estudante (opcional)",
            "category": "Categoria",
            "data_right": "O que você quer sobre os dados (só para a categoria LGPD)",
            "title": "Assunto",
            "description": "Detalhes",
        }
        help_texts = {
            "data_right": "Pela LGPD (art. 18), você pode pedir isso sobre os seus dados e os do seu filho. Prazo de "
                          "referência da escola: 15 dias. Registros que a escola é obrigada a manter, como a vida "
                          "escolar, podem não ser eliminados (art. 16, I); nesse caso a resposta explica o motivo.",
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

    def clean(self):
        data = super().clean()
        if data.get("data_right"):
            data["category"] = ServiceRequest.Category.LGPD  # escolheu o direito: o pedido é sobre dados
        elif data.get("category") == ServiceRequest.Category.LGPD:
            self.add_error("data_right", "Escolha o que você quer sobre os dados.")
        return data


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


class ReminderPolicyForm(forms.ModelForm):
    """Antecedência dos lembretes: números de dias separados por vírgula."""

    class Meta:
        model = ReminderPolicy
        fields = ["activity_days", "overdue_days", "exam_days", "include_guardians"]
        labels = {
            "activity_days": "Atividades e trabalhos: avisar quantos dias antes da entrega",
            "overdue_days": "Atividade pendente: avisar quantos dias depois do vencimento",
            "exam_days": "Provas: avisar quantos dias antes",
        }
        help_texts = {
            "activity_days": "Ex.: 7, 3, 1, 0 (0 = no próprio dia). Até 60 dias.",
            "overdue_days": "Ex.: 1, 3. Deixe vazio para não avisar depois do prazo.",
            "exam_days": "Ex.: 7, 1, 0. Só vale para provas com a data divulgada.",
        }

    def _days(self, name, required):
        raw = (self.cleaned_data.get(name) or "").strip()
        parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
        if not parts:
            if required:
                raise ValidationError("Informe ao menos um número de dias.")
            return ""
        bad = [p for p in parts if not p.isdigit() or int(p) > 60]
        if bad:
            raise ValidationError(f"Use números inteiros de 0 a 60 separados por vírgula (não aceito: {', '.join(bad)}).")
        return ", ".join(str(d) for d in ReminderPolicy.parse(raw))

    def clean_activity_days(self):
        return self._days("activity_days", True)

    def clean_overdue_days(self):
        value = self._days("overdue_days", False)
        if value and "0" in value.split(", "):
            raise ValidationError("Depois do vencimento, use números a partir de 1.")
        return value

    def clean_exam_days(self):
        return self._days("exam_days", True)
