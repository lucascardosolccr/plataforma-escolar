import csv
import io
import re

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import COMPONENTS, CurriculumItem, LearningEvidence
from .services import picker_groups

CODE_RE = re.compile(r"[A-Za-z0-9.\-]+")


class CurriculumFormMixin:
    """Acrescenta a seleção de habilidades/objetivos a um ModelForm que tem o
    campo ``curriculum`` em ``Meta.fields`` (atividade, prova, trabalho, plano).

    Chame ``self.attach_curriculum(user)`` no ``__init__``. A tela mostra as
    habilidades do componente e do ano de cada turma do professor, e o campo
    "outros códigos" aceita qualquer código do catálogo (ex.: EF67EF01).
    """

    def attach_curriculum(self, user):
        if "curriculum" not in self.fields or user is None:
            return
        selected = list(self.instance.curriculum.values_list("pk", flat=True)) if self.instance.pk else []
        field = self.fields["curriculum"]
        field.required = False
        field.queryset = CurriculumItem.objects.filter(
            CurriculumItem.visible_q(user.school)).filter(active=True) | CurriculumItem.objects.filter(pk__in=selected)
        field.widget = forms.CheckboxSelectMultiple()
        field.label = "Habilidades e objetivos curriculares"
        field.help_text = ("Marque o que esta proposta trabalha. Não é obrigatório; ajuda a acompanhar o que já foi "
                           "trabalhado e o que falta.")
        self.curriculum_school = user.school
        self.curriculum_groups = picker_groups(user, selected)
        if self.is_bound:
            self.curriculum_selected = set(self.data.getlist("curriculum")) if hasattr(self.data, "getlist") else set()
        else:
            self.curriculum_selected = {str(pk) for pk in selected}
        self.fields["curriculum_codes"] = forms.CharField(
            required=False, label="Outros códigos (BNCC ou da escola)", max_length=300,
            help_text="Separados por vírgula. Ex.: EF67EF01, EF69LP05")

    def clean_curriculum_codes(self):
        raw = self.cleaned_data.get("curriculum_codes", "")
        codes = [c.upper() for c in CODE_RE.findall(raw or "")]
        if not codes:
            return ""
        found = {i.code.upper(): i for i in CurriculumItem.objects.filter(
            CurriculumItem.visible_q(self.curriculum_school), active=True, code__in=codes)}
        missing = [c for c in codes if c not in found]
        if missing:
            raise ValidationError(f"Código não encontrado no catálogo: {', '.join(missing)}.")
        chosen = list(self.cleaned_data.get("curriculum") or [])
        ids = {i.pk for i in chosen}
        chosen += [i for i in found.values() if i.pk not in ids]
        self.cleaned_data["curriculum"] = chosen
        return ""


