from django import forms
from django.utils import timezone

from apps.academics.models import ClassGroup, Subject, TeacherAssignment
from apps.core.models import Role, User
from apps.core.uploads import (
    MAX_ATTACHMENT_SIZE_MB,
    validate_attachment,
    validate_attachment_content,
)

from .models import (
    AbsenceJustification,
    AcademicRule,
    Activity,
    Evaluation,
    GroupWork,
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
        fields = ["class_group", "subject", "title", "kind", "description", "weight", "date"]
        widgets = {"date": forms.DateInput(format=r"%Y-%m-%d", attrs={"type": "date"})}
        labels = {
            "class_group": "Turma",
            "subject": "Disciplina",
            "title": "Título",
            "kind": "Tipo de avaliação",
            "description": "Descrição",
            "weight": "Peso",
            "date": "Data",
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
                    attrs={"class": "form-control form-control-sm grade-input", "step": "0.01",
                           "inputmode": "decimal", "aria-label": f"Nota de {s.full_name}"}
                ),
            )
            self.grades.append((s, field_name))
        self.fields["observation_all"] = forms.CharField(
            label="Observação geral (opcional)",
            required=False,
            widget=forms.Textarea(attrs={"rows": 2}),
        )


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """Campo de vários arquivos: o FileField padrão só valida o último."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        if not data:
            return []
        files = data if isinstance(data, (list, tuple)) else [data]
        return [super(MultipleFileField, self).clean(f, initial) for f in files]


class ActivityForm(forms.ModelForm):
    # Os validadores ficam no campo do FORMULÁRIO de propósito: ActivityAttachment
    # é criado com objects.create(), que não executa validadores de modelo. Sem
    # isto um executável passaria direto para o disco.
    attachments = MultipleFileField(
        label="Anexos de apoio",
        required=False,
        validators=[validate_attachment, validate_attachment_content],
        help_text=(
            f"Opcional. Até {MAX_ATTACHMENT_SIZE_MB} MB por arquivo. "
            "PDF, imagem, documento, planilha ou apresentação."
        ),
    )

    class Meta:
        model = Activity
        fields = [
            "class_group",
            "subject",
            "title",
            "description",
            "materials",
            "criteria",
            "class_date",
            "published_date",
            "deadline",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
            "materials": forms.Textarea(attrs={"rows": 2}),
            "criteria": forms.Textarea(attrs={"rows": 2}),
            "deadline": forms.DateInput(format=r"%Y-%m-%d", attrs={"type": "date"}),
            "published_date": forms.DateInput(format=r"%Y-%m-%d", attrs={"type": "date"}),
            "class_date": forms.DateInput(format=r"%Y-%m-%d", attrs={"type": "date"}),
        }
        labels = {
            "class_group": "Turma",
            "subject": "Disciplina",
            "title": "Título",
            "description": "Instruções para o estudante",
            "materials": "Materiais necessários",
            "criteria": "Critérios de avaliação",
            "class_date": "Data da aula de referência",
            "deadline": "Data de entrega",
            "published_date": "Data de publicação",
        }
        help_texts = {
            "description": "Detalhe o que deve ser feito. É o texto que a família lê.",
            "published_date": "A família passa a ver a atividade a partir desta data.",
        }

    def __init__(self, *args, user=None, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.school = school
        self.fields["published_date"].required = False
        if not self.instance.pk:
            self.fields["published_date"].initial = timezone.localdate()
        self.fields["title"].required = True
        self.fields["description"].required = True
        if school:
            self.fields["class_group"].queryset = ClassGroup.objects.filter(
                school=school
            ).select_related("school_year")
            self.fields["subject"].queryset = school.subjects.all()
        if user and user.role == Role.PROFESSOR.value:
            self._assignments = TeacherAssignment.objects.filter(
                teacher=user, school=school
            )
            self.fields["class_group"].queryset = ClassGroup.objects.filter(
                pk__in=self._assignments.values("class_group_id")
            ).select_related("school_year")
            self.fields["subject"].queryset = school.subjects.filter(
                pk__in=self._assignments.values("subject_id")
            )
        if self.instance.pk and self.instance.status != Activity.Status.DRAFT:
            # Mudar a turma de uma atividade já publicada a tiraria em silêncio
            # da família que a recebeu e a entregaria à outra turma sem aviso.
            self.fields["class_group"].disabled = True
            self.fields["class_group"].help_text = (
                "A turma não muda depois da publicação. Para outra turma, "
                "crie uma nova atividade."
            )

    def clean(self):
        cleaned = super().clean()
        class_group = cleaned.get("class_group")
        subject = cleaned.get("subject")
        published = cleaned.get("published_date") or timezone.localdate()
        deadline = cleaned.get("deadline")

        # Os querysets acima restringem turma e disciplina isoladamente, o que
        # ainda permitiria combinar uma turma de uma atribuição com a
        # disciplina de outra. O par é conferido aqui, no servidor.
        if (
            class_group
            and subject
            and self.user
            and self.user.role == Role.PROFESSOR.value
        ):
            if not TeacherAssignment.objects.filter(
                teacher=self.user,
                school=self.school,
                class_group=class_group,
                subject=subject,
            ).exists():
                raise forms.ValidationError(
                    f"Você não tem atribuição de {subject} na turma "
                    f"{class_group}. Escolha uma combinação da sua atribuição."
                )

        if deadline and deadline < published:
            self.add_error(
                "deadline",
                "A data de entrega não pode ser anterior à data de publicação.",
            )
        return cleaned

    def clean_published_date(self):
        return self.cleaned_data.get("published_date") or timezone.localdate()


class GroupWorkForm(forms.ModelForm):
    attachments = MultipleFileField(
        label="Arquivos de apoio",
        required=False,
        validators=[validate_attachment, validate_attachment_content],
        help_text=(
            f"Opcional. Até {MAX_ATTACHMENT_SIZE_MB} MB por arquivo. "
            "PDF, imagem, documento, planilha ou apresentação."
        ),
    )

    class Meta:
        model = GroupWork
        fields = [
            "class_group",
            "subject",
            "title",
            "description",
            "objectives",
            "guidelines",
            "materials",
            "presentation",
            "published_date",
            "deadline",
            "delivery_mode",
            "notes",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
            "objectives": forms.Textarea(attrs={"rows": 2}),
            "guidelines": forms.Textarea(attrs={"rows": 2}),
            "materials": forms.Textarea(attrs={"rows": 2}),
            "notes": forms.Textarea(attrs={"rows": 2}),
            "published_date": forms.DateInput(format=r"%Y-%m-%d", attrs={"type": "date"}),
            "deadline": forms.DateInput(format=r"%Y-%m-%d", attrs={"type": "date"}),
        }
        labels = {
            "class_group": "Turma",
            "subject": "Disciplina",
            "title": "Título do trabalho",
            "description": "O que deve ser feito",
            "objectives": "Objetivos pedagógicos",
            "guidelines": "Orientações e critérios de avaliação",
            "materials": "Materiais necessários",
            "presentation": "Forma de apresentação ou entrega",
            "published_date": "Data de publicação",
            "deadline": "Prazo de entrega",
            "delivery_mode": "Registro da entrega",
            "notes": "Observações complementares",
        }
        help_texts = {
            "description": "É o texto que o estudante e a família leem.",
            "published_date": "A família passa a ver o trabalho a partir desta data.",
        }

    def __init__(self, *args, user=None, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.school = school
        self.fields["published_date"].required = False
        if not self.instance.pk:
            self.fields["published_date"].initial = timezone.localdate()
        self.fields["title"].required = True
        self.fields["description"].required = True
        # Só título e enunciado são exigidos: o prompt pede para não obrigar
        # campo que a atividade não precisa.
        for nome in ("objectives", "guidelines", "materials", "presentation", "notes"):
            self.fields[nome].required = False
        if school:
            self.fields["class_group"].queryset = ClassGroup.objects.filter(
                school=school
            ).select_related("school_year")
            self.fields["subject"].queryset = school.subjects.all()
        if user and user.role == Role.PROFESSOR.value:
            assigned = TeacherAssignment.objects.filter(teacher=user, school=school)
            self.fields["class_group"].queryset = ClassGroup.objects.filter(
                pk__in=assigned.values("class_group_id")
            ).select_related("school_year")
            self.fields["subject"].queryset = school.subjects.filter(
                pk__in=assigned.values("subject_id")
            )
        if self.instance.pk:
            # Trocar a turma depois de formar os grupos deixaria integrantes de
            # outra turma no trabalho. A turma fica travada após a criação.
            self.fields["class_group"].disabled = True
            self.fields["class_group"].help_text = (
                "A turma não muda depois da criação, para os grupos não "
                "ficarem com estudantes de outra turma."
            )

    def clean(self):
        cleaned = super().clean()
        class_group = cleaned.get("class_group") or getattr(
            self.instance, "class_group", None
        )
        subject = cleaned.get("subject")
        published = cleaned.get("published_date") or timezone.localdate()
        deadline = cleaned.get("deadline")

        # Os querysets restringem turma e disciplina isoladamente; o PAR é
        # conferido aqui, no servidor.
        if (
            class_group
            and subject
            and self.user
            and self.user.role == Role.PROFESSOR.value
        ):
            if not TeacherAssignment.objects.filter(
                teacher=self.user,
                school=self.school,
                class_group=class_group,
                subject=subject,
            ).exists():
                raise forms.ValidationError(
                    f"Você não tem atribuição de {subject} na turma "
                    f"{class_group}. Escolha uma combinação da sua atribuição."
                )

        if deadline and deadline < published:
            self.add_error(
                "deadline", "O prazo não pode ser anterior à data de publicação."
            )
        return cleaned

    def clean_published_date(self):
        return self.cleaned_data.get("published_date") or timezone.localdate()


class WorkGroupForm(forms.Form):
    """Criação de um grupo dentro do trabalho."""

    name = forms.CharField(
        label="Nome do grupo",
        max_length=80,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: Grupo 1, Equipe Azul"}),
    )

    def __init__(self, *args, group_work=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.group_work = group_work

    def clean_name(self):
        nome = self.cleaned_data["name"].strip()
        if self.group_work and self.group_work.groups.filter(name__iexact=nome).exists():
            raise forms.ValidationError("Já existe um grupo com este nome.")
        return nome


class GroupWorkCancelForm(forms.Form):
    """Cancelamento exige motivo: o trabalho fica no histórico escolar."""

    cancel_reason = forms.CharField(
        label="Motivo do cancelamento",
        max_length=255,
        widget=forms.TextInput(
            attrs={"placeholder": "Ex.: conteúdo adiado para o próximo bimestre"}
        ),
        help_text="Fica visível à família junto do trabalho cancelado.",
    )


class ActivityCancelForm(forms.Form):
    """Cancelamento exige motivo: a atividade continua no histórico escolar."""

    cancel_reason = forms.CharField(
        label="Motivo do cancelamento",
        max_length=255,
        widget=forms.TextInput(
            attrs={"placeholder": "Ex.: aula remarcada; conteúdo adiado"}
        ),
        help_text="Fica visível à família junto da atividade cancelada.",
    )


class SubmissionForm(forms.ModelForm):
    class Meta:
        model = Submission
        fields = ["status", "comment"]
        labels = {"status": "Situação", "comment": "Observação"}


class AttendanceBatchForm(forms.Form):
    """Registro de frequência em lote: um campo por estudante, com default 'presente'."""

    STATUS_MAP = [("presente", "Presente"), ("atraso", "Atraso"), ("falta", "Falta")]
    date = forms.DateField(label="Data da chamada", widget=forms.HiddenInput)

    def __init__(self, *args, class_group=None, students=None, date=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.class_group = class_group
        self.students = students or []
        from .models import AttendanceRecord

        existing = {}
        if class_group is not None and date is not None:
            existing = {
                r.student_id: r
                for r in AttendanceRecord.objects.filter(
                    class_group=class_group, date=date
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
                widget=forms.Select(attrs={"class": "form-select form-select-sm",
                                           "aria-label": f"Situação de {s.full_name}"}),
            )
            self.rows.append((s, field_name))

    def clean_date(self):
        value = self.cleaned_data["date"]
        if value > timezone.localdate():
            raise forms.ValidationError("Não é possível registrar frequência em data futura.")
        return value


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
        class_group = cleaned.get("class_group")
        if class_group and self.student and not self.student.enrollments.filter(
            class_group=class_group
        ).exists():
            self.add_error(
                "class_group", "O estudante não possui matrícula nesta turma."
            )
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