from django import forms
from django.core.exceptions import ValidationError

from apps.core.models import Role, User

from .models import ClassGroup, SchoolYear, Subject, TeacherAssignment


class SchoolYearForm(forms.ModelForm):
    class Meta:
        model = SchoolYear
        fields = ["name", "start_date", "end_date", "is_current"]
        widgets = {
            "start_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "end_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
        }
        labels = {
            "name": "Nome (ano)",
            "start_date": "Início",
            "end_date": "Fim",
            "is_current": "Ano letivo atual",
        }

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.school = school

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        if cleaned.get("start_date") and cleaned.get("end_date"):
            if cleaned["end_date"] < cleaned["start_date"]:
                self.add_error("end_date", "A data de fim não pode ser anterior ao início.")
        dup = SchoolYear.objects.filter(school=self.school, name=cleaned.get("name")).exclude(
            pk=self.instance.pk
        )
        if cleaned.get("name") and dup.exists():
            self.add_error("name", "Já existe um ano letivo com este nome nesta escola.")
        if cleaned.get("is_current"):
            SchoolYear.objects.filter(school=self.school, is_current=True).exclude(
                pk=self.instance.pk
            ).update(is_current=False)
        return cleaned


class ClassGroupForm(forms.ModelForm):
    class Meta:
        model = ClassGroup
        fields = ["school_year", "name", "grade", "turn"]
        labels = {
            "school_year": "Ano letivo",
            "name": "Nome da turma",
            "grade": "Série",
            "turn": "Turno",
        }

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.school = school
        if school:
            self.fields["school_year"].queryset = SchoolYear.objects.filter(school=school)

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        dup = ClassGroup.objects.filter(
            school=self.school, school_year=cleaned.get("school_year"), name=cleaned.get("name")
        ).exclude(pk=self.instance.pk)
        if cleaned.get("name") and dup.exists():
            self.add_error("name", "Já existe uma turma com este nome neste ano letivo.")
        return cleaned


class SubjectForm(forms.ModelForm):
    class Meta:
        model = Subject
        fields = ["name", "code"]
        labels = {"name": "Nome da disciplina", "code": "Código"}

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.school = school

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        dup = Subject.objects.filter(school=self.school, name=cleaned.get("name")).exclude(
            pk=self.instance.pk
        )
        if cleaned.get("name") and dup.exists():
            self.add_error("name", "Já existe uma disciplina com este nome nesta escola.")
        return cleaned


class TeacherAssignmentForm(forms.ModelForm):
    teacher = forms.ModelChoiceField(label="Professor", queryset=User.objects.none())

    class Meta:
        model = TeacherAssignment
        fields = ["teacher", "class_group", "subject", "school_year"]

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.school = school
        if school:
            self.fields["teacher"].queryset = User.objects.filter(
                role=Role.PROFESSOR.value, school=school
            ).order_by("first_name")
            self.fields["class_group"].queryset = ClassGroup.objects.filter(school=school)
            self.fields["subject"].queryset = Subject.objects.filter(school=school)
            self.fields["school_year"].queryset = SchoolYear.objects.filter(school=school)

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        for f in ("class_group", "subject", "school_year"):
            if cleaned.get(f) and cleaned[f].school_id != self.school.id:
                raise ValidationError("Registro de outra escola selecionado.")
        if cleaned["class_group"].school_year_id != cleaned["school_year"].id:
            raise ValidationError("A turma não pertence ao ano letivo selecionado.")
        dup = TeacherAssignment.objects.filter(
            school=self.school,
            school_year=cleaned["school_year"],
            teacher=cleaned["teacher"],
            class_group=cleaned["class_group"],
            subject=cleaned["subject"],
        ).exclude(pk=self.instance.pk)
        if dup.exists():
            raise ValidationError(
                "Este professor já está atribuído a essa turma/disciplina neste ano letivo."
            )
        return cleaned