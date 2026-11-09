import datetime

from django import forms
from django.utils import timezone

from .models import AuthorizedPickup, DepartureNotice, HealthRecord

DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
TIME = forms.TimeInput(attrs={"type": "time"}, format="%H:%M")
CONTACT_ROWS = 3


class HealthForm(forms.ModelForm):
    consent = forms.BooleanField(required=True)

    class Meta:
        model = HealthRecord
        fields = ["allergies", "diet", "diet_notes", "conditions", "medications", "crisis_plan", "insurance",
                  "emergency_transport"]
        widgets = {f: forms.Textarea(attrs={"rows": 2}) for f in
                   ("allergies", "conditions", "medications", "crisis_plan")}

    def __init__(self, *args, family=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["consent"].label = (
            "Autorizo a escola a guardar e usar estas informações de saúde para o cuidado do meu filho na escola "
            "(LGPD, art. 11 e art. 14)." if family else
            "A família entregou estas informações por escrito e autorizou o uso para o cuidado do estudante.")

    def clean(self):
        c = super().clean()
        if c.get("diet") == HealthRecord.Diet.OTHER and not (c.get("diet_notes") or "").strip():
            self.add_error("diet_notes", "Descreva a restrição alimentar.")
        return c


class ContactForm(forms.Form):
    name = forms.CharField(label="Nome", max_length=120, required=False)
    relationship = forms.CharField(label="Parentesco ou relação", max_length=60, required=False)
    phone = forms.CharField(label="Telefone", max_length=30, required=False)

    def clean(self):
        c = super().clean()
        filled = [bool((c.get(k) or "").strip()) for k in ("name", "relationship", "phone")]
        if any(filled) and not all(filled):
            raise forms.ValidationError("Preencha nome, parentesco e telefone, ou deixe a linha em branco.")
        return c


def contact_forms(data=None, initial=()):
    initial = list(initial) + [{}] * (CONTACT_ROWS - len(initial))
    return [ContactForm(data, prefix=f"c{i}", initial=initial[i]) for i in range(CONTACT_ROWS)]


class PickupForm(forms.ModelForm):
    class Meta:
        model = AuthorizedPickup
        fields = ["name", "relationship", "document_hint", "phone", "valid_until"]
        widgets = {"valid_until": DATE}

    def clean_valid_until(self):
        d = self.cleaned_data.get("valid_until")
        if d and d < timezone.localdate():
            raise forms.ValidationError("A data já passou.")
        return d


class NoticeForm(forms.ModelForm):
    class Meta:
        model = DepartureNotice
        fields = ["day", "time", "guardian_pickup", "pickup", "reason"]
        widgets = {"day": DATE, "time": TIME}

    def __init__(self, *args, student=None, **kwargs):
        super().__init__(*args, **kwargs)
        today = timezone.localdate()
        self.fields["pickup"].queryset = AuthorizedPickup.objects.filter(
            student=student, revoked_at__isnull=True).exclude(valid_until__lt=today)
        self.fields["pickup"].required = False
        self.fields["pickup"].empty_label = "—"
        self.fields["pickup"].help_text = "Pessoa da lista de autorizados. Para outra pessoa, inclua-a na lista antes."

    def clean(self):
        c = super().clean()
        if c.get("day") and c["day"] < timezone.localdate():
            self.add_error("day", "Escolha hoje ou um dia futuro.")
        if c.get("day") and c["day"] > timezone.localdate() + datetime.timedelta(days=60):
            self.add_error("day", "Avise com até 60 dias de antecedência.")
        if not c.get("guardian_pickup") and not c.get("pickup"):
            raise forms.ValidationError("Diga quem vai buscar: você ou uma pessoa da lista de autorizados.")
        if c.get("guardian_pickup") and c.get("pickup"):
            raise forms.ValidationError("Escolha só uma opção: você ou a pessoa da lista.")
        return c

