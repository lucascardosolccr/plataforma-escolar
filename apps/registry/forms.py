from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.academics.models import ClassGroup, SchoolYear
from apps.core.models import Role, User

from .models import Enrollment, GuardianLink, GuardianProfile, Student


class StudentForm(forms.ModelForm):
    class Meta:
        model = Student
        fields = ["first_name", "last_name", "birth_date", "photo", "status", "notes"]
        widgets = {"birth_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})}
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

    def clean(self):
        cleaned = super().clean()
        guardian = cleaned.get("guardian")
        student = cleaned.get("student")
        if guardian and student:
            duplicado = GuardianLink.objects.filter(
                guardian=guardian, student=student
            ).exclude(pk=self.instance.pk)
            if duplicado.exists():
                raise ValidationError(
                    "Já existe um vínculo entre este responsável e este estudante."
                )
        return cleaned


class EnrollmentForm(forms.ModelForm):
    class Meta:
        model = Enrollment
        fields = [
            "student", "class_group", "school_year", "enrollment_number", "status",
            "started_on", "ended_on",
        ]
        widgets = {
            "started_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "ended_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.school = school
        if school:
            self.fields["student"].queryset = Student.objects.filter(school=school)
            self.fields["class_group"].queryset = ClassGroup.objects.filter(school=school)
            self.fields["school_year"].queryset = SchoolYear.objects.filter(school=school)
        if self.instance.pk:
            self.fields["student"].disabled = True
            self.fields["class_group"].help_text = (
                "Para mudar o estudante de turma, use “Transferir” na lista de "
                "matrículas: assim o histórico da turma anterior é preservado."
            )
        else:
            # Saída não faz sentido numa matrícula que está sendo criada.
            del self.fields["ended_on"]

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        if cleaned["class_group"].school_id != self.school.id:
            raise ValidationError("Turma de outra escola selecionada.")
        if cleaned["school_year"].school_id != self.school.id:
            raise ValidationError("Ano letivo de outra escola selecionado.")
        if (
            self.instance.pk
            and cleaned["class_group"].pk != self.instance.class_group_id
        ):
            # Trocar a turma no lugar faz a matrícula "nunca ter estado" na
            # turma anterior: atividades e trabalhos já atribuídos somem da
            # ficha e da área da família.
            raise ValidationError(
                "A turma de uma matrícula existente não é alterada pela edição. "
                "Use “Transferir” para mudar o estudante de turma sem apagar o "
                "histórico da turma anterior."
            )
        if cleaned.get("status") == "ativo":
            outra_ativa = Enrollment.objects.filter(
                school=self.school,
                student=cleaned["student"],
                school_year=cleaned["school_year"],
                status="ativo",
            ).exclude(pk=self.instance.pk)
            if outra_ativa.exists():
                raise ValidationError(
                    "Este estudante já possui matrícula ativa neste ano letivo. "
                    "Para mudar de turma, use “Transferir”."
                )
        if cleaned["class_group"].school_year_id != cleaned["school_year"].id:
            raise ValidationError(
                "A turma escolhida não pertence ao ano letivo selecionado."
            )
        inicio, fim = cleaned.get("started_on"), cleaned.get("ended_on")
        if inicio and fim and fim < inicio:
            raise ValidationError("A saída da turma não pode ser anterior à entrada.")
        return cleaned

    def save(self, commit=True):
        enrollment = super().save(commit=False)
        # A data de saída acompanha o status: sem ela, uma publicação feita
        # para a turma depois da saída continuaria chegando à família.
        if enrollment.status == "ativo":
            enrollment.ended_on = None
        elif enrollment.ended_on is None:
            enrollment.ended_on = timezone.localdate()
        if commit:
            enrollment.save()
        return enrollment


class EnrollmentTransferForm(forms.Form):
    """Transferência de turma dentro do mesmo ano letivo.

    Encerra a matrícula atual (status "transferido", com data de saída) e abre
    uma nova na turma de destino. As duas ficam registradas: o histórico da
    turma anterior continua na ficha e na área da família.
    """

    class_group = forms.ModelChoiceField(
        queryset=ClassGroup.objects.none(), label="Nova turma"
    )
    date = forms.DateField(
        label="Data da transferência",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        help_text="Último dia na turma atual e primeiro na nova.",
    )

    def __init__(self, *args, enrollment=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.enrollment = enrollment
        self.fields["class_group"].queryset = ClassGroup.objects.filter(
            school=enrollment.school, school_year=enrollment.school_year
        ).exclude(pk=enrollment.class_group_id)
        self.fields["date"].initial = timezone.localdate()

    def clean_date(self):
        value = self.cleaned_data["date"]
        if self.enrollment.started_on and value < self.enrollment.started_on:
            raise ValidationError(
                "A transferência não pode ser anterior à entrada na turma atual."
            )
        return value