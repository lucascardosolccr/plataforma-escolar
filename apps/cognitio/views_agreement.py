"""Concordância entre observadores: calibração de rubricas (coordenação e direção).

Mede o quanto professores concordam ao observar a mesma habilidade do mesmo estudante. É instrumento de
coordenação para calibrar o olhar avaliativo — não avaliação de professor. Método em ``agreement.py``.
"""

from django.core.exceptions import PermissionDenied
from django.shortcuts import render

from apps.academics.models import ClassGroup, Subject
from apps.core.models import Role
from apps.core.params import digits

from . import agreement
from .models import SkillObservation
from .views import _period  # reaproveita os períodos do calendário oficial


def _staff_team(user):
    return getattr(user, "is_authenticated", False) and user.role in (Role.COORDENACAO.value, Role.DIRECAO.value)


def observer_agreement(request):
    user = request.user
    if not _staff_team(user):
        raise PermissionDenied
    from apps.coordination.scope import class_scope

    start, end, period_label, period_options, chosen = _period(request, user.school)
    scope = class_scope(user) if user.role == Role.COORDENACAO.value else None

    classes = ClassGroup.objects.filter(school=user.school, school_year__is_current=True).order_by("name")
    if scope is not None:
        classes = classes.filter(pk__in=scope)
    subjects = Subject.objects.filter(school=user.school).order_by("name")

    cg = None
    if digits(request.GET.get("turma", "")):
        cg = classes.filter(pk=int(request.GET["turma"])).first()
    subj = None
    if digits(request.GET.get("disciplina", "")):
        subj = subjects.filter(pk=int(request.GET["disciplina"])).first()

    data = agreement.summary(user.school, start, end, class_group=cg,
                             class_ids=None if scope is None else list(scope), subject=subj)
    return render(request, "cognitio/agreement.html", {
        "data": data, "classes": classes, "subjects": subjects, "turma": cg, "disciplina": subj,
        "period_label": period_label, "period_options": period_options, "periodo": chosen,
        "scale": SkillObservation.Level.choices,
    })
