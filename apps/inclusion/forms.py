import datetime

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import (SupportCase, SupportCategory, SupportDocument, SupportNeed, SupportPlan, SupportPlanReview,
                     SupportRequest, SupportSettings)
from .services import validate_upload

DATE = forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})


class DocumentFieldsMixin(forms.Form):
    """Arquivo e dados do documento (opcional na declaração)."""

    file = forms.FileField(label="Documento (PDF, JPG ou PNG)", required=False,
                           widget=forms.ClearableFileInput(attrs={"accept": ".pdf,.jpg,.jpeg,.png"}))
    kind = forms.ChoiceField(label="Tipo de documento", choices=SupportDocument.Kind.choices, required=False)
    issued_on = forms.DateField(label="Data de emissão", required=False, widget=DATE)
    issuer = forms.CharField(label="Profissional ou instituição que emitiu", required=False, max_length=200)

    def clean_issued_on(self):
        d = self.cleaned_data.get("issued_on")
        if d and d > timezone.localdate():
            raise ValidationError("A data de emissão não pode estar no futuro.")
        return d

    def check_file(self, school):
        f = self.cleaned_data.get("file")
        if f:
            try:
                validate_upload(f, school)
            except ValidationError as e:
                self.add_error("file", e)
            f.seek(0)
        return f


class DeclarationForm(DocumentFieldsMixin, forms.ModelForm):
    """O que o responsável informa à escola."""

    understood = forms.BooleanField(
        label="Li a orientação sobre a finalidade, quem pode consultar e como a escola usa estas informações.",
        required=True)

    class Meta:
        model = SupportCase
        fields = ["has_report", "declared_categories", "family_notes"]
        widgets = {"declared_categories": forms.CheckboxSelectMultiple,
                   "has_report": forms.RadioSelect,
                   "family_notes": forms.Textarea(attrs={"rows": 4})}
        labels = {
            "has_report": "O estudante possui laudo ou relatório de profissional?",
            "declared_categories": "Há alguma condição ou necessidade que mereça atenção da escola? (opcional)",
            "family_notes": "Informações complementares",
        }
        help_texts = {
            "family_notes": "O que ajuda o estudante na escola, o que dificulta, apoios que já usa. Só a equipe "
                            "pedagógica (coordenação e direção) lê este texto.",
        }

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.school = school
        self.fields["declared_categories"].queryset = SupportCategory.ensure_defaults(school)
        self.fields["declared_categories"].required = False
        self.fields["has_report"].choices = [c for c in SupportCase.HasReport.choices if c[0]]
        self.fields["has_report"].required = True
        self.fields["kind"].initial = SupportDocument.Kind.REPORT
        self.order_fields(["has_report", "declared_categories", "family_notes", "file", "kind", "issued_on",
                           "issuer", "understood"])

    def clean(self):
        data = super().clean()
        self.check_file(self.school)
        return data


class DocumentForm(DocumentFieldsMixin):
    description = forms.CharField(label="Descrição", required=False, max_length=300,
                                  help_text="Ex.: relatório de acompanhamento de 2026.")

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.school = school
        self.fields["file"].required = True
        self.fields["kind"].required = True
        self.fields["kind"].initial = SupportDocument.Kind.REPORT

    def clean(self):
        data = super().clean()
        self.check_file(self.school)
        return data


class RequestForm(forms.ModelForm):
    class Meta:
        model = SupportRequest
        fields = ["message", "due_on"]
        widgets = {"message": forms.Textarea(attrs={"rows": 4}), "due_on": DATE}
        help_texts = {"message": "Seja específico: qual documento ou esclarecimento e para quê. A família lê este texto."}

    def clean_due_on(self):
        d = self.cleaned_data.get("due_on")
        if d and d < timezone.localdate():
            raise ValidationError("O prazo não pode estar no passado.")
        return d


class ResponseForm(DocumentFieldsMixin):
    response = forms.CharField(label="Resposta à escola", widget=forms.Textarea(attrs={"rows": 4}))

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.school = school
        self.order_fields(["response", "file", "kind", "issued_on", "issuer"])

    def clean(self):
        data = super().clean()
        self.check_file(self.school)
        return data


class DocumentReviewForm(forms.Form):
    decision = forms.ChoiceField(label="Resultado", choices=[
        (SupportDocument.Status.ANALYZED, "Documento analisado"),
        (SupportDocument.Status.ARCHIVED, "Arquivar (não é mais usado)"),
    ])
    note = forms.CharField(label="Registro da análise (interno, a família não vê)", required=False,
                           widget=forms.Textarea(attrs={"rows": 3}))


