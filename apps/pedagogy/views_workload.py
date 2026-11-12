"""Concentração de prazos por turma (planejamento): professor, coordenação e direção.

Mostra os dias com prova, trabalho e atividade demais de uma vez, para a equipe reequilibrar. Método em
``workload.py``. Só leitura: não altera nenhuma data.
"""

import datetime

from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.utils import timezone

from apps.academics.models import ClassGroup
from apps.core.models import Role

from . import workload

HORIZON = 60  # dias à frente: janela de planejamento


def deadline_load(request):
    user = request.user
    if user.role not in (Role.PROFESSOR.value, Role.COORDENACAO.value, Role.DIRECAO.value):
        raise PermissionDenied
    from apps.academics.permissions import teacher_class_ids
    from apps.coordination.scope import class_scope

    today = timezone.localdate()
    end = today + datetime.timedelta(days=HORIZON)
    classes = ClassGroup.objects.filter(school=user.school, school_year__is_current=True).order_by("name")
    if user.role == Role.PROFESSOR.value:
        classes = classes.filter(pk__in=teacher_class_ids(user))
    elif user.role == Role.COORDENACAO.value:
        scope = class_scope(user)
        if scope is not None:
            classes = classes.filter(pk__in=scope)

    rows = []
    for cg in classes:
        days = workload.by_day(cg, today, end)
        rows.append({"class_group": cg, "heavy": [d for d in days if d["overloaded"]],
                     "total": sum(d["count"] for d in days)})
    return render(request, "pedagogy/workload.html", {
        "rows": rows, "horizon": HORIZON, "today": today, "end": end, "heavy": workload.HEAVY})
