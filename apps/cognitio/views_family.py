"""Resumo de aprendizagens para a família e o estudante (opcional, desligado por padrão).

Linguagem própria, sem estigma e sem dado interno da equipe:
- "já demonstradas nas atividades" (consolidada ou em consolidação);
- "em desenvolvimento, com acompanhamento do professor" (em desenvolvimento ou
  dificuldade observada: a família não recebe o rótulo "dificuldade");
- "ainda sem evidência suficiente" (só a contagem).
Sem alertas, sem porcentagens, sem tipos de erro, sem comparação com colegas.
Inclui as devolutivas escritas que o professor registrou nas produções revisadas.
"""

import datetime
from collections import OrderedDict

from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, render

from apps.core.models import Role, create_audit_log
from apps.registry.models import Student

from .mastery import apply_judgments, assess
from .models import MasteryScale, SkillEvidence, TextAnalysis


def family_can_view(user, student):
    from apps.registry.access import guardian_of

    if not getattr(user, "is_authenticated", False) or student.school_id != user.school_id:
        return False
    if not MasteryScale.for_school(student.school).share_with_family:
        return False
    if user.role == Role.RESPONSAVEL.value:
        return guardian_of(user, student)
    if user.role == Role.ESTUDANTE.value:
        return student.user_id == user.pk
    return False


def learning_summary(request, student_id):
    student = get_object_or_404(Student, pk=student_id)
    if not family_can_view(request.user, student):
        raise PermissionDenied
    scale = MasteryScale.for_school(student.school)
    by_item = OrderedDict()
    for e in SkillEvidence.objects.filter(student=student).select_related("item").order_by("observed_on"):
        by_item.setdefault(e.item_id, []).append(e)
    comps = OrderedDict()
    # decisão do professor vale aqui também (mesmo estado das telas da equipe)
    assessed = apply_judgments({(student.pk, iid): assess(evs, scale) for iid, evs in by_item.items()})
    for iid, evs in by_item.items():
        item = evs[0].item
        a = assessed[(student.pk, iid)]
        if a.state in ("consolidada", "consolidacao"):
            key = "done"
        elif a.state in ("desenvolvimento", "dificuldade", "contraditoria", "reverificar"):
            key = "developing"
        else:
            key = "pending"
        c = comps.setdefault(item.component or "Outros", {"done": [], "developing": [], "pending": 0})
        if key == "pending":
            c["pending"] += 1
        else:
            c[key].append(item)
    feedback = TextAnalysis.objects.filter(student=student, reviewed=True).exclude(teacher_feedback="") \
        .select_related("subject")[:10]
    create_audit_log(user=request.user, action="view", request=request, target=student,
                     detail=f"Família/estudante consultou o resumo de aprendizagens de {student}")
    return render(request, "cognitio/family_summary.html", {
        "student": student, "comps": comps, "feedback": feedback, "upcoming": upcoming_for_family(student),
        "is_student": request.user.role == Role.ESTUDANTE.value})


def upcoming_for_family(student, today=None, days=30):
    """Habilidades das próximas semanas, só do que a família já pode ver: atividades publicadas (mesma regra
    das telas da família) e avaliações publicadas ou com data divulgada. Prova não divulgada nunca aparece."""
    from django.db.models import Q
    from django.utils import timezone

    from apps.pedagogy.models import Activity, Evaluation
    from apps.registry.models import Enrollment

    today = today or timezone.localdate()
    end = today + datetime.timedelta(days=days)
    classes = Enrollment.objects.filter(student=student, status="ativo").values("class_group_id")
    out = OrderedDict()
    acts = (Activity.objects.filter(Activity.family_visible_q(today=today), class_group_id__in=classes,
                                    status=Activity.Status.PUBLISHED, deadline__gte=today, deadline__lte=end)
            .select_related("subject").prefetch_related("curriculum").order_by("deadline"))
    evals = (Evaluation.objects.filter(Q(announced=True) | Q(status=Evaluation.Status.PUBLISHED),
                                       class_group_id__in=classes, date__gte=today, date__lte=end)
             .select_related("subject").prefetch_related("curriculum").order_by("date"))
    dated = [(a.deadline, "atividade", a) for a in acts] + [(e.date, "avaliação", e) for e in evals]
    for when, what, obj in sorted(dated, key=lambda t: t[0]):
        for it in obj.curriculum.all():
            if it.kind in ("habilidade", "objetivo_df", "proprio"):
                out.setdefault(it.pk, {"item": it, "when": when, "what": what, "subject": obj.subject})
    return list(out.values())[:12]
