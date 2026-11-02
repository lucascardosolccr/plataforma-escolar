import re

from django import forms
from django.core.exceptions import ValidationError

from apps.curriculum.models import CurriculumItem, component_for, year_for

from .models import MasteryScale, Question, SkillObservation

CODE_RE = re.compile(r"[A-Za-z0-9.\-]+")


def skill_choices(evaluation_or_pair):
    """Habilidades sugeridas: as já ligadas à avaliação e as do componente e ano da turma."""
    if hasattr(evaluation_or_pair, "curriculum"):
        ev = evaluation_or_pair
        cg, subject, school = ev.class_group, ev.subject, ev.school
        first = list(ev.curriculum.all())
    else:
        cg, subject = evaluation_or_pair
        school, first = cg.school, []
    comp, year = component_for(subject), year_for(cg)
    rest = list(CurriculumItem.for_pair(school, comp, year).order_by("code")) if comp else []
    seen, out = set(), []
    for it in first + rest:
        if it.pk not in seen:
            seen.add(it.pk)
            out.append(it)
    return out


class QuestionForm(forms.ModelForm):
    main_skill = forms.ModelChoiceField(queryset=CurriculumItem.objects.none(), label="Habilidade principal")
    secondary_codes = forms.CharField(label="Habilidades secundárias (códigos)", required=False, max_length=200,
                                      help_text="Separados por vírgula. Ex.: EF06MA02, EF06MA03")

    class Meta:
        model = Question
        fields = ["number", "label", "max_points", "complexity", "evidence_type", "criteria", "expected_concepts"]
        widgets = {"criteria": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, evaluation=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.evaluation = evaluation
        items = skill_choices(evaluation)
        self.fields["main_skill"].queryset = CurriculumItem.objects.filter(pk__in=[i.pk for i in items])
        self.fields["main_skill"].label_from_instance = lambda i: f"{i.code} — {i.text[:110]}"
        self.order_fields(["number", "label", "main_skill", "secondary_codes", "max_points", "complexity",
                           "evidence_type", "criteria", "expected_concepts"])
        if self.instance.pk:
            links = list(self.instance.questionskill_set.select_related("item"))
            main = [l.item for l in links if l.role == "principal"]
            if main:
                self.initial["main_skill"] = main[0].pk
            self.initial["secondary_codes"] = ", ".join(l.item.code for l in links if l.role == "secundaria")
        else:
            n = (evaluation.questions.order_by("-number").values_list("number", flat=True).first() or 0) + 1
            self.initial["number"] = n

    def clean_number(self):
        n = self.cleaned_data["number"]
        if Question.objects.filter(evaluation=self.evaluation, number=n).exclude(pk=self.instance.pk).exists():
            raise ValidationError("Já existe uma questão com este número.")
        return n

    def clean_max_points(self):
        v = self.cleaned_data["max_points"]
        if v is None or v <= 0:
            raise ValidationError("Use um valor maior que zero.")
        return v

    def clean_secondary_codes(self):
        codes = [c.upper() for c in CODE_RE.findall(self.cleaned_data.get("secondary_codes") or "")]
        found = list(CurriculumItem.objects.filter(CurriculumItem.visible_q(self.evaluation.school), code__in=codes,
                                                   active=True))
        missing = sorted(set(codes) - {i.code for i in found})
        if missing:
            raise ValidationError(f"Código não encontrado: {', '.join(missing)}.")
        return found


class ObservationForm(forms.Form):
    item = forms.ModelChoiceField(queryset=CurriculumItem.objects.none(), label="Habilidade")
    level = forms.TypedChoiceField(choices=SkillObservation.Level.choices, coerce=int, label="O que foi observado")
    context = forms.CharField(label="Situação observada", max_length=200,
                              help_text="Ex.: leitura compartilhada, resolução no quadro, experimento em grupo.")
    observed_on = forms.DateField(label="Data", widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    note = forms.CharField(label="Comentário pedagógico (opcional)", required=False,
                           widget=forms.Textarea(attrs={"rows": 2}))
    students = forms.MultipleChoiceField(label="Estudantes", widget=forms.CheckboxSelectMultiple)
    activity = forms.ModelChoiceField(queryset=None, required=False, label="Atividade relacionada (opcional)")
    evaluation = forms.ModelChoiceField(queryset=None, required=False, label="Avaliação relacionada (opcional)")
    recheck_on = forms.DateField(label="Reavaliar em (opcional)", required=False,
                                 widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
                                 help_text="Aparece nas pendências nesse dia, se não houver evidência nova até lá.")

    def __init__(self, *args, pair=None, students=(), **kwargs):
        from apps.pedagogy.models import Activity, Evaluation

        super().__init__(*args, **kwargs)
        items = skill_choices(pair)
        self.fields["item"].queryset = CurriculumItem.objects.filter(pk__in=[i.pk for i in items])
        self.fields["item"].label_from_instance = lambda i: f"{i.code} — {i.text[:110]}"
        self.fields["students"].choices = [(str(s.pk), s.full_name) for s in students]
        self.fields["level"].label = "O que foi observado (nível de todos os marcados)"
        # Revisão individual antes de confirmar (Prompt 18 §7): cada estudante pode ter
        # um nível diferente do nível de todos.
        own = [("", "o nível de todos")] + list(SkillObservation.Level.choices)
        self.students_list = list(students)
        for s in self.students_list:
            self.fields[f"lv_{s.pk}"] = forms.TypedChoiceField(
                choices=own, coerce=int, empty_value=None, required=False, label=f"Nível de {s.full_name}")
        cg, subject = pair
        # as 60 mais recentes; o filtro por ids mantém o queryset filtrável (validação do ModelChoiceField)
        acts = Activity.objects.filter(class_group=cg, subject=subject).exclude(status="cancelada")
        evals = Evaluation.objects.filter(class_group=cg, subject=subject)
        self.fields["activity"].queryset = acts.filter(
            pk__in=list(acts.order_by("-class_date").values_list("pk", flat=True)[:60])).order_by("-class_date")
        self.fields["evaluation"].queryset = evals.filter(
            pk__in=list(evals.order_by("-date").values_list("pk", flat=True)[:60])).order_by("-date")

    def main_fields(self):
        """Campos comuns a todos; estudantes e níveis individuais vão na tabela própria."""
        return [f for f in self if f.name != "students" and not f.name.startswith("lv_")]

    def level_for(self, student_id):
        return self.cleaned_data.get(f"lv_{student_id}") or self.cleaned_data["level"]

    def clean_observed_on(self):
        from django.utils import timezone

        d = self.cleaned_data["observed_on"]
        if d > timezone.localdate():
            raise ValidationError("A data não pode estar no futuro.")
        return d

    def clean(self):
        data = super().clean()
        if data.get("recheck_on") and data.get("observed_on") and data["recheck_on"] <= data["observed_on"]:
            self.add_error("recheck_on", "A reavaliação precisa ser depois da data da observação.")
        return data


class ScaleForm(forms.ModelForm):
    class Meta:
        model = MasteryScale
        fields = ["t1", "t2", "t3", "min_evidence", "min_weight", "half_life_days", "stale_days", "share_with_family"]

    def clean(self):
        data = super().clean()
        t1, t2, t3 = data.get("t1"), data.get("t2"), data.get("t3")
        if None not in (t1, t2, t3) and not (0 < t1 < t2 < t3 <= 1):
            raise ValidationError("Os cortes precisam crescer: 0 < dificuldade < desenvolvimento < consolidação ≤ 1.")
        if data.get("min_evidence") is not None and data["min_evidence"] < 1:
            self.add_error("min_evidence", "Use pelo menos 1.")
        return data
