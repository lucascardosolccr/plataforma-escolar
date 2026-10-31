"""Mapas de competências: estudante, turma e página inicial do EIA-Cognitio."""

import datetime
from collections import Counter, OrderedDict

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.academics.models import ClassGroup, Subject
from apps.core.models import Role, create_audit_log
from apps.curriculum.models import CurriculumItem
from apps.registry.models import Enrollment, Student

from . import access
from .forms import ScaleForm
from .mastery import CSS, STATES, assess, group_evidence, trajectory
from .models import MasteryScale, SkillEvidence


def _period(request, school):
    """(início, fim, rótulo, opções). Usa os períodos do calendário oficial quando existem."""
    from apps.school_calendar.models import CalendarPeriod

    today = timezone.localdate()
    periods = list(CalendarPeriod.objects.filter(school=school, school_year__is_current=True).order_by("start"))
    options = [(str(p.pk), p.name) for p in periods]
    chosen = request.GET.get("periodo", "")
    for p in periods:
        if chosen == str(p.pk):
            return p.start, p.end, p.name, options, chosen
    return datetime.date(today.year - 1, 1, 1), today, "Últimos dois anos letivos", options, ""


def _items_linked(class_ids, subject_ids):
    from apps.pedagogy.models import Activity, Evaluation, LessonPlan

    q_subject = Q() if subject_ids is None else Q(subject_id__in=subject_ids)
    ids = set()
    for model in (Activity, Evaluation, LessonPlan):
        ids |= set(model.objects.filter(q_subject, class_group_id__in=class_ids)
                   .values_list("curriculum", flat=True))
    ids.discard(None)
    return ids


def home(request):
    """Ponto de entrada por perfil."""
    user = request.user
    if not access.can_use(user):
        raise PermissionDenied
    from apps.academics.models import TeacherAssignment
    from apps.academics.permissions import teacher_pairs
    from apps.coordination.scope import class_scope

    if user.role == Role.PROFESSOR.value:
        pairs = teacher_pairs(user)
    else:
        qs = TeacherAssignment.objects.filter(school=user.school, school_year__is_current=True)
        scope = class_scope(user) if user.role == Role.COORDENACAO.value else None
        if scope is not None:
            qs = qs.filter(class_group_id__in=scope)
        pairs = set(qs.values_list("class_group_id", "subject_id"))
    classes = {c.pk: c for c in ClassGroup.objects.filter(pk__in={c for c, _ in pairs})}
    subjects = {s.pk: s for s in Subject.objects.filter(pk__in={s for _, s in pairs})}
    scale = MasteryScale.for_school(user.school)
    cards = []
    for cg_id, s_id in sorted(pairs, key=lambda p: (classes[p[0]].name if p[0] in classes else "",
                                                     subjects[p[1]].name if p[1] in subjects else "")):
        if cg_id not in classes or s_id not in subjects:
            continue
        evs = SkillEvidence.objects.filter(class_group_id=cg_id, subject_id=s_id)
        grouped = group_evidence(evs)
        states = Counter(assess(v, scale).state for v in grouped.values())
        chips = [(STATES[k][0], CSS[k], states[k]) for k in STATES if states[k]]
        cards.append({"cg": classes[cg_id], "subject": subjects[s_id], "states": states, "chips": chips,
                      "items": len({k[1] for k in grouped}), "students": len({k[0] for k in grouped}),
                      "evidence": evs.count()})
    return render(request, "cognitio/home.html", {"cards": cards, "states": STATES, "scale": scale,
                                                   "can_configure": user.role in (Role.COORDENACAO.value,
                                                                                  Role.DIRECAO.value)})


