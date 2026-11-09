"""Mapa de Aprendizagem e Projeção de Competências (Prompt 17, §12), análise de lacunas e propagação
para um estudante (§7 e §8) e decisão do professor sobre uma habilidade (§6.1).

Acesso: as mesmas regras do mapa individual (``access.student_subjects``). Toda consulta fica na
auditoria. Nenhum índice global do estudante: tudo é por habilidade e componente.
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.models import Role, create_audit_log
from apps.core.params import as_id, digits
from apps.curriculum.models import CurriculumItem, component_for
from apps.registry.models import Enrollment, Student

from . import access, gaps
from .models import LearningIntervention, SkillEvidence, SkillJudgment
from .recommend import RESULT_LABELS, outcomes
from .summary import student_components


def _source_parents():
    """Origem → (modelo do registro, campo da tela de destino, rota)."""
    from apps.pedagogy.models import Grade, GroupWorkDelivery, GroupWorkRubricScore, RubricScore, Submission

    from .models import QuestionResponse

    return {"questao": (QuestionResponse, "question__evaluation_id", "cognitio:responses"),
            "avaliacao": (Grade, "evaluation_id", "pedagogy:evaluation_grade"),
            "atividade": (Submission, "activity_id", "pedagogy:activity_detail"),
            "trabalho": (GroupWorkDelivery, "group_work_id", "pedagogy:group_work_detail"),
            "rubrica": (RubricScore, "activity_id", "pedagogy:activity_detail"),
            "rubrica_trab": (GroupWorkRubricScore, "group_work_id", "pedagogy:group_work_detail")}


def evidence_urls(evs):
    """Endereço do registro original de cada evidência, na mesma ordem (cada tela confere o próprio
    acesso). Uma consulta por tipo de origem, não uma por evidência."""
    parents = _source_parents()
    found = {}
    by_type = {}
    for e in evs:
        by_type.setdefault(e.source_type, set()).add(e.source_id)
    for kind, ids in by_type.items():
        if kind in parents:
            model, field, _ = parents[kind]
            found.update({(kind, pk): v for pk, v in model.objects.filter(pk__in=ids).values_list("pk", field)})
    out = []
    for e in evs:
        try:
            if e.source_type == "texto":
                out.append(reverse("cognitio:text_detail", args=[e.source_id]))
            elif (e.source_type, e.source_id) in found:
                out.append(reverse(parents[e.source_type][2], args=[found[(e.source_type, e.source_id)]]))
            else:
                out.append(None)
        except NoReverseMatch:
            out.append(None)
    return out


def evidence_url(e):
    """Endereço do registro original de uma evidência (cada tela confere o próprio acesso)."""
    return evidence_urls([e])[0]


def _student_or_403(user, student_id):
    student = get_object_or_404(Student, pk=student_id, school=user.school)
    subjects = access.student_subjects(user, student)
    if subjects is not None and not subjects:
        raise PermissionDenied
    return student, subjects


def _teach_pairs(user, student, item):
    """(turma, disciplina) em que a pessoa leciona ao estudante no componente da habilidade."""
    from apps.academics.models import ClassGroup, Subject
    from apps.academics.permissions import teacher_pairs

    if user.role != Role.PROFESSOR.value:
        return []
    classes = set(Enrollment.objects.filter(student=student, status="ativo").values_list("class_group_id", flat=True))
    out = []
    for c, s in teacher_pairs(user):
        subject = Subject.objects.filter(pk=s).first()
        if c in classes and subject and component_for(subject) == item.component:
            out.append((ClassGroup.objects.get(pk=c), subject))
    return out


def student_projection(request, student_id):
    user = request.user
    student, subjects = _student_or_403(user, student_id)
    today = timezone.localdate()
    target = None
    tid = request.GET.get("habilidade", "")
    if digits(tid):
        target = get_object_or_404(CurriculumItem.objects.filter(CurriculumItem.visible_q(user.school)), pk=int(tid))
    order = request.GET.get("ordem", "prioridade")
    order = order if order in gaps.CRITERIA else "prioridade"
    evs = (SkillEvidence.objects.filter(student=student).select_related("item", "subject")
           .order_by("-observed_on", "-pk"))
    if subjects is not None:
        evs = evs.filter(subject_id__in=subjects)
    recent = list(evs[:15])
    timeline = list(zip(recent, evidence_urls(recent)))
    ups = gaps.upcoming_items(student, today, days=45)
    up_items = CurriculumItem.objects.in_bulk(list(ups))
    up_states = gaps.item_states(student, list(up_items.values()), today=today)  # duas consultas para todas
    upcoming = []
    for pk, uses in ups.items():
        it = up_items.get(pk)
        if it is None:
            continue
        upcoming.append({"item": it, "uses": sorted(uses, key=lambda u: u[2]), "a": up_states[pk]})
    upcoming.sort(key=lambda r: r["uses"][0][2])
    prio = gaps.priorities(student, user.school, subjects, order=order, today=today)
    analysis = prop = hor = scen = estimate = None
    pairs = []
    if target:
        analysis = gaps.gap_analysis(student, target, user.school, subjects, today)
        # propagação a partir da lacuna mais relevante: a própria habilidade, se fraca; senão o 1º pré-requisito aberto
        origin = target
        open_rows = [r for r in analysis["rows"] if r["kind"] in ("confirmada", "situacao", "reavaliar", "hipotese")]
        if analysis["target_state"].effective not in gaps.WEAK and open_rows:
            origin = open_rows[0]["item"]
        prop = {"origin": origin, "rows": gaps.propagation(student, origin, user.school, today=today)}
        hor = gaps.horizon(student, [{"item": origin}] + prop["rows"], today)
        scen = gaps.scenarios(student, origin, user.school, prop["rows"])
        pairs = _teach_pairs(user, student, target)
        from . import bkt

        estimate = bkt.estimate(bkt.active_run(user.school), student, target)
    ivs = (LearningIntervention.objects.filter(students=student).select_related("item", "target_item", "subject")
           .order_by("-starts_on"))
    if subjects is not None:
        ivs = ivs.filter(subject_id__in=subjects)
    history = []
    for iv in ivs[:10]:
        mine = [r for r in outcomes(iv) if r["student"].pk == student.pk]
        history.append({"iv": iv, "result": mine[0] if mine else None})
    create_audit_log(user=user, action="view", request=request, target=student,
                     detail=f"Consultou o mapa de aprendizagem e projeção de {student}"
                            + (f" ({target.code})" if target else ""))
    return render(request, "cognitio/student_projection.html", {
        "student": student, "components": student_components(user, student), "timeline": timeline,
        "upcoming": upcoming[:12], "priorities": prio, "order": order, "criteria": gaps.CRITERIA,
        "target": target, "analysis": analysis, "prop": prop, "horizon": hor, "scenarios": scen,
        "history": history, "labels": RESULT_LABELS, "pairs": pairs, "estimate": estimate,
        "judgment_states": SkillJudgment.State.choices, "today": today,
        "can_judge": user.role in (Role.PROFESSOR.value, Role.COORDENACAO.value),
        "subject_limited": subjects is not None,
    })


@require_POST
def judgment_save(request, student_id):
    """Registra a decisão do professor (com fundamento) sobre uma habilidade do estudante."""
    user = request.user
    student, subjects = _student_or_403(user, student_id)
    if user.role not in (Role.PROFESSOR.value, Role.COORDENACAO.value):
        raise PermissionDenied
    item = get_object_or_404(CurriculumItem.objects.filter(CurriculumItem.visible_q(user.school)),
                             pk=as_id(request.POST.get("habilidade")))
    if user.role == Role.PROFESSOR.value and not _teach_pairs(user, student, item):
        raise PermissionDenied  # professor decide só no componente que leciona a este estudante
    back = (f"{reverse('cognitio:student_projection', args=[student.pk])}"
            f"?habilidade={request.POST.get('alvo') or item.pk}")
    if request.POST.get("acao") == "retirar":
        n = SkillJudgment.objects.filter(student=student, item=item, active=True).update(active=False)
        create_audit_log(user=user, action="update", request=request, target=student,
                         detail=f"Retirou a decisão sobre {item.code} de {student} ({n})")
        messages.success(request, "Decisão retirada; volta a valer o estado calculado pelas evidências.")
        return redirect(back)
    state = request.POST.get("estado")
    rationale = (request.POST.get("fundamento") or "").strip()
    if state not in dict(SkillJudgment.State.choices) or len(rationale) < 10:
        messages.error(request, "Escolha a decisão e escreva o fundamento (pelo menos 10 caracteres).")
        return redirect(back)
    SkillJudgment.objects.filter(student=student, item=item, active=True).update(active=False)
    SkillJudgment.objects.create(school=user.school, student=student, item=item, state=state,
                                 rationale=rationale[:2000], decided_by=user)
    create_audit_log(user=user, action="create", request=request, target=student,
                     detail=f"Decisão do professor sobre {item.code} de {student}: "
                            f"{dict(SkillJudgment.State.choices)[state]}")
    messages.success(request, "Decisão registrada. Ela vale até surgir evidência nova; aí a análise pede revisão.")
    return redirect(back)


def assistant_page(request):
    """Assistente analítico por regras (Prompt 17, §14). GET com ``pergunta``: cada pergunta vai para a auditoria."""
    from apps.academics.models import ClassGroup

    from . import assistant

    user = request.user
    if not access.can_use(user):
        raise PermissionDenied
    classes = [cg for cg in ClassGroup.objects.filter(school=user.school, school_year__is_current=True)
               .order_by("name") if access.can_view_class(user, cg)]
    cg = None
    if digits(request.GET.get("turma") or ""):
        cg = next((c for c in classes if c.pk == int(request.GET["turma"])), None)
    students = assistant.visible_students(user, cg) if cg else []
    student = None
    if digits(request.GET.get("estudante") or ""):
        student = next((s for s in (students or assistant.visible_students(user))
                        if s.pk == int(request.GET["estudante"])), None)
    question = (request.GET.get("pergunta") or "").strip()[:400]
    code = (request.GET.get("habilidade") or "").strip().upper()[:30]
    item = (CurriculumItem.objects.filter(CurriculumItem.visible_q(user.school), code=code, active=True).first()
            if code else None)
    codes = []
    if cg:  # sugestões do campo: habilidades das disciplinas da turma que a pessoa acompanha
        from apps.academics.models import Subject, TeacherAssignment
        from apps.curriculum.models import year_for

        allowed = access.class_subjects(user, cg)
        sids = set(TeacherAssignment.objects.filter(class_group=cg).values_list("subject_id", flat=True))
        for subject in Subject.objects.filter(pk__in=sids if allowed is None else sids & allowed):
            comp = component_for(subject)
            if comp:
                codes += [(i.code, i.text[:80]) for i in CurriculumItem.for_pair(user.school, comp, year_for(cg))
                          .filter(kind="habilidade").order_by("code")]
    result = None
    if question:
        result = assistant.answer(user, question, student=student, class_group=cg, item=item)
        create_audit_log(user=user, action="view", request=request, target=student or cg,
                         target_type=None if (student or cg) else "Assistente", target_id=None if (student or cg)
                         else "pergunta",
                         detail=f"Assistente EIA-Cognitio: {question[:200]}")
    return render(request, "cognitio/assistant.html", {
        "question": question, "result": result, "examples": assistant.EXAMPLES, "classes": classes,
        "cg": cg, "students": students, "student": student, "code": code, "codes": codes,
    })


def class_council(request, class_id):
    """Preparação do conselho de classe: por estudante, em ordem alfabética, estados por componente até o
    fim do período, lacunas confirmadas, intervenções e seus resultados, decisões e reavaliações pendentes.
    Sem pontuação nem ordenação por desempenho. Professor vê só as disciplinas que leciona na turma."""
    import datetime
    from collections import Counter

    from django.db.models import Exists, OuterRef

    from apps.academics.models import ClassGroup
    from apps.school_calendar.models import CalendarPeriod

    from .mastery import STATES, apply_judgments, assess, group_evidence
    from .models import MasteryScale, SkillObservation
    from .recommend import next_step

    user = request.user
    cg = get_object_or_404(ClassGroup, pk=class_id, school=user.school)
    subjects = access.class_subjects(user, cg)
    if subjects is not None and not subjects:
        raise PermissionDenied
    today = timezone.localdate()
    periods = list(CalendarPeriod.objects.filter(school=user.school, school_year=cg.school_year).order_by("start"))
    period = None
    if digits(request.GET.get("periodo") or ""):
        period = next((p for p in periods if p.pk == int(request.GET["periodo"])), None)
    if period is None:  # o período em curso, ou o último que já começou
        started = [p for p in periods if p.start <= today]
        period = started[-1] if started else None
    end = min(period.end, today) if period else today
    start = period.start if period else end - datetime.timedelta(days=90)
    students = sorted({e.student for e in Enrollment.objects.filter(class_group=cg, status="ativo")
                       .select_related("student")}, key=lambda s: s.full_name)
    evs = SkillEvidence.objects.filter(class_group=cg, student__in=students, observed_on__lte=end) \
        .select_related("item").order_by("observed_on")
    if subjects is not None:
        evs = evs.filter(subject_id__in=subjects)
    scale = MasteryScale.for_school(user.school)
    assessed = apply_judgments({k: assess(v, scale, end) for k, v in group_evidence(evs).items()})
    ivs = LearningIntervention.objects.filter(class_group=cg, starts_on__lte=end).prefetch_related("students") \
        .select_related("item")
    if subjects is not None:
        ivs = ivs.filter(subject_id__in=subjects)
    ivs = list(ivs)
    iv_out = {iv.pk: outcomes(iv) for iv in ivs}
    newer = SkillEvidence.objects.filter(student=OuterRef("student"), item=OuterRef("item"),
                                         observed_on__gt=OuterRef("observed_on"))
    rechecks = Counter(SkillObservation.objects.filter(class_group=cg, recheck_on__lte=today)
                       .exclude(Exists(newer)).values_list("student_id", flat=True))
    # Trajetória e indicadores precoces até o fim do período, desde o início do ano letivo (trajectory.py).
    from apps.analytics.bi import _school_year_dates
    from apps.pedagogy.access import can_view_occurrences

    from .trajectory import TRENDS, class_overview

    year_start = min(_school_year_dates(user.school, end)[0], start)
    signals = {r["student"].pk: r for r in class_overview(cg, year_start, end, today=end,
                                                         behavior=can_view_occurrences(user),
                                                         subject_ids=subjects)["rows"]}
    rows, item_diff = [], Counter()
    for st in students:
        sig = signals.get(st.pk)
        mine = {iid: a for (sid, iid), a in assessed.items() if sid == st.pk}
        comps = {}
        confirmed = []
        for iid, a in mine.items():
            item = a.evidence[0].item if a.evidence else None
            if item is None:
                continue
            c = comps.setdefault(item.component or "Outros", Counter())
            c[a.state] += 1
            if a.state == "dificuldade":
                item_diff[item.code] += 1
            kind, _why = gaps.classify(a, scale, end)
            if kind == "confirmada":
                confirmed.append(item)
        my_ivs = []
        for iv in ivs:
            if st in iv.students.all():
                res = [r for r in iv_out[iv.pk] if r["student"].pk == st.pk]
                my_ivs.append({"iv": iv, "result": res[0] if res else None})
        rows.append({
            "student": st,
            "components": [(comp, [(STATES[s][0], c[s]) for s in STATES if c[s]]) for comp, c in sorted(comps.items())],
            "confirmed": sorted(confirmed, key=lambda i: i.code),
            "interventions": my_ivs,
            "judgments": sum(1 for a in mine.values() if a.computed_state),
            "rechecks": rechecks.get(st.pk, 0),
            "no_evidence": not mine,
            "signals": sig["indicators"] if sig else [],
            "trend": TRENDS[sig["overall"]["trend"]] if sig else None,
        })
    retake = [(code, n) for code, n in item_diff.most_common() if n * 10 >= 3 * max(len(students), 1)]
    summary = {"students": len(students), "with_evidence": sum(1 for r in rows if not r["no_evidence"]),
               "confirmed": sum(len(r["confirmed"]) for r in rows),
               "ivs_active": sum(1 for iv in ivs if iv.status in ("aceita", "andamento")),
               "with_signals": sum(1 for r in rows if r["signals"]),
               # lista de pares: um Counter no template vira Counter["items"] == 0
               "next": sorted(Counter(next_step(iv, iv_out[iv.pk])["label"] for iv in ivs).items())}
    create_audit_log(user=user, action="view", request=request, target=cg,
                     detail=f"Consultou a preparação do conselho de classe da turma {cg}")
    return render(request, "cognitio/class_council.html", {
        "cg": cg, "rows": rows, "summary": summary, "retake": retake, "periods": periods, "period": period,
        "start": start, "end": end, "subject_limited": subjects is not None, "labels": RESULT_LABELS,
    })


def my_judgments(request):
    """Decisões registradas pela pessoa: as que perderam a vez para evidência mais nova vêm primeiro."""
    user = request.user
    if user.role not in (Role.PROFESSOR.value, Role.COORDENACAO.value):
        raise PermissionDenied
    rows = []
    for j in (SkillJudgment.objects.filter(decided_by=user, active=True, school=user.school)
              .select_related("student", "item").order_by("-decided_on", "-pk")):
        last = (SkillEvidence.objects.filter(student=j.student, item=j.item).order_by("-observed_on")
                .values_list("observed_on", flat=True).first())
        rows.append({"j": j, "last": last, "stale": bool(last and last > j.decided_on)})
    rows.sort(key=lambda r: (not r["stale"], -r["j"].decided_on.toordinal()))
    return render(request, "cognitio/my_judgments.html", {"rows": rows})
