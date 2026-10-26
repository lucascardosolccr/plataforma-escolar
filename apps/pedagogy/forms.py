from django import forms
from django.utils import timezone

from apps.academics.models import ClassGroup, Subject, TeacherAssignment
from apps.core.models import Role, User

from .models import (
    AbsenceJustification,
    AcademicRule,
    Activity,
    Evaluation,
    InterventionPlan,
    Occurrence,
    PedagogicalObservation,
    PlanNote,
    SchoolConfig,
    Submission,
)


def _unlocalize(field):
    field.localize = False
    field.widget.is_localized = False
    return field


class EvaluationForm(forms.ModelForm):
    class Meta:
        model = Evaluation
        fields = ["class_group", "subject", "title", "description", "weight", "date", "status"]
        widgets = {"date": forms.DateInput(format=r"%Y-%m-%d", attrs={"type": "date"})}
        labels = {
            "class_group": "Turma",
            "subject": "Disciplina",
            "title": "Título",
            "description": "Descrição",
            "weight": "Peso",
            "date": "Data",
            "status": "Situação",
        }

    def __init__(self, *args, user=None, school=None, class_group=None, subject=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.school = school
        if school:
            self.fields["class_group"].queryset = ClassGroup.objects.filter(school=school)
            self.fields["subject"].queryset = Subject.objects.filter(school=school)
        if user and user.role == Role.PROFESSOR.value:
            assigned = TeacherAssignment.objects.filter(teacher=user, school=school)
            self.fields["class_group"].queryset = ClassGroup.objects.filter(
                pk__in=assigned.values("class_group_id")
            )
            self.fields["subject"].queryset = Subject.objects.filter(
                pk__in=assigned.values("subject_id")
            )
        if class_group:
            self.fields["class_group"].initial = class_group
        if subject:
            self.fields["subject"].initial = subject
        self.fields["status"].required = False
        self.fields["status"].initial = Evaluation.Status.DRAFT
        self.fields["date"].required = False
        self.fields["date"].initial = timezone.localdate()
        _unlocalize(self.fields["weight"])

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        cg, subj = cleaned.get("class_group"), cleaned.get("subject")
        if cg and cg.school_id != self.school.id:
            self.add_error("class_group", "Turma de outra escola.")
        if subj and subj.school_id != self.school.id:
            self.add_error("subject", "Disciplina de outra escola.")
        if (
            self.user
            and self.user.role == Role.PROFESSOR.value
            and cg
            and subj
            and not TeacherAssignment.objects.filter(
                teacher=self.user, class_group=cg, subject=subj, school=self.school
            ).exists()
        ):
            raise forms.ValidationError("Você só pode criar avaliações nas turmas/disciplinas que leciona.")
        return cleaned


class GradeBatchForm(forms.Form):
    """Lançamento de notas em lote para uma avaliação (um campo por estudante)."""

    def __init__(self, *args, evaluation=None, students=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.evaluation = evaluation
        self.students = students or []
        from .models import Grade

        existing = {
            g.student_id: g
            for g in Grade.objects.filter(evaluation=evaluation).select_related("student")
        }
        self.grades = []
        for s in self.students:
            grade = existing.get(s.id)
            field_name = f"grade_{s.id}"
            initial = grade.value if grade else None
            self.fields[field_name] = forms.DecimalField(
                label=None,
                required=False,
                max_digits=4,
                decimal_places=2,
                min_value=0,
                max_value=100,
                initial=initial,
                localize=False,
                widget=forms.NumberInput(
                    attrs={"class": "form-control form-control-sm", "style": "width:90px"}
                ),
            )
            self.grades.append((s, field_name))
        self.fields["observation_all"] = forms.CharField(
            label="Observação geral (opcional)",
            required=False,
            widget=forms.Textarea(attrs={"rows": 2}),
        )


class ActivityForm(forms.ModelForm):
    class Meta:
        model = Activity
        fields = ["class_group", "subject", "title", "description", "criteria", "deadline", "published_date"]
        widgets = {
            "deadline": forms.DateInput(format=r"%Y-%m-%d", attrs={"type": "date"}),
            "published_date": forms.DateInput(format=r"%Y-%m-%d", attrs={"type": "date"}),
        }
        labels = {
            "class_group": "Turma",
            "subject": "Disciplina",
            "title": "Título",
            "description": "Descrição",
            "criteria": "Critérios de avaliação",
            "deadline": "Prazo",
            "published_date": "Data de publicação",
        }

    def __init__(self, *args, user=None, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.school = school
        self.fields["published_date"].required = False
        self.fields["published_date"].initial = timezone.localdate()
        if school:
            self.fields["class_group"].queryset = ClassGroup.objects.filter(school=school)
            self.fields["subject"].queryset = school.subjects.all()
        if user and user.role == Role.PROFESSOR.value:
            assigned = TeacherAssignment.objects.filter(teacher=user, school=school)
            self.fields["class_group"].queryset = ClassGroup.objects.filter(
                pk__in=assigned.values("class_group_id")
            )
            self.fields["subject"].queryset = school.subjects.filter(
                pk__in=assigned.values("subject_id")
            )


class SubmissionForm(forms.ModelForm):
    class Meta:
        model = Submission
        fields = ["status", "comment"]
        labels = {"status": "Situação", "comment": "Observação"}


class AttendanceBatchForm(forms.Form):
    """Registro de frequência em lote: um campo por estudante, com default 'presente'."""

    STATUS_MAP = [("presente", "Presente"), ("atraso", "Atraso"), ("falta", "Falta")]
    date = forms.DateField(widget=forms.DateInput(format=r"%Y-%m-%d", attrs={"type": "date"}))

    def __init__(self, *args, class_group=None, students=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.class_group = class_group
        self.students = students or []
        from .models import AttendanceRecord

        existing = {
            (r.student_id): r
            for r in AttendanceRecord.objects.filter(
                class_group=class_group
            ).select_related("student")
        }
        self.rows = []
        for s in self.students:
            rec = existing.get(s.id)
            field_name = f"status_{s.id}"
            initial = rec.status if rec else "presente"
            self.fields[field_name] = forms.ChoiceField(
                label=None,
                choices=self.STATUS_MAP,
                initial=initial,
                widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
            )
            self.rows.append((s, field_name))


class AbsenceJustificationForm(forms.ModelForm):
    class Meta:
        model = AbsenceJustification
        fields = ["class_group", "start_date", "end_date", "reason"]
        widgets = {
            "start_date": forms.DateInput(format=r"%Y-%m-%d", attrs={"type": "date"}),
            "end_date": forms.DateInput(format=r"%Y-%m-%d", attrs={"type": "date"}),
        }
        labels = {
            "class_group": "Turma",
            "start_date": "Data inicial",
            "end_date": "Data final",
            "reason": "Motivo da falta",
        }

    def __init__(self, *args, school=None, student=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.school = school
        self.student = student
        if school:
            self.fields["class_group"].queryset = ClassGroup.objects.filter(school=school)
            self.fields["class_group"].required = False
        self.fields["start_date"].required = True
        self.fields["end_date"].required = True

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", "A data final não pode ser anterior à inicial.")
        return cleaned


class OccurrenceForm(forms.ModelForm):
    class Meta:
        model = Occurrence
        fields = ["student", "date", "description", "providencias", "encaminhamento", "status"]
        widgets = {"date": forms.DateInput(format=r"%Y-%m-%d", attrs={"type": "date"})}
        labels = {
            "student": "Estudante",
            "date": "Data",
            "description": "Descrição objetiva",
            "providencias": "Providências adotadas",
            "encaminhamento": "Encaminhamento",
            "status": "Situação",
        }

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.school = school
        if school:
            self.fields["student"].queryset = school.students.all()
        self.fields["status"].required = False
        self.fields["status"].initial = Occurrence.Status.OPEN
        self.fields["date"].required = False
        self.fields["date"].initial = timezone.localdate()


class OccurrenceUpdateForm(forms.ModelForm):
    class Meta:
        model = Occurrence
        fields = ["status", "providencias", "encaminhamento"]
        labels = {
            "status": "Situação",
            "providencias": "Providências adotadas",
            "encaminhamento": "Encaminhamento",
        }


class PedagogicalObservationForm(forms.ModelForm):
    class Meta:
        model = PedagogicalObservation
        fields = ["student", "subject", "content", "dificuldades", "habilidades", "estrategias", "observed_at"]
        widgets = {"observed_at": forms.DateInput(format=r"%Y-%m-%d", attrs={"type": "date"})}
        labels = {
            "student": "Estudante",
            "subject": "Disciplina",
            "content": "Conteúdo/tema",
            "dificuldades": "Dificuldades observadas",
            "habilidades": "Habilidades consolidadas",
            "estrategias": "Estratégias e reforço recomendado",
            "observed_at": "Data",
        }

    def __init__(self, *args, school=None, student=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.school = school
        self.student = student
        if school:
            self.fields["student"].queryset = school.students.all()
            self.fields["subject"].queryset = school.subjects.all()
            self.fields["subject"].required = False
        if student:
            self.fields["student"].initial = student
        if self.instance.pk:
            self.fields["student"].disabled = True
        self.fields["observed_at"].required = False
        self.fields["observed_at"].initial = timezone.localdate()


class InterventionPlanForm(forms.ModelForm):
    class Meta:
        model = InterventionPlan
        fields = ["student", "title", "description", "status"]
        labels = {
            "student": "Estudante",
            "title": "Título",
            "description": "Objetivos e estratégias",
            "status": "Situação",
        }

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.school = school
        if school:
            self.fields["student"].queryset = school.students.all()
        self.fields["status"].required = False
        self.fields["status"].initial = InterventionPlan.Status.ACTIVE


class PlanNoteForm(forms.ModelForm):
    class Meta:
        model = PlanNote
        fields = ["note"]
        labels = {"note": "Registro de evolução"}
        widgets = {"note": forms.Textarea(attrs={"rows": 3})}


class SchoolConfigForm(forms.ModelForm):
    class Meta:
        model = SchoolConfig
        fields = ["max_absences_percent"]
        labels = {"max_absences_percent": "Limite de faltas (%)"}
        widgets = {"max_absences_percent": forms.NumberInput(attrs={"step": "0.5"})}

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.school = school
        _unlocalize(self.fields["max_absences_percent"])


class AcademicRuleForm(forms.ModelForm):
    class Meta:
        model = AcademicRule
        fields = ["subject", "formula", "passing_grade"]
        labels = {
            "subject": "Disciplina",
            "formula": "Fórmula de média",
            "passing_grade": "Média de aprovação",
        }

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.school = school
        if school:
            self.fields["subject"].queryset = Subject.objects.filter(school=school)
        _unlocalize(self.fields["passing_grade"])


class JustificationResolutionForm(forms.Form):
    """Parecer da secretaria ao aprovar/recusar uma justificativa de falta."""

    note = forms.CharField(
        label="Parecer (opcional)", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )