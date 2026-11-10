from django import forms
from django.utils import timezone

from apps.academics.models import ClassGroup, SchoolYear

from .models import Answer, Campaign

DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class CampaignForm(forms.ModelForm):
    class Meta:
        model = Campaign
        fields = ["title", "target_year", "class_groups", "opens_on", "deadline", "message", "terms"]
        widgets = {"opens_on": DATE, "deadline": DATE, "class_groups": forms.CheckboxSelectMultiple(),
                   "message": forms.Textarea(attrs={"rows": 4}), "terms": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, school, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["target_year"].queryset = SchoolYear.objects.filter(school=school).order_by("-name")
        current = ClassGroup.objects.filter(school=school, school_year__is_current=True)
        self.fields["class_groups"].queryset = (current if current.exists() else
                                                ClassGroup.objects.filter(school=school)).order_by("name")
        if not self.instance.pk:
            self.fields["opens_on"].initial = timezone.localdate()

    def clean(self):
        c = super().clean()
        opens, deadline, year = c.get("opens_on"), c.get("deadline"), c.get("target_year")
        if opens and deadline and deadline < opens:
            self.add_error("deadline", "O prazo precisa ser depois do início.")
        if deadline and deadline < timezone.localdate() and "deadline" in self.changed_data:
            self.add_error("deadline", "Essa data já passou.")
        if year and year.is_current:
            self.add_error("target_year", "Escolha o ano que vem, não o ano letivo atual.")
        if year and any(cg.school_year_id == year.pk for cg in c.get("class_groups") or []):
            self.add_error("class_groups", "Escolha turmas do ano atual (de onde os estudantes saem).")
        return c


class AnswerForm(forms.Form):
    decision = forms.ChoiceField(label="O estudante continua na escola no ano que vem?", choices=Answer.Decision.choices,
                                 widget=forms.RadioSelect)
    reason = forms.ChoiceField(label="Motivo", required=False,
                               choices=[("", "Escolha")] + list(Answer.Reason.choices),
                               help_text="Só se não for continuar. Ajuda a escola a entender e melhorar.")
    reason_text = forms.CharField(label="Comentário", required=False, max_length=300,
                                  help_text="Opcional. Ex.: turno preferido, dúvida para a secretaria.")
    data_ok = forms.BooleanField(label="Os dados de contato estão certos", required=False)
    data_changes = forms.CharField(label="O que mudou no cadastro", required=False, max_length=1000,
                                   widget=forms.Textarea(attrs={"rows": 3}),
                                   help_text="Endereço, telefone, quem busca, responsável, saúde. A secretaria atualiza.")
    accept = forms.BooleanField(label="Li e concordo com o termo acima", required=False)
    on_behalf = forms.CharField(label="Quem respondeu no balcão", required=False, max_length=150,
                                help_text="Nome do responsável que veio à secretaria.")

    def __init__(self, *args, terms=False, in_person=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.terms, self.in_person = terms, in_person
        if not terms:
            del self.fields["accept"]
        if not in_person:
            del self.fields["on_behalf"]

    def clean(self):
        c = super().clean()
        stay = c.get("decision") == Answer.Decision.STAY
        if c.get("decision") == Answer.Decision.LEAVE and not c.get("reason"):
            self.add_error("reason", "Escolha o motivo.")
        if stay and not c.get("data_ok") and not (c.get("data_changes") or "").strip():
            self.add_error("data_changes", "Marque que os dados estão certos ou conte o que mudou.")
        if stay and self.terms and not c.get("accept"):
            self.add_error("accept", "Para confirmar a continuidade, é preciso concordar com o termo.")
        if self.in_person and not (c.get("on_behalf") or "").strip():
            self.add_error("on_behalf", "Diga quem respondeu.")
        return c
