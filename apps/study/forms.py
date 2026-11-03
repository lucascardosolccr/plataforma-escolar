from django import forms
from django.core.files.uploadedfile import UploadedFile
from django.utils import timezone

from apps.academics.models import ClassGroup, Subject
from apps.academics.permissions import teacher_class_ids, teacher_subject_ids, teaches
from apps.core.uploads import MAX_ATTACHMENT_SIZE_MB, validate_attachment, validate_attachment_content
from apps.curriculum.forms import CurriculumFormMixin
from apps.curriculum.models import CurriculumItem

from .models import ExamGuide, ExamTopic, PracticeQuestion, StudyMaterial, StudyQuestion, platform_of

DATE = forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})


class GuideForm(forms.ModelForm):
    version = forms.IntegerField(widget=forms.HiddenInput, required=False)

    class Meta:
        model = ExamGuide
        fields = ["class_group", "subject", "evaluation", "title", "exam_date", "description", "guidance",
                  "criteria", "prep_time", "published_date", "available_until"]
        widgets = {"exam_date": DATE, "published_date": DATE, "available_until": DATE,
                   "description": forms.Textarea(attrs={"rows": 3}), "guidance": forms.Textarea(attrs={"rows": 4}),
                   "criteria": forms.Textarea(attrs={"rows": 2})}
        help_texts = {
            "published_date": "A turma e a família passam a ver a partir desta data.",
            "available_until": "Opcional. Depois desta data some das listas da família (deve ser depois da prova).",
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.pedagogy.models import Evaluation

        self.user = user
        school = user.school
        self.fields["class_group"].queryset = ClassGroup.objects.filter(
            pk__in=teacher_class_ids(user, edit=True)).select_related("school_year").order_by("name")
        self.fields["subject"].queryset = Subject.choices_for(school, keep=self.instance.subject_id).filter(
            pk__in=teacher_subject_ids(user, edit=True))
        # select_related: o rótulo cita turma (com o ano) e disciplina; sem isto eram
        # 3 consultas por avaliação ao montar a lista (117 consultas na página).
        self.fields["evaluation"].queryset = Evaluation.objects.filter(
            school=school, class_group_id__in=teacher_class_ids(user, edit=True))             .select_related("class_group__school_year", "subject").order_by("-date")
        self.fields["evaluation"].label_from_instance = lambda e: f"{e.title} — {e.class_group} · {e.subject} · {e.date:%d/%m/%Y}"
        self.fields["published_date"].required = False
        self.fields["exam_date"].required = False
        self.fields["version"].initial = self.instance.version if self.instance.pk else 1
        if self.instance.pk and self.instance.status != ExamGuide.Status.DRAFT:
            # Mudar a turma depois de publicado tiraria o conteúdo de quem já o recebeu.
            self.fields["class_group"].disabled = True

    def clean(self):
        c = super().clean()
        cg, subj, ev = c.get("class_group"), c.get("subject"), c.get("evaluation")
        if cg and subj and not teaches(self.user, cg, subj, edit=True):
            raise forms.ValidationError(f"Você não tem atribuição de {subj} na turma {cg}.")
        if ev is not None:
            if (ev.class_group_id, ev.subject_id) != (getattr(cg, "pk", None), getattr(subj, "pk", None)):
                self.add_error("evaluation", "A avaliação precisa ser desta turma e desta disciplina.")
            else:
                c["exam_date"] = ev.date  # uma fonte só para a data
        if not c.get("exam_date"):
            self.add_error("exam_date", "Informe a data da prova (ou escolha a avaliação).")
        c["published_date"] = c.get("published_date") or timezone.localdate()
        exam, until = c.get("exam_date"), c.get("available_until")
        if exam and until and until < exam:
            self.add_error("available_until", "O conteúdo não pode sumir antes da prova.")
        if self.instance.pk and c.get("version") not in (None, self.instance.version):
            raise forms.ValidationError(
                "Outra pessoa salvou estes conteúdos enquanto você editava. Abra de novo para ver a versão atual "
                "e refaça a sua alteração (nada foi gravado).")
        return c


class TopicForm(CurriculumFormMixin, forms.ModelForm):
    class Meta:
        model = ExamTopic
        fields = ["title", "description", "priority", "level", "prerequisite_notes", "curriculum", "order"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3}),
                   "prerequisite_notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.attach_curriculum(user)


