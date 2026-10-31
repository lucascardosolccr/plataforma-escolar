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
        return cleaned

    def save(self, commit=True):
        # Só aqui, depois de validado: no clean(), um formulário recusado já
        # desmarcava o ano atual e a escola ficava sem ano corrente.
        year = super().save(commit=commit)
        if year.is_current:
            SchoolYear.objects.filter(school=self.school, is_current=True).exclude(
                pk=year.pk
            ).update(is_current=False)
        return year


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
        fields = ["name", "code", "curriculum_component", "grade_level", "workload_hours", "is_active", "valid_from",
                  "valid_until"]
        labels = {"name": "Nome da disciplina", "code": "Código"}
        widgets = {
            "valid_from": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "valid_until": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
        }

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.school = school

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        start, end = cleaned.get("valid_from"), cleaned.get("valid_until")
        if start and end and end < start:
            self.add_error("valid_until", "O fim da vigência não pode ser antes do início.")
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
        fields = ["teacher", "class_group", "subject", "school_year", "starts_on", "ends_on"]
        widgets = {
            "starts_on": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "ends_on": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
        }
        help_texts = {"starts_on": "Em branco: desde o início do ano letivo.",
                      "ends_on": "Em branco: até o fim do ano letivo. Use em substituições."}

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.school = school
        if school:
            self.fields["teacher"].queryset = User.objects.filter(
                role=Role.PROFESSOR.value, school=school
            ).order_by("first_name")
            self.fields["class_group"].queryset = ClassGroup.objects.filter(school=school)
            self.fields["subject"].queryset = Subject.choices_for(school, keep=self.instance.subject_id)
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