class AnalysisForm(forms.ModelForm):
    """Validação conforme procedimento institucional e base legal."""

    status = forms.ChoiceField(label="Situação da ficha", choices=[
        (SupportCase.Status.ANALYZED, SupportCase.Status.ANALYZED.label),
        (SupportCase.Status.UPDATED, SupportCase.Status.UPDATED.label),
        (SupportCase.Status.ARCHIVED, SupportCase.Status.ARCHIVED.label),
    ])
    note = forms.CharField(label="Registro para o histórico", required=False,
                           widget=forms.Textarea(attrs={"rows": 2}),
                           help_text="Aparece no histórico da ficha, inclusive para a família.")

    class Meta:
        model = SupportCase
        fields = ["validated_categories", "validation_basis", "legal_basis", "legal_basis_notes"]
        widgets = {"validated_categories": forms.CheckboxSelectMultiple,
                   "validation_basis": forms.Textarea(attrs={"rows": 3}),
                   "legal_basis_notes": forms.Textarea(attrs={"rows": 2})}
        help_texts = {
            "validated_categories": "Marque só o que foi validado pelo procedimento da escola. Não é diagnóstico: "
                                    "a escola não diagnostica.",
            "validation_basis": "Qual procedimento foi seguido (estudo de caso, documento analisado, reunião).",
            "legal_basis": "Definida com o encarregado de dados. O consentimento não é a única base possível.",
        }

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["validated_categories"].queryset = SupportCategory.objects.filter(school=school)
        self.fields["validated_categories"].required = False

    def clean(self):
        data = super().clean()
        if data.get("validated_categories") and not (data.get("validation_basis") or "").strip():
            self.add_error("validation_basis", "Descreva o procedimento que fundamenta a validação.")
        return data


class NeedForm(forms.ModelForm):
    class Meta:
        model = SupportNeed
        fields = ["area", "description", "resources", "classroom_strategies", "care_notes", "share_with_teachers",
                  "active"]
        widgets = {f: forms.Textarea(attrs={"rows": 3}) for f in
                   ("description", "resources", "classroom_strategies", "care_notes")}
        help_texts = {
            "description": "Descreva a necessidade observada no contexto escolar, não um diagnóstico.",
            "share_with_teachers": "Os professores do estudante veem área, recursos, estratégias e cuidados.",
        }


class PlanForm(forms.ModelForm):
    class Meta:
        model = SupportPlan
        fields = ["status", "starts_on", "review_due", "responsibles"] + [n for n, _ in SupportPlan.PLAN_FIELDS]
        widgets = {"starts_on": DATE, "review_due": DATE, "responsibles": forms.CheckboxSelectMultiple,
                   **{n: forms.Textarea(attrs={"rows": 3}) for n, _ in SupportPlan.PLAN_FIELDS}}
        help_texts = {"teacher_summary": "Texto curto, sem diagnóstico: o que cada professor precisa saber e fazer.",
                      "family_participation": "Como o estudante e a família participaram (Decreto nº 12.686/2025, "
                                              "art. 11, § 3º)."}

    def __init__(self, *args, responsible_qs=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["responsibles"].queryset = responsible_qs
        self.fields["responsibles"].required = False
        self.fields["responsibles"].label_from_instance = lambda u: f"{u.get_full_name() or u.username} — {u.role_label}"
        if not self.instance.pk:
            today = timezone.localdate()
            self.fields["starts_on"].initial = today
            self.fields["review_due"].initial = today + datetime.timedelta(days=180)

    def clean(self):
        data = super().clean()
        start, due = data.get("starts_on"), data.get("review_due")
        if start and due:
            if due < start:
                self.add_error("review_due", "A revisão não pode ser antes do início.")
            elif due > start + datetime.timedelta(days=366):
                self.add_error("review_due", "A revisão deve acontecer em até um ano (Portaria MEC nº 421/2026, "
                                             "art. 7º, § 3º).")
        if data.get("status") == SupportPlan.Status.ACTIVE and not any(
                (data.get(n) or "").strip() for n in ("objectives", "strategies", "curricular_measures")):
            self.add_error("status", "Para ficar vigente, o plano precisa de objetivos, estratégias ou medidas de "
                                     "acessibilidade curricular.")
        return data


class PlanReviewForm(forms.ModelForm):
    class Meta:
        model = SupportPlanReview
        fields = ["kind", "happened_on", "notes"]
        widgets = {"happened_on": DATE, "notes": forms.Textarea(attrs={"rows": 3})}
        help_texts = {"kind": "A devolutiva à família aparece para o responsável."}


class CategoryForm(forms.Form):
    name = forms.CharField(label="Nova categoria", max_length=120,
                           widget=forms.TextInput(attrs={"class": "form-control"}))


class SettingsForm(forms.ModelForm):
    class Meta:
        model = SupportSettings
        fields = ["max_upload_mb", "retention_years", "contact"]

    def clean_max_upload_mb(self):
        v = self.cleaned_data["max_upload_mb"]
        if not 1 <= v <= 20:
            raise ValidationError("Use de 1 a 20 MB.")
        return v

    def clean_retention_years(self):
        v = self.cleaned_data["retention_years"]
        if not 1 <= v <= 30:
            raise ValidationError("Use de 1 a 30 anos.")
        return v
