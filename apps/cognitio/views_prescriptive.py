"""Intervenções pedagógicas, trilhas e banco de estratégias."""

import datetime

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.academics.models import ClassGroup, Subject
from apps.core.models import Role, create_audit_log
from apps.core.pagination import paginate
from apps.curriculum.models import CurriculumItem
from apps.registry.models import Enrollment, Student

from . import access
from .models import InterventionStrategy, LearningAlert, LearningIntervention, LearningTrail
from .recommend import (RESULT_LABELS, build_trail, comparison, error_types_for, next_step, outcomes, recommend,
                        strategy_histories, strategy_history)

DATE = forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})


class InterventionForm(forms.ModelForm):
    students = forms.MultipleChoiceField(label="Estudantes", widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = LearningIntervention
        fields = ["title", "kind", "objective", "activity", "complexity", "materials", "minutes", "methodology",
                  "criteria", "expected_evidence", "prereqs_to_check", "evidence_basis", "starts_on", "review_on"]
        widgets = {"starts_on": DATE, "review_on": DATE,
                   **{f: forms.Textarea(attrs={"rows": 3}) for f in ("objective", "activity", "materials",
                                                                     "methodology", "criteria", "expected_evidence",
                                                                     "prereqs_to_check", "evidence_basis")}}

    def __init__(self, *args, students=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["students"].choices = [(str(s.pk), s.full_name) for s in students]
        self.fields["kind"].help_text = ("Um estudante: individual; parte da turma: pequeno grupo; todos: a turma. "
                                         "O formato sai dos estudantes marcados.")
        self.order_fields(["title", "kind", "students"] + self.Meta.fields[2:])

    def clean(self):
        data = super().clean()
        if data.get("starts_on") and data.get("review_on") and data["review_on"] < data["starts_on"]:
            self.add_error("review_on", "A revisão não pode ser antes do início.")
        return data


def _visible(user):
    from apps.academics.permissions import teacher_pairs
    from apps.coordination.scope import class_scope

    qs = LearningIntervention.objects.filter(school=user.school)
    if user.role == Role.PROFESSOR.value:
        q = Q(pk__in=[])
        for c, s in teacher_pairs(user):
            q |= Q(class_group_id=c, subject_id=s)
        return qs.filter(q)
    if user.role == Role.COORDENACAO.value:
        scope = class_scope(user)
        return qs if scope is None else qs.filter(class_group_id__in=scope)
    if user.role == Role.DIRECAO.value:
        return qs
    return qs.none()


def intervention_list(request):
    user = request.user
    if not access.can_use(user):
        raise PermissionDenied
    qs = _visible(user).select_related("class_group", "subject", "item", "strategy").prefetch_related("students")
    status = request.GET.get("situacao", "abertas")
    if status == "abertas":
        qs = qs.filter(status__in=["aceita", "andamento", "proposta"])
    elif status in dict(LearningIntervention.Status.choices):
        qs = qs.filter(status=status)
    today = timezone.localdate()
    # Paginado: antes só as 60 mais recentes apareciam, sem aviso, e o contador dizia 60. O resultado
    # (antes e depois) é calculado só para a página exibida.
    page = paginate(request, qs, per_page=20)
    rows = []
    for iv in page:
        res = outcomes(iv)
        rows.append({"iv": iv, "results": res, "due": iv.review_on <= today and iv.status in ("aceita", "andamento")})
    return render(request, "cognitio/interventions.html", {
        "rows": rows, "page": page, "status": status, "labels": RESULT_LABELS,
        "status_choices": [("abertas", "Abertas")] + list(LearningIntervention.Status.choices)})


def intervention_create(request):
    """Planejar intervenção a partir de um alerta, de uma habilidade da turma ou do zero."""
    user = request.user
    alert = None
    if request.GET.get("alerta", "").isdigit():
        from .views_intel import _alerts_visible

        alert = get_object_or_404(_alerts_visible(user), pk=int(request.GET["alerta"]))
    cg_id = request.GET.get("turma") or (alert.class_group_id if alert else None)
    subj_id = request.GET.get("disciplina") or (alert.subject_id if alert and alert.subject_id else None)
    item_id = request.GET.get("habilidade") or (alert.item_id if alert and alert.item_id else None)
    if not (cg_id and subj_id and item_id):
        messages.info(request, "Abra a intervenção a partir de um alerta ou de uma habilidade no mapa da turma.")
        return redirect("cognitio:alerts")
    cg = get_object_or_404(ClassGroup, pk=cg_id, school=user.school)
    subject = get_object_or_404(Subject, pk=subj_id, school=user.school)
    item = get_object_or_404(CurriculumItem.objects.filter(CurriculumItem.visible_q(user.school)), pk=item_id)
    if not access.can_teach(user, cg, subject):
        raise PermissionDenied
    students = sorted({e.student for e in Enrollment.objects.filter(class_group=cg, status="ativo")
                       .select_related("student")}, key=lambda s: s.first_name)
    pre = [str(alert.student_id)] if alert and alert.student_id else request.GET.getlist("estudante")
    chosen = [s for s in students if str(s.pk) in pre] or students
    recs = recommend(item, user.school, "", error_types_for(chosen, item), chosen)
    strategy = None
    sid = request.POST.get("strategy") or request.GET.get("estrategia")
    if sid and sid.isdigit():
        strategy = get_object_or_404(InterventionStrategy.objects.filter(Q(school__isnull=True) | Q(school=user.school)),
                                     pk=int(sid))
    elif recs:
        strategy = recs[0]["strategy"]
    initial = {"students": pre, "starts_on": timezone.localdate(),
               "review_on": timezone.localdate() + datetime.timedelta(days=14)}
    if request.GET.get("tipo") in LearningIntervention.Kind.values:
        initial["kind"] = request.GET["tipo"]
    elif (request.GET.get("alvo") or "").isdigit() and request.GET["alvo"] != str(item.pk):
        initial["kind"] = LearningIntervention.Kind.PREREQUISITE  # trabalha um pré-requisito da competência-alvo
    if strategy:
        initial.update(title=f"{strategy.title} — {item.code}", objective=strategy.objective,
                       activity=strategy.procedures, materials=strategy.materials, minutes=strategy.minutes,
                       methodology=strategy.title, criteria=strategy.follow_up,
                       expected_evidence=strategy.expected_evidence)
    # Plano de recuperação a partir da análise de lacunas (Prompt 17, §10): competência-alvo, pré-requisitos a
    # verificar e evidências que fundamentam, calculados dos dados (nunca digitados pela URL).
    target = None
    if (request.GET.get("alvo") or "").isdigit():
        target = CurriculumItem.objects.filter(CurriculumItem.visible_q(user.school),
                                               pk=int(request.GET["alvo"])).first()
    if target and len(chosen) == 1 and target.pk != item.pk:
        from .gaps import gap_analysis

        g = gap_analysis(chosen[0], target, user.school)
        initial["prereqs_to_check"] = "\n".join(f"{r['item'].code}: {r['kind_label']} — {r['verify']}"
                                                for r in g["rows"] if r["kind"] not in (None, "superada"))
        initial["evidence_basis"] = g["summary"] + "\n" + "\n".join(
            f"{r['item'].code}: {r['why']}" for r in g["rows"] if r["why"])
    form = InterventionForm(request.POST or None, students=students, initial=initial)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            iv = form.save(commit=False)
            iv.school, iv.class_group, iv.subject, iv.item = user.school, cg, subject, item
            iv.target_item = target
            iv.strategy, iv.alert, iv.created_by = strategy, alert, user
            iv.status = LearningIntervention.Status.ACCEPTED
            iv.save()
            iv.students.set(Student.objects.filter(pk__in=form.cleaned_data["students"], school=user.school))
            if alert:
                alert.status = LearningAlert.Status.ACTION
                alert.reviewed_by, alert.reviewed_at = user, timezone.now()
                alert.save(update_fields=["status", "reviewed_by", "reviewed_at"])
            create_audit_log(user=user, action="create", request=request, target=iv,
                             detail=f"Planejou intervenção em {item.code} ({cg} — {subject})")
        messages.success(request, "Intervenção registrada. O resultado aparece conforme novas evidências forem lançadas.")
        return redirect("cognitio:intervention_detail", pk=iv.pk)
    return render(request, "cognitio/intervention_form.html", {
        "form": form, "cg": cg, "subject": subject, "item": item, "alert": alert, "recs": recs,
        "strategy": strategy, "query": request.GET.urlencode()})


def grouping(iv):
    """Individual, pequeno grupo ou turma, pelos estudantes marcados (§12). Não é guardado: sai dos dados."""
    n = iv.students.count()
    total = Enrollment.objects.filter(class_group=iv.class_group, status="ativo").count()
    if n == 1:
        return "individual"
    if total and n >= total:
        return f"com a turma ({n} estudantes)"
    return f"em pequeno grupo ({n} estudantes)"


def intervention_detail(request, pk):
    user = request.user
    iv = get_object_or_404(_visible(user).select_related("class_group", "subject", "item", "strategy", "alert"), pk=pk)
    can_edit = access.can_teach(user, iv.class_group, iv.subject)
    if request.method == "POST" and can_edit:
        status = request.POST.get("situacao")
        if status in dict(LearningIntervention.Status.choices):
            iv.status = status
            iv.teacher_note = (request.POST.get("registro") or iv.teacher_note)[:2000]
            iv.save(update_fields=["status", "teacher_note", "updated_at"])
            create_audit_log(user=user, action="update", request=request, target=iv,
                             detail=f"Intervenção {iv.get_status_display().lower()}: {iv.title}")
            messages.success(request, "Situação atualizada.")
        return redirect("cognitio:intervention_detail", pk=iv.pk)
    results = outcomes(iv)
    return render(request, "cognitio/intervention_detail.html", {
        "iv": iv, "results": results, "labels": RESULT_LABELS, "can_edit": can_edit, "cmp": comparison(iv),
        "next": next_step(iv, results), "grouping": grouping(iv),
        "status_choices": LearningIntervention.Status.choices,
        "history": strategy_history(iv.strategy, user.school) if iv.strategy else None})


def trail_create(request, class_id, subject_id, item_id):
    """Gera uma trilha (pré-requisitos → habilidade → verificação) para revisão do professor."""
    user = request.user
    cg = get_object_or_404(ClassGroup, pk=class_id, school=user.school)
    subject = get_object_or_404(Subject, pk=subject_id, school=user.school)
    item = get_object_or_404(CurriculumItem.objects.filter(CurriculumItem.visible_q(user.school)), pk=item_id)
    if not access.can_teach(user, cg, subject):
        raise PermissionDenied
    ids = request.GET.getlist("estudante") or request.POST.getlist("estudante")
    students = list(Student.objects.filter(pk__in=ids, school=user.school,
                                           enrollments__class_group=cg, enrollments__status="ativo").distinct())
    if not students:
        messages.info(request, "Escolha os estudantes da trilha a partir do mapa da turma.")
        return redirect(f"{_u('cognitio:class_view', cg.pk)}?disciplina={subject.pk}&habilidade={item.pk}")
    steps = build_trail(item, user.school, students, cg, subject)
    if request.method == "POST":
        keep = set(request.POST.getlist("passo"))
        today = timezone.localdate()
        with transaction.atomic():
            trail = LearningTrail.objects.create(school=user.school, class_group=cg, subject=subject, created_by=user,
                                                 title=f"Trilha {item.code} — {', '.join(s.first_name for s in students[:4])}")
            trail.students.set(students)
            order = 0
            for i, st in enumerate(steps):
                if str(i) not in keep:
                    continue
                order += 1
                strat = st["strategy"]
                start = today + datetime.timedelta(days=7 * (order - 1))
                iv = LearningIntervention.objects.create(
                    school=user.school, class_group=cg, subject=subject, item=st["item"], strategy=strat, trail=trail,
                    order=order, title=f"{order}. {st['kind']}: {st['item'].code}",
                    objective=strat.objective if strat else st["kind"], activity=strat.procedures if strat else "",
                    materials=strat.materials if strat else "", minutes=strat.minutes if strat else 30,
                    methodology=strat.title if strat else "", criteria=strat.follow_up if strat else "",
                    expected_evidence=strat.expected_evidence if strat else "", starts_on=start,
                    review_on=start + datetime.timedelta(days=7), created_by=user, status="aceita")
                iv.students.set(st["students"])
            create_audit_log(user=user, action="create", request=request, target=trail,
                             detail=f"Criou trilha de {order} passo(s) para {item.code}")
        messages.success(request, f"Trilha criada com {order} passo(s). Edite cada intervenção se precisar.")
        return redirect("cognitio:interventions")
    return render(request, "cognitio/trail_form.html", {"steps": steps, "cg": cg, "subject": subject, "item": item,
                                                        "students": students})


def _u(name, *args):
    from django.urls import reverse

    return reverse(name, args=args)


class StrategyForm(forms.ModelForm):
    class Meta:
        model = InterventionStrategy
        fields = ["title", "component", "objective", "procedures", "materials", "minutes", "follow_up",
                  "expected_evidence", "references"]
        widgets = {f: forms.Textarea(attrs={"rows": 3}) for f in ("objective", "procedures", "materials", "follow_up",
                                                                  "expected_evidence", "references")}


def strategy_bank(request):
    user = request.user
    if not access.can_use(user):
        raise PermissionDenied
    form = StrategyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        s = form.save(commit=False)
        s.school, s.created_by = user.school, user
        s.evidence_level = InterventionStrategy.Evidence.EXPERIMENTAL  # da escola: experimental até avaliar
        s.save()
        create_audit_log(user=user, action="create", request=request, target=s, detail=f"Cadastrou estratégia {s.title}")
        messages.success(request, "Estratégia cadastrada como sugestão experimental da escola.")
        return redirect("cognitio:strategies")
    qs = InterventionStrategy.objects.filter(Q(school__isnull=True) | Q(school=user.school), active=True) \
        .select_related("dimension")
    comp = request.GET.get("componente", "")
    if comp:
        qs = qs.filter(component=comp)
    comps = sorted({c for c in InterventionStrategy.objects.values_list("component", flat=True) if c})
    strategies = list(qs)
    hist = strategy_histories(strategies, user.school)
    rows = [(s, hist[s.pk]) for s in strategies]
    return render(request, "cognitio/strategies.html", {"rows": rows, "form": form, "comp": comp,
                                                        "comp_choices": [(c, c) for c in comps]})
