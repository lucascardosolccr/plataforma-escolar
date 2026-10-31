"""Formulários do pré-cadastro pela família, da análise pela secretaria e
das configurações de cadastro."""

from django import forms
from django.utils import timezone

from apps.academics.models import ClassGroup, SchoolYear
from apps.core.uploads import validate_attachment_content, validate_photo

from .models import ApplicationDocument, RegistrationSettings, StudentApplication

DATE = forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})


class _EnabledFieldsMixin:
    """Remove os campos opcionais que a escola não pede à família."""

    optional = ()

    def __init__(self, *args, enabled=(), **kwargs):
        super().__init__(*args, **kwargs)
        for name in self.optional:
            if name not in enabled and name in self.fields:
                del self.fields[name]


class ApplicationStudentForm(_EnabledFieldsMixin, forms.ModelForm):
    optional = ("desired_turn",)

    class Meta:
        model = StudentApplication
        fields = ["school_year", "first_name", "last_name", "birth_date", "desired_grade", "desired_turn"]
        widgets = {"birth_date": DATE}
        labels = {
            "school_year": "Ano letivo em que vai estudar",
            "first_name": "Nome do estudante",
            "last_name": "Sobrenome",
            "birth_date": "Data de nascimento",
            "desired_grade": "Ano/série em que vai estudar",
            "desired_turn": "Turno desejado",
        }
        help_texts = {"desired_grade": "Por exemplo: 1º ano, 5º ano, Educação Infantil."}

    def __init__(self, *args, years=(), **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("first_name", "birth_date", "desired_grade"):
            self.fields[name].required = True
        # Só pergunta o ano quando a escola abriu mais de um; com um só, a
        # tela grava esse ano sem perguntar.
        if len(years) > 1:
            self.fields["school_year"].queryset = SchoolYear.objects.filter(pk__in=[y.pk for y in years])
            self.fields["school_year"].required = True
            self.fields["school_year"].empty_label = "Escolha…"
        else:
            del self.fields["school_year"]

    def clean_birth_date(self):
        value = self.cleaned_data["birth_date"]
        today = timezone.localdate()
        if value > today:
            raise forms.ValidationError("A data de nascimento não pode ser futura.")
        if value.year < today.year - 30:
            raise forms.ValidationError("Confira a data: o estudante teria mais de 30 anos.")
        return value


class ApplicationContactForm(_EnabledFieldsMixin, forms.ModelForm):
    optional = ("phone", "address", "relation", "school_notes")

    class Meta:
        model = StudentApplication
        fields = ["relation", "phone", "address", "school_notes"]
        labels = {
            "relation": "Seu parentesco com o estudante",
            "phone": "Telefone para a escola falar com você",
            "address": "Endereço",
            "school_notes": "Algo que a escola precisa saber?",
        }
        widgets = {"school_notes": forms.Textarea(attrs={"rows": 3})}


class ApplicationPhotoForm(forms.Form):
    """Só valida o arquivo: quem grava é ``core.photos.save_photo``, depois de
    recortar, reduzir e tirar os metadados."""

    photo = forms.ImageField(
        required=False, label="Fotografia do estudante", validators=[validate_photo],
        widget=forms.FileInput(attrs={"accept": ".jpg,.jpeg,.png,.webp", "data-photo-crop": ""}),
        help_text="Rosto de frente, fundo claro. JPG, PNG ou WEBP, até 2 MB.",
    )


class ApplicationDocumentForm(forms.ModelForm):
    class Meta:
        model = ApplicationDocument
        fields = ["kind", "file"]
        labels = {"kind": "Tipo de documento", "file": "Arquivo"}
        help_texts = {"file": "PDF ou imagem, até 10 MB."}

    def clean_file(self):
        f = self.cleaned_data["file"]
        validate_attachment_content(f)
        return f


class ReviewForm(forms.Form):
    """Decisão da secretaria sobre um pré-cadastro."""

    decision = forms.ChoiceField(
        choices=[("aprovar", "Aprovar"), ("correcao", "Pedir correção"), ("recusar", "Recusar")],
        widget=forms.RadioSelect, label="Decisão",
    )
    target = forms.ChoiceField(required=False, label="Ficha do estudante", widget=forms.RadioSelect)
    class_group = forms.ModelChoiceField(
        queryset=ClassGroup.objects.none(), required=False, label="Matricular na turma (opcional)",
        help_text="Em branco: cria a ficha e o vínculo da família, sem matrícula. Matricule depois.",
    )
    code = forms.CharField(max_length=30, required=False, label="Código do aluno (opcional)")
    note = forms.CharField(
        required=False, label="Mensagem para a família", widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Obrigatória ao pedir correção ou recusar.",
    )

    def __init__(self, *args, school=None, matches=(), year=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.school = school
        choices = [("nova", "Criar uma ficha nova")] + [
            (str(s.pk), f"Usar a ficha já existente: {s.full_name}"
                        f"{' · nasc. ' + s.birth_date.strftime('%d/%m/%Y') if s.birth_date else ''}"
                        f"{' · código ' + s.code if s.code else ''}")
            for s in matches
        ]
        self.fields["target"].choices = choices
        self.fields["target"].initial = "nova"
        qs = ClassGroup.objects.filter(school=school)
        if year:
            qs = qs.filter(school_year=year)
        self.fields["class_group"].queryset = qs.order_by("name")

    def clean(self):
        data = super().clean()
        decision = data.get("decision")
        if decision in ("correcao", "recusar") and not (data.get("note") or "").strip():
            self.add_error("note", "Explique à família o que corrigir ou por que foi recusado.")
        if decision == "aprovar" and not data.get("target"):
            data["target"] = "nova"
        code = (data.get("code") or "").strip()
        if decision == "aprovar" and code:
            from .models import Student

            dup = Student.objects.filter(school=self.school, code=code)
            if data.get("target") not in (None, "", "nova"):
                dup = dup.exclude(pk=data["target"])
            if dup.exists():
                self.add_error("code", "Já existe um aluno com este código.")
        data["code"] = code
        return data


class RegistrationSettingsForm(forms.ModelForm):
    family_fields = forms.MultipleChoiceField(
        choices=RegistrationSettings.OPTIONAL_FIELDS, required=False,
        widget=forms.CheckboxSelectMultiple, label="O que a família preenche, além de nome, nascimento e ano/série",
    )

    class Meta:
        model = RegistrationSettings
        fields = ["family_mode", "family_fields", "allow_correction_requests", "opens_on", "closes_on"]
        widgets = {"family_mode": forms.RadioSelect, "opens_on": DATE, "closes_on": DATE}
        labels = {"opens_on": "Período de cadastro: abre em", "closes_on": "Fecha em"}
        help_texts = {"opens_on": "Em branco: sem data de abertura.", "closes_on": "Em branco: sem data de fechamento."}

    open_years = forms.ModelMultipleChoiceField(
        queryset=SchoolYear.objects.none(), required=False, widget=forms.CheckboxSelectMultiple,
        label="Anos letivos que aceitam novos pré-cadastros",
        help_text="Com mais de um marcado, a família escolhe o ano no pré-cadastro.",
    )

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["open_years"].queryset = SchoolYear.objects.filter(school=school).order_by("-name")
        self.initial["family_fields"] = self.instance.fields_list
        self.initial["open_years"] = [y.pk for y in self.instance.open_years()] if school else []

    def clean_family_fields(self):
        return ",".join(self.cleaned_data["family_fields"])

    def clean(self):
        data = super().clean()
        if data.get("opens_on") and data.get("closes_on") and data["closes_on"] < data["opens_on"]:
            self.add_error("closes_on", "O fechamento não pode ser antes da abertura.")
        if data.get("family_mode") == RegistrationSettings.MODE_FULL and not data.get("open_years"):
            self.add_error("open_years", "Marque pelo menos um ano letivo para receber pré-cadastros.")
        return data