def student_map(request, student_id):
    user = request.user
    student = get_object_or_404(Student, pk=student_id, school=user.school)
    subjects = access.student_subjects(user, student)
    if subjects is not None and not subjects:
        raise PermissionDenied
    start, end, period_label, period_options, period = _period(request, user.school)
    scale = MasteryScale.for_school(user.school)
    evs = SkillEvidence.objects.filter(student=student, observed_on__gte=start, observed_on__lte=end) \
        .select_related("item", "subject")
    if subjects is not None:
        evs = evs.filter(subject_id__in=subjects)
    subject_options = Subject.objects.filter(pk__in=evs.values("subject_id")).order_by("name")
    subj = request.GET.get("disciplina", "")
    if subj.isdigit():
        evs = evs.filter(subject_id=int(subj))
    source = request.GET.get("fonte", "")
    if source in dict(SkillEvidence.Source.choices):
        evs = evs.filter(source_type=source)
    else:
        source = ""
    grouped = OrderedDict()
    for e in evs.order_by("observed_on"):
        grouped.setdefault(e.item_id, []).append(e)
    class_ids = list(Enrollment.objects.filter(student=student, status="ativo").values_list("class_group_id", flat=True))
    linked = _items_linked(class_ids, subjects)
    items = {i.pk: i for i in CurriculumItem.objects.filter(pk__in=set(grouped) | linked)}
    comps = OrderedDict()
    counts = Counter()
    for pk, item in sorted(items.items(), key=lambda kv: (kv[1].component, kv[1].thematic_unit, kv[1].code)):
        if subj.isdigit() and pk not in grouped:
            continue
        a = assess(grouped.get(pk, []), scale)
        counts[a.state] += 1
        comps.setdefault(item.component or item.area or "Outros", OrderedDict()).setdefault(
            item.thematic_unit or "Sem unidade identificada", []).append((item, a))
    detail_item = request.GET.get("habilidade", "")
    detail = None
    if detail_item.isdigit() and int(detail_item) in items:
        it = items[int(detail_item)]
        ev_list = grouped.get(it.pk, [])
        from apps.school_calendar.models import CalendarPeriod

        cutoffs = [(p.name, p.end) for p in CalendarPeriod.objects.filter(
            school=user.school, school_year__is_current=True).order_by("start") if p.start <= timezone.localdate()]
        detail = {"item": it, "a": assess(ev_list, scale), "traj": trajectory(ev_list, scale, cutoffs) if cutoffs else []}
    create_audit_log(user=user, action="view", request=request, target=student,
                     detail=f"Consultou o mapa de competências de {student}")
    from .models import LearningAlert, LearningIntervention
    from .recommend import RESULT_LABELS, outcomes

    alerts = LearningAlert.objects.filter(student=student, active=True).exclude(
        status__in=["descartado", "resolvido"]).select_related("item", "subject", "class_group")
    ivs = LearningIntervention.objects.filter(students=student).select_related("item", "subject").order_by("-starts_on")
    if subjects is not None:
        alerts = alerts.filter(subject_id__in=subjects)
        ivs = ivs.filter(subject_id__in=subjects)
    iv_rows = []
    for iv in ivs[:10]:
        mine = [r for r in outcomes(iv) if r["student"].pk == student.pk]
        iv_rows.append((iv, mine[0] if mine else None))
    upcoming = _next_objectives(class_ids, subjects)
    timeline = list(evs.order_by("-observed_on")[:40])
    return render(request, "cognitio/student_map.html", {
        "student": student, "comps": comps, "counts": counts, "states": STATES, "detail": detail,
        "timeline": timeline, "period_options": period_options, "period": period, "period_label": period_label,
        "subject_options": [(s.pk, s.name) for s in subject_options], "subj": subj,
        "source_options": SkillEvidence.Source.choices, "source": source, "scale": scale,
        "classes": ClassGroup.objects.filter(pk__in=class_ids),
        "alerts": alerts, "iv_rows": iv_rows, "labels": RESULT_LABELS, "upcoming": upcoming,
    })


def _next_objectives(class_ids, subjects):
    """Próximos objetivos: habilidades de planejamentos e atividades das próximas semanas."""
    from apps.pedagogy.models import Activity, LessonPlan

    today = timezone.localdate()
    end = today + datetime.timedelta(days=30)
    q = Q() if subjects is None else Q(subject_id__in=subjects)
    out = {}
    plans = LessonPlan.objects.filter(q, class_group_id__in=class_ids, ends_on__gte=today, starts_on__lte=end)
    for p in plans.prefetch_related("curriculum"):
        for it in p.curriculum.all():
            out.setdefault(it.pk, (it, p.starts_on))
    acts = Activity.objects.filter(q, class_group_id__in=class_ids, class_date__gte=today, class_date__lte=end)
    for a in acts.prefetch_related("curriculum"):
        for it in a.curriculum.all():
            out.setdefault(it.pk, (it, a.class_date))
    return sorted(out.values(), key=lambda t: t[1])


