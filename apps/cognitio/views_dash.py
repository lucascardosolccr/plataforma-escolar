"""Painéis de inteligência pedagógica: professor, coordenação, direção e disciplina.

Regras comuns: só dados reais da plataforma; recorte pelo alcance de cada perfil;
na visão da direção, nada individual e grupos com menos de 5 estudantes ocultos;
"prioridade de acompanhamento" é contagem de alertas, não pontuação de capacidade.
"""

import datetime
from collections import Counter, OrderedDict

from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone

from apps.academics.models import ClassGroup, Subject, TeacherAssignment
from apps.core.models import Role
from apps.curriculum.models import COMPONENTS, ItemDimension, component_for

from . import access
from .mastery import CSS, STATES, apply_judgments, assess, group_evidence
from .models import LearningAlert, LearningIntervention, MasteryScale, SkillEvidence, TextAnalysis
from .recommend import outcomes
from .taxonomy import NO_ERROR_TYPING, error_label

MIN_GROUP = 5


def _scope(user):
    """(class_ids, pairs) que a pessoa alcança; pairs None = todas as disciplinas da turma."""
    from apps.academics.permissions import teacher_pairs
    from apps.coordination.scope import class_scope

    if user.role == Role.PROFESSOR.value:
        pairs = teacher_pairs(user)
        return {c for c, _ in pairs}, pairs
    qs = ClassGroup.objects.filter(school=user.school, school_year__is_current=True)
    if user.role == Role.COORDENACAO.value:
        scope = class_scope(user)
        if scope is not None:
            qs = qs.filter(pk__in=scope)
    return set(qs.values_list("pk", flat=True)), None


def _evidence_qs(user, class_ids, pairs):
    qs = SkillEvidence.objects.filter(school=user.school, class_group_id__in=class_ids)
    if pairs is not None:
        q = Q(pk__in=[])
        for c, s in pairs:
            q |= Q(class_group_id=c, subject_id=s)
        qs = qs.filter(q)
    return qs


def _dist(states):
    """[(rótulo, classe, quantidade, %, posição x)] para a barra empilhada."""
    c = Counter(states)
    total = sum(c.values()) or 1
    out, x = [], 0
    for k in STATES:
        if c[k]:
            pct = round(c[k] * 100 / total)
            out.append((STATES[k][0], CSS[k], c[k], pct, x))
            x += pct
    return out


def _periods(school):
    from apps.school_calendar.models import CalendarPeriod

    today = timezone.localdate()
    ps = [(p.name, p.end) for p in CalendarPeriod.objects.filter(school=school, school_year__is_current=True)
          .order_by("start") if p.start <= today]
    if not ps:
        ps = [(f"{m:02d}/{today.year}", (datetime.date(today.year, m, 28))) for m in range(1, today.month + 1)]
    return ps


def _worked(class_ids, pairs, today):
    """{(turma, disciplina, habilidade): (última data, origem)} do que já foi trabalhado: planejamento
    encerrado ou atividade com aula já dada."""
    from apps.pedagogy.models import Activity, LessonPlan

    last_worked = {}
    for model, field, origin in ((LessonPlan, "ends_on", "planejamento"), (Activity, "class_date", "atividade")):
        qs = model.objects.filter(class_group_id__in=class_ids, **{f"{field}__lte": today})
        if pairs is not None:
            q = Q(pk__in=[])
            for c, s in pairs:
                q |= Q(class_group_id=c, subject_id=s)
            qs = qs.filter(q)
        for cid, sid, iid, when in qs.values_list("class_group_id", "subject_id", "curriculum", field):
            key = (cid, sid, iid)
            if iid is not None and when and (key not in last_worked or when > last_worked[key][0]):
                last_worked[key] = (when, origin)
    return last_worked


