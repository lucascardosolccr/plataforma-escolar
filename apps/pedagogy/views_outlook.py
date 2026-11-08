"""Agenda e faltas do estudante: o que vence logo e quantas faltas ainda cabem no ano (ver ``outlook``).

Família (filhos com vínculo aprovado), o próprio estudante e a equipe que pode abrir o painel do estudante.
"""

from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, render

from apps.analytics.access import can_view_student_dashboard
from apps.core.models import Role
from apps.core.params import id_param
from apps.registry.models import GuardianLink, Student

from . import access as acc
from . import outlook


def _students_for(user):
    if user.role == Role.RESPONSAVEL.value:
        return [link.student for link in GuardianLink.objects.filter(guardian=user, status="aprovado")
                .select_related("student").order_by("student__first_name")]
    if user.role == Role.ESTUDANTE.value:
        own = acc.own_student(user)
        return [own] if own else []
    return []


def student_outlook(request):
    user = request.user
    choices = _students_for(user)
    wanted = id_param(request, "estudante")
    if wanted:
        student = get_object_or_404(Student, pk=int(wanted))
        if not (student in choices or can_view_student_dashboard(user, student)):
            raise PermissionDenied
    elif choices:
        student = choices[0]
    else:
        if user.role in (Role.RESPONSAVEL.value, Role.ESTUDANTE.value):
            return render(request, "pedagogy/outlook.html", {"student": None, "choices": []})
        raise PermissionDenied
    return render(request, "pedagogy/outlook.html", {
        "student": student, "choices": choices if len(choices) > 1 else [],
        "is_own": user.role == Role.ESTUDANTE.value,
        "att": outlook.attendance_outlook(student),
        "agenda": outlook.upcoming(student, days=30),
    })
