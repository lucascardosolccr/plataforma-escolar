"""Resumo de aprendizagens para a família e o estudante (opcional, desligado por padrão).

Linguagem própria, sem estigma e sem dado interno da equipe:
- "já demonstradas nas atividades" (consolidada ou em consolidação);
- "em desenvolvimento, com acompanhamento do professor" (em desenvolvimento ou
  dificuldade observada: a família não recebe o rótulo "dificuldade");
- "ainda sem evidência suficiente" (só a contagem).
Sem alertas, sem porcentagens, sem tipos de erro, sem comparação com colegas.
Inclui as devolutivas escritas que o professor registrou nas produções revisadas.
"""

from collections import OrderedDict

from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, render

from apps.core.models import Role, create_audit_log
from apps.registry.models import Student

from .mastery import assess
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
    for evs in by_item.values():
        item = evs[0].item
        a = assess(evs, scale)
        if a.state in ("consolidada", "consolidacao"):
            key = "done"
        elif a.state in ("desenvolvimento", "dificuldade", "contraditoria"):
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
        "student": student, "comps": comps, "feedback": feedback, "is_student": request.user.role == Role.ESTUDANTE.value})