def class_view(request, class_id):
    user = request.user
    cg = get_object_or_404(ClassGroup, pk=class_id, school=user.school)
    allowed = access.class_subjects(user, cg)
    if allowed is not None and not allowed:
        raise PermissionDenied
    from apps.academics.models import TeacherAssignment

    subject_ids = set(TeacherAssignment.objects.filter(class_group=cg).values_list("subject_id", flat=True)) \
        | set(SkillEvidence.objects.filter(class_group=cg).values_list("subject_id", flat=True))
    if allowed is not None:
        subject_ids &= allowed
    subjects = list(Subject.objects.filter(pk__in=subject_ids).order_by("name"))
    if not subjects:
        raise PermissionDenied
    chosen = request.GET.get("disciplina", "")
    subject = next((s for s in subjects if str(s.pk) == chosen), subjects[0])
    start, end, period_label, period_options, period = _period(request, user.school)
    scale = MasteryScale.for_school(user.school)
    students = sorted({e.student for e in Enrollment.objects.filter(class_group=cg, status="ativo")
                       .select_related("student")}, key=lambda s: s.first_name)
    evs = SkillEvidence.objects.filter(class_group=cg, subject=subject, observed_on__gte=start,
                                       observed_on__lte=end).select_related("item")
    grouped = group_evidence(evs)
    item_ids = {k[1] for k in grouped} | _items_linked([cg.pk], {subject.pk})
    items = sorted(CurriculumItem.objects.filter(pk__in=item_ids), key=lambda i: (i.thematic_unit, i.code))
    matrix, dist = [], OrderedDict()
    for it in items:
        dist[it.pk] = Counter()
    for st in students:
        row = []
        for it in items:
            a = assess(grouped.get((st.pk, it.pk), []), scale)
            dist[it.pk][a.state] += 1
            row.append((it, a))
        matrix.append((st, row))
    n = max(len(students), 1)
    summary = []
    for it in items:
        c = dist[it.pk]
        summary.append({"item": it, "c": c, "difficulty": c["dificuldade"], "insufficient": c["nao_avaliado"] + c["insuficiente"],
                        "consolidated": c["consolidada"] + c["consolidacao"], "contradictory": c["contraditoria"],
                        "bars": _bars(c, n)})
    retake = sorted([s for s in summary if s["difficulty"] / n >= 0.3], key=lambda s: -s["difficulty"])
    strong = sorted([s for s in summary if s["consolidated"] / n >= 0.6], key=lambda s: -s["consolidated"])[:5]
    sel = request.GET.get("habilidade", "")
    focus = None
    if sel.isdigit():
        it = next((i for i in items if i.pk == int(sel)), None)
        if it:
            rows = [(st, a) for st, r in matrix for i, a in r if i.pk == it.pk]
            focus = {"item": it, "rows": sorted(rows, key=lambda r: (r[1].level, r[1].mean or 0))}
    groups = []
    for s in summary:
        members = [st for st, r in matrix for i, a in r if i.pk == s["item"].pk
                   and a.state in ("dificuldade", "desenvolvimento")]
        if len(members) >= 2:
            groups.append({"item": s["item"], "students": members})
    return render(request, "cognitio/class_view.html", {
        "cg": cg, "subject": subject, "subjects": [(s.pk, s.name) for s in subjects], "items": items,
        "matrix": matrix, "summary": summary, "retake": retake, "strong": strong, "focus": focus, "groups": groups,
        "states": STATES, "period_options": period_options, "period": period, "period_label": period_label,
        "students_count": len(students), "can_record": access.can_teach(user, cg, subject),
    })


def scale_settings(request):
    user = request.user
    if user.role not in (Role.COORDENACAO.value, Role.DIRECAO.value):
        raise PermissionDenied
    scale = MasteryScale.for_school(user.school)
    form = ScaleForm(request.POST or None, instance=scale)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.school, obj.updated_by = user.school, user
        obj.save()
        create_audit_log(user=user, action="update", request=request, target=obj,
                         detail=f"Alterou a escala de domínio: cortes {obj.t1}/{obj.t2}/{obj.t3}, mínimo "
                                f"{obj.min_evidence} evidências")
        messages.success(request, "Critérios da escala salvos.")
        return redirect("cognitio:home")
    return render(request, "cognitio/scale_form.html", {"form": form})


def _bars(counter, total, width=160):
    """Segmentos da barra empilhada: (estado, rótulo, quantidade, x, largura, classe)."""
    out, x = [], 0
    for state, (label, _lvl, _h) in STATES.items():
        n = counter[state]
        if not n:
            continue
        w = round(n * width / max(total, 1))
        out.append((state, label, n, x, w, CSS[state]))
        x += w
    return out