def not_evaluated_for(user, class_group=None, today=None, limit=8):
    """Trabalhadas e ainda não avaliadas no alcance da pessoa (ou só na turma escolhida)."""
    today = today or timezone.localdate()
    class_ids, pairs = _scope(user)
    if class_group is not None:
        class_ids &= {class_group.pk}
        if pairs is not None:
            pairs = {(c, s) for c, s in pairs if c == class_group.pk}
    evs = _evidence_qs(user, class_ids, pairs).only("class_group_id", "subject_id", "item_id", "ratio", "weight")
    return _not_evaluated_rows(_worked(class_ids, pairs, today), evs, limit)


def _not_evaluated_rows(last_worked, evs, limit=8):
    """Habilidades trabalhadas sem evidência válida de nenhum estudante naquela turma e disciplina (a mesma
    regra de ``assess``: com proporção de acerto e peso). As mais recentes primeiro: ainda dá tempo de
    observar."""
    from apps.academics.models import Subject
    from apps.curriculum.models import CurriculumItem

    evaluated = {(e.class_group_id, e.subject_id, e.item_id) for e in evs if e.ratio is not None and e.weight > 0}
    open_ = sorted(((k, v) for k, v in last_worked.items() if k not in evaluated), key=lambda kv: kv[1][0],
                   reverse=True)
    total, open_ = len(open_), open_[:limit]
    cgs = ClassGroup.objects.in_bulk({k[0] for k, _ in open_})
    subjects = Subject.objects.in_bulk({k[1] for k, _ in open_})
    items = CurriculumItem.objects.in_bulk({k[2] for k, _ in open_})
    rows = [{"cg": cgs.get(c), "subject": subjects.get(s), "item": items.get(i), "when": when, "origin": origin}
            for (c, s, i), (when, origin) in open_]
    return {"rows": [r for r in rows if r["cg"] and r["subject"] and r["item"]], "total": total,
            "worked": len(last_worked)}


