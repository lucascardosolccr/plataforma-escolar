"""Tela da frequência semanal com limites de controle (cálculo em ``spc``)."""

import datetime

from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone

from apps.academics.models import ClassGroup, SchoolYear
from apps.core.models import Role
from apps.core.params import as_id

from . import charts, spc
from .access import can_view_class_dashboard, can_view_institutional_dashboard

STAFF = (Role.DIRECAO.value, Role.COORDENACAO.value, Role.SECRETARIA.value, Role.ADMIN.value, Role.PROFESSOR.value)


def _year_window(school, today):
    year = SchoolYear.objects.filter(school=school, is_current=True).first()
    start = (year.start_date if year and year.start_date else today - datetime.timedelta(days=180))
    end = min(today, year.end_date) if year and year.end_date else today
    return year, start, end


def attendance_control(request):
    user = request.user
    if not user.is_authenticated or user.role not in STAFF or not user.school_id:
        raise PermissionDenied
    school = user.school
    today = timezone.localdate()
    year, start, end = _year_window(school, today)
    classes = [c for c in ClassGroup.objects.filter(school=school, school_year=year).order_by("name")
               if can_view_class_dashboard(user, c)] if year else []
    whole = can_view_institutional_dashboard(user)
    class_id = as_id(request.GET.get("turma"))
    chosen = None
    if class_id:
        chosen = next((c for c in classes if str(c.pk) == class_id), None)
        if chosen is None:
            raise Http404
    elif not whole and classes:
        chosen = classes[0]
    result = spc.control(school, start, end, chosen) if (chosen or whole) else None
    return render(request, "analytics/attendance_control.html", {
        "result": result, "chart": charts.control_chart(result["chart"]) if result else None,
        "classes": [(c.pk, c.name) for c in classes], "chosen": chosen, "whole": whole,
        "class_id": class_id or "", "start": start, "end": end, "min_weeks": spc.MIN_WEEKS,
    })
