"""Produções escritas: registro, análise automática explicada e revisão do professor."""

import re

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.academics.models import ClassGroup, Subject
from apps.core.models import Role, create_audit_log
from apps.curriculum.models import CurriculumItem, component_for
from apps.registry.models import Enrollment, Student

from . import access, nlp
from .models import AnalysisFeedback, SkillObservation, TextAnalysis


class TextForm(forms.ModelForm):
    pair = forms.ChoiceField(label="Turma e disciplina")
    student = forms.ChoiceField(label="Estudante")
    skill_codes = forms.CharField(label="Habilidades (códigos)", required=False, max_length=200,
                                  help_text="Ex.: EF06LP04. Vazio: a plataforma sugere depois da análise.")

    class Meta:
        model = TextAnalysis
        fields = ["title", "genre", "prompt_text", "text", "expected_concepts", "produced_on"]
        widgets = {"prompt_text": forms.Textarea(attrs={"rows": 2}), "text": forms.Textarea(attrs={"rows": 10}),
                   "produced_on": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})}
        help_texts = {"text": "Transcreva fielmente, inclusive com os erros: a análise não avalia ortografia.",
                      "expected_concepts": "Opcional, separados por vírgula. Ex.: fotossíntese, luz, energia"}

    def __init__(self, *args, pairs=(), students=(), school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.school = school
        self.fields["pair"].choices = [(f"{cg.pk}:{s.pk}", f"{cg.name} — {s.name}") for cg, s in pairs]
        self.fields["student"].choices = [(str(st.pk), f"{st.full_name} ({cg})") for st, cg in students]
        self.pairs = {f"{cg.pk}:{s.pk}": (cg, s) for cg, s in pairs}
        self.order_fields(["pair", "student", "title", "genre", "prompt_text", "text", "expected_concepts",
                           "skill_codes", "produced_on"])

    def clean(self):
        data = super().clean()
        pair = self.pairs.get(data.get("pair"))
        if not pair:
            self.add_error("pair", "Escolha uma turma e disciplina sua.")
            return data
        cg, _s = pair
        sid = data.get("student")
        if sid and not Enrollment.objects.filter(student_id=sid, class_group=cg, status="ativo").exists():
            self.add_error("student", "O estudante não está nesta turma.")
        codes = [c.upper() for c in re.findall(r"[A-Za-z0-9.\-]+", data.get("skill_codes") or "")]
        found = list(CurriculumItem.objects.filter(CurriculumItem.visible_q(self.school), code__in=codes, active=True))
        missing = sorted(set(codes) - {i.code for i in found})
        if missing:
            self.add_error("skill_codes", f"Código não encontrado: {', '.join(missing)}.")
        data["items"] = found
        return data


def _teacher_pairs(user):
    from apps.academics.permissions import teacher_pairs

    pairs = teacher_pairs(user, edit=True)
    classes = {c.pk: c for c in ClassGroup.objects.filter(pk__in={c for c, _ in pairs})}
    subjects = {s.pk: s for s in Subject.objects.filter(pk__in={s for _, s in pairs})}
    return [(classes[c], subjects[s]) for c, s in sorted(pairs) if c in classes and s in subjects]


def _visible(user):
    from apps.academics.permissions import teacher_pairs
    from apps.coordination.scope import class_scope

    qs = TextAnalysis.objects.filter(school=user.school)
    if user.role == Role.PROFESSOR.value:
        q = Q(pk__in=[])
        for c, s in teacher_pairs(user):
            q |= Q(class_group_id=c, subject_id=s)
        return qs.filter(q)
    if user.role == Role.COORDENACAO.value:
        scope = class_scope(user)
        return qs if scope is None else qs.filter(class_group_id__in=scope)
    return qs if user.role == Role.DIRECAO.value else qs.none()


def text_list(request):
    user = request.user
    if not access.can_use(user):
        raise PermissionDenied
    qs = _visible(user).select_related("student", "class_group", "subject")[:80]
    return render(request, "cognitio/texts.html", {"texts": qs, "can_create": user.role == Role.PROFESSOR.value})


def text_create(request):
    user = request.user
    if user.role != Role.PROFESSOR.value:
        raise PermissionDenied
    pairs = _teacher_pairs(user)
    if not pairs:
        raise PermissionDenied
    students = [(e.student, e.class_group.name) for e in Enrollment.objects.filter(
        class_group__in={cg for cg, _ in pairs}, status="ativo").select_related("student", "class_group")
        .order_by("class_group__name", "student__first_name")]
    form = TextForm(request.POST or None, pairs=pairs, students=students, school=user.school,
                    initial={"produced_on": timezone.localdate()})
    if request.method == "POST" and form.is_valid():
        cg, subject = form.pairs[form.cleaned_data["pair"]]
        with transaction.atomic():
            t = form.save(commit=False)
            t.school, t.class_group, t.subject = user.school, cg, subject
            t.student = Student.objects.get(pk=form.cleaned_data["student"])
            t.created_by = user
            t.result = nlp.analyze(t.text, component_for(subject), t.prompt_text, t.expected_concepts, t.genre)
            t.engine_version = nlp.ENGINE_VERSION
            t.save()
            t.items.set(form.cleaned_data["items"])
            create_audit_log(user=user, action="create", request=request, target=t,
                             detail=f"Registrou produção escrita de {t.student} para análise")
        return redirect("cognitio:text_detail", pk=t.pk)
    return render(request, "cognitio/text_form.html", {"form": form})


def text_detail(request, pk):
    user = request.user
    t = get_object_or_404(_visible(user).select_related("student", "class_group", "subject"), pk=pk)
    can_review = access.can_teach(user, t.class_group, t.subject)
    if request.method == "POST" and can_review:
        action = request.POST.get("acao")
        if action == "sinal":
            key = request.POST.get("sinal", "")[:60]
            if key in {s["key"] for s in t.result.get("signals", [])}:
                AnalysisFeedback.objects.update_or_create(
                    analysis=t, signal=key, defaults={"agrees": request.POST.get("concorda") == "1", "teacher": user,
                                                      "comment": (request.POST.get("comentario") or "")[:300]})
        elif action == "revisar":
            level = request.POST.get("nivel", "")
            t.teacher_level = int(level) if level.isdigit() and int(level) in SkillObservation.RATIO else None
            t.teacher_feedback = (request.POST.get("devolutiva") or "").strip()[:3000]
            codes = [c.upper() for c in re.findall(r"[A-Za-z0-9.\-]+", request.POST.get("habilidades") or "")]
            if codes:
                t.items.set(CurriculumItem.objects.filter(CurriculumItem.visible_q(user.school), code__in=codes))
            t.reviewed = True
            t.reviewed_at = timezone.now()
            t.save()
            create_audit_log(user=user, action="update", request=request, target=t,
                             detail=f"Revisou análise de produção de {t.student}")
            messages.success(request, "Revisão registrada." + (" O nível observado virou evidência da habilidade."
                                                               if t.teacher_level and t.items.exists() else ""))
        return redirect("cognitio:text_detail", pk=t.pk)
    fb = {f.signal: f for f in t.feedback.all()}
    signals = [(s, fb.get(s["key"])) for s in t.result.get("signals", [])]
    suggestions = []
    comp = component_for(t.subject)
    if can_review:
        from apps.curriculum.models import year_for

        suggestions = nlp.suggest_skills(f"{t.title} {t.prompt_text} {t.text}", user.school, comp, year_for(t.class_group))
    return render(request, "cognitio/text_detail.html", {
        "t": t, "signals": signals, "can_review": can_review, "levels": SkillObservation.Level.choices,
        "suggestions": suggestions, "codes": ", ".join(t.items.values_list("code", flat=True))})


def analyzer_quality(school):
    """Concordância dos professores com cada tipo de indício (monitoramento do analisador)."""
    rows = {}
    for f in AnalysisFeedback.objects.filter(analysis__school=school):
        kind = f.signal.split(":")[0]
        r = rows.setdefault(kind, [0, 0])
        r[0] += 1
        r[1] += f.agrees
    return sorted(((k, n, a, round(a * 100 / n)) for k, (n, a) in rows.items()), key=lambda r: -r[1])