def dashboard(request):
    user = request.user
    if not access.can_use(user):
        raise PermissionDenied
    scale = MasteryScale.for_school(user.school)
    today = timezone.localdate()
    class_ids, pairs = _scope(user)
    evs = list(_evidence_qs(user, class_ids, pairs).select_related("item", "class_group", "subject"))
    grouped = group_evidence(evs)
    assessments = apply_judgments({k: assess(v, scale, today) for k, v in grouped.items()})
    ctx = {"role": user.role, "dist": _dist([a.state for a in assessments.values()]),
           "n_students": len({k[0] for k in grouped}), "n_items": len({k[1] for k in grouped}), "n_evidence": len(evs)}
    # Evolução por período (estado acumulado no fim de cada período).
    evolution = []
    for label, end in _periods(user.school):
        st = [assess([e for e in v if e.observed_on <= end], scale, end).state for v in grouped.values()]
        st = [s for s in st if s != "nao_avaliado"]
        cons = sum(1 for s in st if s in ("consolidada", "consolidacao"))
        diff = sum(1 for s in st if s == "dificuldade")
        evolution.append({"label": label, "n": len(st), "cons": round(cons * 100 / len(st)) if st else None,
                          "diff": round(diff * 100 / len(st)) if st else None})
    ctx["evolution"] = evolution
    # Habilidades que pedem atenção: dificuldade em vários estudantes.
    by_item = {}
    for (sid, iid), a in assessments.items():
        d = by_item.setdefault(iid, {"diff": 0, "classes": set(), "item": a.evidence[0].item, "n": 0})
        d["n"] += 1
        if a.state == "dificuldade":
            d["diff"] += 1
            d["classes"].add(a.evidence[0].class_group_id)
    attention = sorted([d for d in by_item.values() if d["diff"] >= 2], key=lambda d: -d["diff"])[:10]
    ctx["attention"] = attention
    alerts = LearningAlert.objects.filter(school=user.school, class_group_id__in=class_ids, active=True) \
        .exclude(status__in=["descartado", "resolvido"])
    if pairs is not None:
        q = Q(pk__in=[])
        for c, s in pairs:
            q |= Q(class_group_id=c, subject_id=s) | Q(class_group_id=c, subject__isnull=True)
        alerts = alerts.filter(q)
    ivs = LearningIntervention.objects.filter(school=user.school, class_group_id__in=class_ids)
    if pairs is not None:
        q = Q(pk__in=[])
        for c, s in pairs:
            q |= Q(class_group_id=c, subject_id=s)
        ivs = ivs.filter(q)
    open_ivs = ivs.filter(status__in=["aceita", "andamento"])
    results = Counter()
    for iv in ivs.filter(starts_on__lte=today).prefetch_related("students")[:100]:
        for r in outcomes(iv, scale):
            results[r["result"]] += 1
    ctx.update(alerts_count=alerts.count(), alerts_high=alerts.filter(level="importante").count(),
               top_alerts=alerts.select_related("student", "item", "class_group")[:6],
               open_ivs=open_ivs.count(), due_ivs=open_ivs.filter(review_on__lte=today).count(),
               iv_results=[(k, v) for k, v in results.items()])
    # Habilidades trabalhadas e ainda não avaliadas (planejadas ou em atividades, sem evidência).
    last_worked = _worked(class_ids, pairs, today)
    worked = {k[2] for k in last_worked}
    evaluated = {k[1] for k, a in assessments.items() if a.n_valid}
    ctx["worked_count"], ctx["not_evaluated"] = len(worked), len(worked - evaluated)
    if user.role == Role.PROFESSOR.value:
        # Prompt 17, §13.2: quais habilidades, na turma e disciplina em que foram trabalhadas
        ctx["not_evaluated_rows"] = _not_evaluated_rows(last_worked, evs)
    if user.role == Role.PROFESSOR.value:
        ctx["next_lessons"] = [d for d in attention if d["diff"] >= 2][:5]
        # Prompt 17, §13.2: pré-requisitos críticos para o conteúdo das próximas semanas, por turma
        from apps.academics.models import Subject
        from apps.registry.models import Enrollment

        from .gaps import class_prerequisite_needs

        # Só os pares com prova ou atividade nas próximas semanas têm o que analisar (os demais devolviam
        # vazio depois de 5 consultas cada: um professor com 80 pares fazia ~450 consultas nesta página).
        from apps.pedagogy.models import Activity, Evaluation

        horizon = today + datetime.timedelta(days=45)
        upcoming = set(Evaluation.objects.filter(class_group_id__in=class_ids, date__gte=today, date__lte=horizon)
                       .values_list("class_group_id", "subject_id"))
        upcoming |= set(Activity.objects.filter(class_group_id__in=class_ids, deadline__gte=today,
                                                deadline__lte=horizon).exclude(status="cancelada")
                        .values_list("class_group_id", "subject_id"))
        todo = [(c, s) for c, s in (pairs or []) if (c, s) in upcoming]
        cgs = ClassGroup.objects.in_bulk({c for c, _ in todo})
        subs = Subject.objects.in_bulk({s for _, s in todo})
        studs_by_class = {}
        for e in Enrollment.objects.filter(class_group_id__in=list(cgs), status="ativo").select_related("student"):
            studs_by_class.setdefault(e.class_group_id, []).append(e.student)
        critical = []
        for c, s in todo:
            cg, subject = cgs.get(c), subs.get(s)
            if not (cg and subject):
                continue
            studs = studs_by_class.get(c, [])
            for r in class_prerequisite_needs(cg, subject, user.school, studs, today)["rows"]:
                if r["weak"]:
                    critical.append({"cg": cg, "subject": subject, **r})
        ctx["critical"] = sorted(critical, key=lambda r: -len(r["weak"]))[:8]
    if user.role in (Role.COORDENACAO.value, Role.DIRECAO.value):
        classes = []
        for cg in ClassGroup.objects.filter(pk__in=class_ids).order_by("name"):
            st = [a.state for k, a in assessments.items() if a.evidence and a.evidence[0].class_group_id == cg.pk]
            if not st:
                classes.append({"cg": cg, "n": 0})
                continue
            classes.append({"cg": cg, "n": len(st), "dist": _dist(st),
                            "alerts": alerts.filter(class_group=cg).count()})
        ctx["classes"] = classes
        ctx["articulation"] = [d for d in attention if len(d["classes"]) >= 2]
        # Prompt 17, §13.3: estudantes com dificuldade em mais de um componente pedem conversa entre professores
        comps_by_student = {}
        for (sid, iid), a in assessments.items():
            if a.state == "dificuldade" and a.evidence:
                comps_by_student.setdefault(sid, set()).add(a.evidence[0].item.component)
        if user.role == Role.COORDENACAO.value:
            from apps.registry.models import Student

            multi = {sid: c for sid, c in comps_by_student.items() if len(c) >= 2}
            names = {s.pk: s for s in Student.objects.filter(pk__in=multi)}
            ctx["cross_component"] = sorted([(names[sid], sorted(c)) for sid, c in multi.items() if sid in names],
                                            key=lambda t: (-len(t[1]), t[0].full_name))[:10]
        else:
            ctx["cross_component_count"] = sum(1 for c in comps_by_student.values() if len(c) >= 2)
        from apps.pedagogy.models import LessonPlan as LP

        ctx["plans_count"] = LP.objects.filter(class_group_id__in=class_ids,
                                               starts_on__gte=today - datetime.timedelta(days=30)).count()
    if user.role == Role.COORDENACAO.value:
        prio = Counter(alerts.filter(student__isnull=False, level="importante").values_list("student_id", flat=True))
        from apps.registry.models import Student

        names = {s.pk: s for s in Student.objects.filter(pk__in=prio)}
        ctx["priority"] = [(names[sid], n) for sid, n in prio.most_common(10) if sid in names]
    if user.role == Role.DIRECAO.value:
        ctx["by_component"] = _by_component(assessments)
        ctx["quality"] = _record_quality(user.school)
        ctx["participation"] = _participation(user.school)
    return render(request, "cognitio/dashboard.html", ctx)


