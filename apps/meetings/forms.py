from django import forms

from apps.academics.models import ClassGroup
from apps.core.models import Role, User

from apps.registry.choices import label_students_with_class

from .access import STAFF_ROLES
from .models import Meeting, MeetingFollowUp

DATETIME = forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"})


def staff_of(school):
    return User.objects.filter(school=school, is_active=True, role__in=STAFF_ROLES).order_by(
        "first_name", "last_name", "username")


class MeetingForm(forms.ModelForm):
    staff = forms.ModelMultipleChoiceField(
        label="Participantes da escola", required=False, queryset=User.objects.none(),
        widget=forms.SelectMultiple(attrs={"size": 6}),
        help_text="Quem marca a reunião já participa. Segure Ctrl para escolher mais de um.",
    )
    invite_guardians = forms.BooleanField(
        label="Convidar os responsáveis do estudante", required=False,
        help_text="Só os responsáveis com vínculo aprovado. Eles recebem o aviso e veem a pauta e o registro.",
    )

    class Meta:
        model = Meeting
        fields = ["kind", "title", "student", "class_group", "scheduled_at", "duration_minutes",
                  "location", "agenda"]
        widgets = {"scheduled_at": DATETIME, "agenda": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.registry.access import students_visible_to

        self.user = user
        school = user.school
        self.fields["student"].queryset = (students_visible_to(user) or school.students.none()).order_by(
            "first_name", "last_name")
        label_students_with_class(self.fields["student"])
        classes = ClassGroup.objects.filter(school=school)
        if user.role == Role.PROFESSOR.value:
            from apps.academics.permissions import teacher_class_ids

            classes = classes.filter(pk__in=teacher_class_ids(user))
        elif user.role == Role.COORDENACAO.value:
            from apps.coordination.scope import class_scope

            scope = class_scope(user)
            if scope is not None:
                classes = classes.filter(pk__in=scope)
        self.fields["class_group"].queryset = classes.order_by("name")
        # Quem marcou sempre participa e não aparece na lista (na edição, pode
        # ser outra pessoa a editar, e ela continua escolhível).
        owner = self.instance.created_by_id if self.instance.pk else user.pk
        self.fields["staff"].queryset = staff_of(school).exclude(pk=owner)
        self.fields["scheduled_at"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"]
        if self.instance.pk:
            self.fields["staff"].initial = self.instance.participants.filter(role__in=STAFF_ROLES)
            self.fields["invite_guardians"].initial = self.instance.participants.filter(
                role=Role.RESPONSAVEL.value).exists()

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("invite_guardians") and not cleaned.get("student"):
            self.add_error("invite_guardians", "Escolha o estudante para convidar os responsáveis dele.")
        return cleaned


class MeetingRecordForm(forms.ModelForm):
    class Meta:
        model = Meeting
        fields = ["summary", "confidential_notes"]
        widgets = {"summary": forms.Textarea(attrs={"rows": 5}),
                   "confidential_notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["summary"].required = True


class MeetingCancelForm(forms.Form):
    reason = forms.CharField(label="Motivo do cancelamento", max_length=255)


class FollowUpForm(forms.ModelForm):
    class Meta:
        model = MeetingFollowUp
        fields = ["description", "responsible", "due_date", "staff_only"]
        widgets = {"due_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})}

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["responsible"].queryset = staff_of(school)
        self.fields["responsible"].required = False
        self.fields["responsible"].help_text = "Quem da escola cuida disto. A família não é responsável por encaminhamento."
