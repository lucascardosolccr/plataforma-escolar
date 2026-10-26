from django import forms
from django.core.exceptions import ValidationError

from apps.academics.models import ClassGroup, SchoolYear
from apps.core.models import Role, User

from .models import Enrollment, GuardianLink, GuardianProfile, Student


class StudentForm(forms.ModelForm):
    class Meta:
        model = Student
        fields = ["first_name", "last_name", "birth_date", "photo", "status", "notes"]
        widgets = {"birth_date": forms.DateInput(attrs={"type": "date"})}
        labels = {
            "first_name": "Nome",
            "last_name": "Sobrenome",
            "birth_date": "Data de nascimento",
            "photo": "Fotografia",
            "status": "Situação",
            "notes": "Observações da secretaria",
        }

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.school = school
        if not self.instance.pk:
            self.fields["photo"].help_text = "Opcional. JPG, PNG ou WEBP, até 2 MB."

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("first_name", "").strip():
            self.add_error("first_name", "Informe o nome do estudante.")
        return cleaned


class GuardianProfileForm(forms.ModelForm):
    class Meta:
        model = GuardianProfile
        fields = ["phone", "emergency_contact", "address", "relation", "comm_preference", "photo"]
        labels = {
            "phone": "Telefone",
            "emergency_contact": "Contato de emergência",
            "address": "Endereço",
            "relation": "Relação com o estudante",
            "comm_preference": "Preferência de comunicação",
            "photo": "Fotografia",
        }


class GuardianLinkRequestForm(forms.Form):
    """Solicitação de vínculo feita pelo próprio responsável.

    O responsável informa o nome completo do estudante. A solicitação fica
    aguardando validação da secretaria; nenhum dado do estudante é exposto
    ao solicitante antes da aprovação.
    """

    student_name = forms.CharField(
        label="Nome completo do estudante",
        max_length=200,
        help_text="Informe exatamente como consta na matrícula.",
    )
    relation = forms.ChoiceField(
        label="Relação com o estudante",
        choices=GuardianProfile.RELATION_CHOICES,
    )

    def __init__(self, *args, guardian=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.guardian = guardian

    def clean_student_name(self):
        query = " ".join(self.cleaned_data["student_name"].split()).lower()
        if not self.guardian or not self.guardian.school_id:
            raise ValidationError("Seu perfil precisa estar vinculado a uma escola.")
        match = None
        candidates = Student.objects.filter(school=self.guardian.school_id, status="ativo")
        for s in candidates:
            if " ".join((s.first_name + " " + s.last_name).split()).lower() == query:
                match = s
                break
        if match is None:
            raise ValidationError(
                "Nenhum estudante ativo encontrado com esse nome em sua escola. "
                "Verifique a grafia ou solicite auxílio da secretaria."
            )
        if GuardianLink.objects.filter(guardian=self.guardian, student=match).exists():
            raise ValidationError(
                "Já existe um vínculo com esse estudante; aguarde a validação da secretaria."
            )
        return match

    def clean(self):
        cleaned = super().clean()
        students = cleaned.get("student_name")
        if students is not None and not isinstance(students, Student):
            raise ValidationError(
                "Não foi possível localizar o estudante. Verifique o nome informado."
            )
        return cleaned


class GuardianLinkAdminForm(forms.ModelForm):
    """Criação de vínculo pela secretaria (validado de imediato)."""

    guardian = forms.ModelChoiceField(
        label="Responsável",
        queryset=User.objects.none(),
    )

    class Meta:
        model = GuardianLink
        fields = ["guardian", "student", "relation"]

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.school = school
        if school:
            self.fields["guardian"].queryset = User.objects.filter(
                role=Role.RESPONSAVEL.value, school=school
            ).order_by("first_name")
            self.fields["student"].queryset = Student.objects.filter(school=school)
        self.fields["student"].label = "Estudante"


class EnrollmentForm(forms.ModelForm):
    class Meta:
        model = Enrollment
        fields = ["student", "class_group", "school_year", "enrollment_number", "status"]

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.school = school
        if school:
            self.fields["student"].queryset = Student.objects.filter(school=school)
            self.fields["class_group"].queryset = ClassGroup.objects.filter(school=school)
            self.fields["school_year"].queryset = SchoolYear.objects.filter(school=school)

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        if cleaned["class_group"].school_id != self.school.id:
            raise ValidationError("Turma de outra escola selecionada.")
        if cleaned["school_year"].school_id != self.school.id:
            raise ValidationError("Ano letivo de outra escola selecionado.")
        existing = Enrollment.objects.filter(
            school=self.school,
            student=cleaned["student"],
            school_year=cleaned["school_year"],
        ).exclude(pk=self.instance.pk)
        if cleaned.get("status") and cleaned["status"] != "desistente" and existing.exists():
            raise ValidationError(
                "Este estudante já possui matrícula ativa ou concluída neste ano letivo."
            )
        if cleaned["class_group"].school_year_id != cleaned["school_year"].id:
            raise ValidationError(
                "A turma escolhida não pertence ao ano letivo selecionado."
            )
        return cleaned