def _by_component(assessments):
    """Distribuição por componente; componentes com menos de 5 estudantes ficam ocultos."""
    by = {}
    for (sid, iid), a in assessments.items():
        comp = a.evidence[0].item.component or "Outros"
        d = by.setdefault(comp, {"states": [], "students": set()})
        d["states"].append(a.state)
        d["students"].add(sid)
    out = []
    for comp, d in sorted(by.items()):
        hidden = len(d["students"]) < MIN_GROUP
        out.append({"comp": comp, "hidden": hidden, "dist": [] if hidden else _dist(d["states"]),
                    "students": len(d["students"])})
    return out


def _record_quality(school):
    from apps.pedagogy.models import Activity, Evaluation

    from .models import Question

    evals = Evaluation.objects.filter(school=school, class_group__school_year__is_current=True)
    acts = Activity.objects.filter(school=school, class_group__school_year__is_current=True, status="publicada")
    n_e, n_a = evals.count(), acts.count()
    with_q = evals.filter(pk__in=Question.objects.values("evaluation_id")).count()
    e_skill = evals.filter(curriculum__isnull=False).distinct().count()
    a_skill = acts.filter(curriculum__isnull=False).distinct().count()
    pct = lambda a, b: round(a * 100 / b) if b else None
    return {"evals": n_e, "evals_skill": pct(e_skill, n_e), "evals_questions": pct(with_q, n_e),
            "acts": n_a, "acts_skill": pct(a_skill, n_a)}