class EvidenceForm(forms.ModelForm):
    pair = forms.ChoiceField(label="Turma e disciplina")

    class Meta:
        model = LearningEvidence
        fields = ["item", "observed_on", "judgement", "description", "activity", "evaluation"]
        widgets = {"observed_on": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
                   "description": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, user=None, pairs=(), item_qs=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.pedagogy.models import Activity, Evaluation

        self.fields["pair"].choices = [(f"{cg.pk}:{s.pk}", f"{cg.name} — {s.name}") for cg, s in pairs]
        self.order_fields(["pair", "item", "observed_on", "judgement", "description", "activity", "evaluation"])
        self.fields["item"].queryset = item_qs if item_qs is not None else CurriculumItem.objects.none()
        self.fields["item"].label = "Habilidade ou objetivo"
        self.fields["observed_on"].initial = timezone.localdate()
        class_ids = {cg.pk for cg, _ in pairs}
        self.fields["activity"].queryset = Activity.objects.filter(class_group_id__in=class_ids, created_by=user)
        self.fields["evaluation"].queryset = Evaluation.objects.filter(class_group_id__in=class_ids, created_by=user)
        self.fields["activity"].required = self.fields["evaluation"].required = False
        self.pairs = {f"{cg.pk}:{s.pk}": (cg, s) for cg, s in pairs}

    def clean(self):
        data = super().clean()
        pair = self.pairs.get(data.get("pair"))
        if not pair:
            self.add_error("pair", "Escolha uma turma e disciplina sua.")
            return data
        cg, subject = pair
        for name in ("activity", "evaluation"):
            obj = data.get(name)
            if obj and (obj.class_group_id != cg.pk or obj.subject_id != subject.pk):
                self.add_error(name, "Escolha uma proposta da mesma turma e disciplina.")
        if data.get("observed_on") and data["observed_on"] > timezone.localdate():
            self.add_error("observed_on", "A data não pode estar no futuro.")
        self.class_group, self.subject = cg, subject
        return data


class CurriculumItemForm(forms.ModelForm):
    """Objetivo do Currículo em Movimento do DF ou objetivo próprio, cadastrado pela escola."""

    source_url = forms.URLField(label="Endereço da fonte", required=False, assume_scheme="https")
    bncc_codes = forms.CharField(label="Habilidades da BNCC relacionadas", required=False,
                                 help_text="Códigos separados por vírgula. Ex.: EF06MA01, EF06MA02")

    class Meta:
        model = CurriculumItem
        fields = ["kind", "code", "text", "component", "years", "source", "source_url"]
        labels = {"years": "Anos (ex.: 6 ou 6,7)"}
        widgets = {"text": forms.Textarea(attrs={"rows": 3}),
                   "component": forms.Select(choices=[("", "—")] + [(c, c) for c in COMPONENTS])}

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.school = school
        self.fields["kind"].choices = [(k, v) for k, v in CurriculumItem.Kind.choices
                                       if k in (CurriculumItem.Kind.DF_OBJECTIVE, CurriculumItem.Kind.DF_CONTENT,
                                                CurriculumItem.Kind.OWN)]
        self.fields["source"].help_text = "Documento de onde o texto foi copiado, com edição e página."

    def clean_years(self):
        years = (self.cleaned_data.get("years") or "").replace(" ", "")
        if years and not re.fullmatch(r"[1-9](,[1-9])*", years):
            raise ValidationError("Use números de 1 a 9 separados por vírgula.")
        return years

    def clean_bncc_codes(self):
        codes = [c.upper() for c in CODE_RE.findall(self.cleaned_data.get("bncc_codes") or "")]
        found = list(CurriculumItem.objects.filter(school__isnull=True, kind=CurriculumItem.Kind.SKILL,
                                                   code__in=codes))
        missing = sorted(set(codes) - {i.code for i in found})
        if missing:
            raise ValidationError(f"Habilidade não encontrada: {', '.join(missing)}.")
        return found

    def clean(self):
        data = super().clean()
        code, kind = data.get("code"), data.get("kind")
        if code and kind and CurriculumItem.objects.filter(school=self.school, kind=kind, code=code).exclude(
                pk=self.instance.pk).exists():
            self.add_error("code", "Já existe um item com este código.")
        return data


class CurriculumImportForm(forms.Form):
    file = forms.FileField(label="Planilha CSV", help_text=(
        "Colunas: tipo (objetivo_df, conteudo_df ou proprio), codigo, componente, anos, texto, fonte, url, "
        "habilidades_bncc e, opcionais, relacao (equivalente, parcial, relacionada) e confianca (alta, media, "
        "baixa). Separador vírgula ou ponto e vírgula, codificação UTF-8. Correspondências importadas ficam "
        "marcadas como a validar."))

    def clean_file(self):
        f = self.cleaned_data["file"]
        if f.size > 2 * 1024 * 1024:
            raise ValidationError("Arquivo maior que 2 MB.")
        try:
            text = f.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ValidationError("Salve a planilha como CSV UTF-8.")
        dialect = csv.Sniffer().sniff(text[:2000], delimiters=",;") if text.strip() else csv.excel
        rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
        if not rows:
            raise ValidationError("A planilha está vazia.")
        need = {"tipo", "codigo", "texto", "fonte"}
        cols = {c.strip().lower() for c in rows[0].keys() if c}
        if not need <= cols:
            raise ValidationError(f"Faltam colunas: {', '.join(sorted(need - cols))}.")
        return [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in rows]