class MaterialForm(forms.ModelForm):
    # Esquema explícito: o padrão do Django muda de http para https na versão 6.
    url = forms.URLField(label="Endereço (link)", max_length=500, required=False, assume_scheme="https")

    class Meta:
        model = StudyMaterial
        fields = ["kind", "topic", "title", "description", "why", "file", "url", "author", "duration", "segment",
                  "guiding_questions", "follow_up", "accessibility", "publisher", "edition_year", "pages",
                  "access_type", "alternative", "curriculum", "order", "shared", "tags"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3}),
                   "guiding_questions": forms.Textarea(attrs={"rows": 2}),
                   "follow_up": forms.Textarea(attrs={"rows": 2}),
                   "curriculum": forms.CheckboxSelectMultiple}
        help_texts = {"file": f"PDF, imagem, documento, planilha ou apresentação, até {MAX_ATTACHMENT_SIZE_MB} MB."}

    def __init__(self, *args, guide=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.guide = guide
        self.fields["topic"].queryset = guide.topics.all()
        self.fields["topic"].required = False
        self.fields["curriculum"].queryset = CurriculumItem.objects.filter(exam_topics__guide=guide).distinct()
        self.fields["curriculum"].required = False
        self.fields["curriculum"].help_text = "Habilidades dos tópicos desta prova."
        # Mesmo seletor das outras telas (curriculum/_picker.html), num grupo só.
        self.curriculum_groups = [("Habilidades dos tópicos desta prova", list(self.fields["curriculum"].queryset))]
        if self.is_bound:
            self.curriculum_selected = set(self.data.getlist("curriculum"))
        else:
            chosen = self.initial.get("curriculum") or (
                list(self.instance.curriculum.values_list("pk", flat=True)) if self.instance.pk else [])
            self.curriculum_selected = {str(getattr(c, "pk", c)) for c in chosen}
        self.fields["file"].validators = [validate_attachment, validate_attachment_content]

    def clean_url(self):
        url = (self.cleaned_data.get("url") or "").strip()
        if url and not url.lower().startswith(("http://", "https://")):
            raise forms.ValidationError("Use um endereço que comece com http:// ou https://.")
        return url

    def clean(self):
        c = super().clean()
        kind, url, f = c.get("kind"), c.get("url"), c.get("file")
        has_file = bool(f) or bool(self.instance.pk and self.instance.file)
        if kind in (StudyMaterial.Kind.VIDEO, StudyMaterial.Kind.LINK) and not url:
            self.add_error("url", "Informe o endereço do vídeo ou da página.")
        if kind == StudyMaterial.Kind.FILE and not has_file:
            self.add_error("file", "Escolha o arquivo.")
        if kind == StudyMaterial.Kind.READING:
            if not c.get("author") and not c.get("publisher"):
                self.add_error("author", "Para indicar uma leitura, informe o autor ou a instituição (ou a editora). "
                                         "Sem isso o estudante não consegue encontrar o material.")
            if c.get("access_type") == StudyMaterial.Access.FREE and not url:
                self.add_error("access_type", "“Acesso livre” só com o link conferido; sem link, escolha outro tipo.")
        if kind in (StudyMaterial.Kind.EXERCISES, StudyMaterial.Kind.EXAMPLE, StudyMaterial.Kind.SUMMARY,
                    StudyMaterial.Kind.GUIDE) and not (has_file or url or c.get("description")):
            self.add_error("description", "Escreva o conteúdo, anexe um arquivo ou informe um link.")
        if f and url:
            self.add_error("url", "Use o arquivo ou o link, não os dois no mesmo material.")
        c["platform"] = platform_of(url) if url else ""
        return c

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.platform = self.cleaned_data.get("platform", "")
        f = self.cleaned_data.get("file")
        if isinstance(f, UploadedFile):  # arquivo novo nesta gravação
            obj.original_name = f.name[:255]
        if commit:
            obj.save()
            self.save_m2m()
        return obj


class QuestionForm(forms.ModelForm):
    class Meta:
        model = StudyQuestion
        fields = ["topic", "text"]
        widgets = {"text": forms.Textarea(attrs={"rows": 3, "maxlength": 1000})}
        labels = {"topic": "Sobre qual tópico (opcional)", "text": "Sua dúvida"}

    def __init__(self, *args, guide=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["topic"].queryset = guide.topics.all()
        self.fields["topic"].required = False
        self.fields["topic"].empty_label = "A prova toda"


class AnswerForm(forms.Form):
    answer = forms.CharField(label="Resposta", widget=forms.Textarea(attrs={"rows": 2}), max_length=2000)


class PracticeForm(forms.ModelForm):
    """Exercício de múltipla escolha (verdadeiro ou falso = duas alternativas)."""

    MAX_OPTIONS = 5
    correct_choice = forms.TypedChoiceField(
        label="Alternativa correta", coerce=int, choices=[(i, f"Alternativa {i + 1}") for i in range(MAX_OPTIONS)])

    class Meta:
        model = PracticeQuestion
        fields = ["topic", "statement", "explanation", "curriculum", "order"]
        widgets = {"statement": forms.Textarea(attrs={"rows": 3}), "explanation": forms.Textarea(attrs={"rows": 2}),
                   "curriculum": forms.CheckboxSelectMultiple}

    def __init__(self, *args, guide=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["topic"].queryset = guide.topics.all()
        self.fields["topic"].required = False
        self.fields["curriculum"].queryset = CurriculumItem.objects.filter(exam_topics__guide=guide).distinct()
        self.fields["curriculum"].required = False
        self.curriculum_groups = [("Habilidades dos tópicos desta prova", list(self.fields["curriculum"].queryset))]
        current = list(self.instance.options) if self.instance.pk else []
        for i in range(self.MAX_OPTIONS):
            self.fields[f"option_{i}"] = forms.CharField(
                label=f"Alternativa {i + 1}", required=False, max_length=300,
                initial=current[i] if i < len(current) else "")
        if self.instance.pk:
            self.fields["correct_choice"].initial = self.instance.correct
        if self.is_bound:
            self.curriculum_selected = set(self.data.getlist("curriculum"))
        else:
            self.curriculum_selected = {str(pk) for pk in (
                self.instance.curriculum.values_list("pk", flat=True) if self.instance.pk else [])}
        # Ordem dos campos: enunciado, alternativas, correta, explicação.
        order = ["topic", "statement"] + [f"option_{i}" for i in range(self.MAX_OPTIONS)] + [
            "correct_choice", "explanation", "curriculum", "order"]
        self.order_fields(order)

    def clean(self):
        c = super().clean()
        filled = [(i, (c.get(f"option_{i}") or "").strip()) for i in range(self.MAX_OPTIONS)]
        options = [text for _, text in filled if text]
        if len(options) < 2:
            raise forms.ValidationError("Escreva pelo menos duas alternativas.")
        chosen = c.get("correct_choice")
        if chosen is None or not filled[chosen][1]:
            self.add_error("correct_choice", "A alternativa correta precisa estar preenchida.")
            return c
        # Índice da correta na lista compacta (sem as alternativas em branco).
        c["options_list"] = options
        c["correct_index"] = [i for i, t in filled if t].index(chosen)
        return c

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.options = self.cleaned_data["options_list"]
        obj.correct = self.cleaned_data["correct_index"]
        if commit:
            obj.save()
            self.save_m2m()
        return obj