def _participation(school):
    from apps.pedagogy.models import AttendanceRecord, Submission

    since = timezone.localdate() - datetime.timedelta(days=60)
    att = list(AttendanceRecord.objects.filter(school=school, date__gte=since).values_list("status", flat=True))
    subs = list(Submission.objects.filter(school=school, activity__deadline__gte=since).values_list("status", flat=True))
    return {"attendance": round(sum(1 for s in att if s != "falta") * 100 / len(att)) if att else None,
            "deliveries": round(sum(1 for s in subs if s in ("entregue", "atrasado")) * 100 / len(subs)) if subs else None,
            "n_att": len(att), "n_subs": len(subs)}


def discipline(request):
    """Painel por componente, com o recorte próprio de cada área."""
    user = request.user
    if not access.can_use(user):
        raise PermissionDenied
    scale = MasteryScale.for_school(user.school)
    class_ids, pairs = _scope(user)
    evs = list(_evidence_qs(user, class_ids, pairs).select_related("item", "subject"))
    available = sorted({component_for(e.subject) or e.subject.name for e in evs if e.subject})
    comp = request.GET.get("componente") or (available[0] if available else "")
    evs = [e for e in evs if e.subject and (component_for(e.subject) or e.subject.name) == comp]
    grouped = group_evidence(evs)
    assessments = {k: assess(v, scale) for k, v in grouped.items()}
    # Por unidade temática.
    units = OrderedDict()
    for (sid, iid), a in sorted(assessments.items(), key=lambda kv: kv[1].evidence[0].item.thematic_unit):
        unit = a.evidence[0].item.thematic_unit or "Sem unidade identificada"
        units.setdefault(unit, []).append(a.state)
    unit_rows = [(u, len(st), _dist(st)) for u, st in units.items()]
    # Por dimensão analítica (ligações validadas ou sugeridas).
    item_ids = {k[1] for k in assessments}
    dim_links = ItemDimension.objects.filter(item_id__in=item_ids).select_related("dimension")
    dims = OrderedDict()
    for l in dim_links:
        for (sid, iid), a in assessments.items():
            if iid == l.item_id:
                dims.setdefault((l.dimension.group, l.dimension.name), []).append(a.state)
    dim_rows = [(g, n, len(st), _dist(st)) for (g, n), st in dims.items()]
    # Tipos de erro (só onde há tipologia).
    errors = []
    if comp not in NO_ERROR_TYPING:
        by_unit_err = OrderedDict()
        for e in evs:
            if e.error_type:
                u = e.item.thematic_unit or "Sem unidade"
                by_unit_err.setdefault(u, Counter())[error_label(comp, e.error_type)] += 1
        errors = [(u, c.most_common()) for u, c in by_unit_err.items()]
    texts = None
    if comp in ("Língua Portuguesa", "Língua Inglesa", "Ciências", "História", "Geografia"):
        ta = TextAnalysis.objects.filter(school=user.school, class_group_id__in=class_ids)
        if pairs is not None:
            q = Q(pk__in=[])
            for c, s in pairs:
                q |= Q(class_group_id=c, subject_id=s)
            ta = ta.filter(q)
        agg = OrderedDict()
        n = 0
        for t in ta:
            if (component_for(t.subject) or t.subject.name) != comp:
                continue
            n += 1
            for s in t.result.get("signals", []):
                if s["key"].startswith("conceito:"):
                    continue
                d = agg.setdefault(s["label"], [0, 0])
                d[0] += 1
                d[1] += s["status"] == "evidenciado"
        texts = {"n": n, "rows": [(k, v[0], round(v[1] * 100 / v[0])) for k, v in agg.items()]}
    return render(request, "cognitio/discipline.html", {
        "comp": comp, "comp_choices": [(c, c) for c in available], "unit_rows": unit_rows, "dim_rows": dim_rows,
        "errors": errors, "texts": texts, "no_error_typing": comp in NO_ERROR_TYPING,
        "n_students": len({k[0] for k in assessments}), "n_items": len(item_ids)})
