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
from apps.curriculum.models import CurriculumItem, component_for
from apps.registry.models import Enrollment, Student

from . import access, gaps
from .models import LearningIntervention, SkillEvidence, SkillJudgment
from .recommend import RESULT_LABELS, outcomes
from .summary import student_components


def evidence_url(e):
    """Endereço do registro original de uma evidência (cada tela confere o próprio acesso)."""
    from apps.pedagogy.models import Grade, GroupWorkDelivery, Submission

    from .models import QuestionResponse

    try:
        if e.source_type == "questao":
            r = QuestionResponse.objects.select_related("question").filter(pk=e.source_id).first()
            return reverse("cognitio:responses", args=[r.question.evaluation_id]) if r else None
        if e.source_type == "avaliacao":
            g = Grade.objects.filter(pk=e.source_id).first()
            return reverse("pedagogy:evaluation_grade", args=[g.evaluation_id]) if g else None
        if e.source_type == "atividade":
            s = Submission.objects.filter(pk=e.source_id).first()
            return reverse("pedagogy:activity_detail", args=[s.activity_id]) if s else None
        if e.source_type == "trabalho":
            d = GroupWorkDelivery.objects.filter(pk=e.source_id).first()
            return reverse("pedagogy:group_work_detail", args=[d.group_work_id]) if d else None
        if e.source_type == "texto":
            return reverse("cognitio:text_detail", args=[e.source_id])
    except NoReverseMatch:
        return None
    return None


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
    if tid.isdigit():
        target = get_object_or_404(CurriculumItem.objects.filter(CurriculumItem.visible_q(user.school)), pk=int(tid))
    order = request.GET.get("ordem", "prioridade")
    order = order if order in gaps.CRITERIA else "prioridade"
    evs = (SkillEvidence.objects.filter(student=student).select_related("item", "subject")
           .order_by("-observed_on", "-pk"))
    if subjects is not None:
        evs = evs.filter(subject_id__in=subjects)
    timeline = [(e, evidence_url(e)) for e in evs[:15]]
    ups = gaps.upcoming_items(student, today, days=45)
    upcoming = []
    for pk, uses in ups.items():
        it = CurriculumItem.objects.filter(pk=pk).first()
        if it is None:
            continue
        a = gaps.item_state(student, it, today=today)
        upcoming.append({"item": it, "uses": sorted(uses, key=lambda u: u[2]), "a": a})
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
                             pk=request.POST.get("habilidade"))
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
    if (request.GET.get("turma") or "").isdigit():
        cg = next((c for c in classes if c.pk == int(request.GET["turma"])), None)
    students = assistant.visible_students(user, cg) if cg else []
    student = None
    if (request.GET.get("estudante") or "").isdigit():
        student = next((s for s in (students or assistant.visible_students(user))
                        if s.pk == int(request.GET["estudante"])), None)
    question = (request.GET.get("pergunta") or "").strip()[:400]
    result = None
    if question:
        result = assistant.answer(user, question, student=student, class_group=cg)
        create_audit_log(user=user, action="view", request=request, target=student or cg,
                         target_type=None if (student or cg) else "Assistente", target_id=None if (student or cg)
                         else "pergunta",
                         detail=f"Assistente EIA-Cognitio: {question[:200]}")
    return render(request, "cognitio/assistant.html", {
        "question": question, "result": result, "examples": assistant.EXAMPLES, "classes": classes,
        "cg": cg, "students": students, "student": student,
    })
