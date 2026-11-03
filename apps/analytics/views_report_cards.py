"""Boletins da turma para impressão: um por estudante, um por página.

Para a reunião de entrega de boletins a secretaria imprimia estudante por estudante. Aqui a turma inteira
sai de uma vez, no período escolhido (bimestre do calendário, ano letivo ou datas), com a mesma regra de
média do boletim individual e do histórico escolar (``services._averages_from_grades``) e o limite de
faltas da escola. As consultas são feitas para a turma toda, não por estudante.

Quem imprime: secretaria, direção, administração e coordenação (só nas turmas da designação). O professor
não, porque veria as médias das disciplinas que não leciona. Cada impressão vai para a auditoria.
"""

from collections import defaultdict

from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from apps.academics.models import ClassGroup
from apps.core.models import Role, create_audit_log
from apps.pedagogy.models import AttendanceRecord, Evaluation, Grade
from apps.registry.models import Enrollment

from . import bi
from .access import can_view_class_dashboard
from .services import _averages_from_grades, rules_by_subject, school_max_absences


def can_print_report_cards(user, class_group):
    return can_view_class_dashboard(user, class_group) and user.role != Role.PROFESSOR.value


def build_cards(class_group, period):
    enrollments = list(Enrollment.objects.filter(class_group=class_group, status="ativo")
                       .select_related("student").order_by("student__first_name", "student__last_name"))
    ids = [e.student_id for e in enrollments]
    grades = defaultdict(list)
    for g in (Grade.objects.filter(student_id__in=ids, evaluation__class_group=class_group,
                                   evaluation__status=Evaluation.Status.PUBLISHED, value__isnull=False,
                                   evaluation__date__gte=period.start, evaluation__date__lte=period.end)
              .select_related("evaluation", "evaluation__subject")):
        grades[g.student_id].append(g)
    attendance = defaultdict(list)
    for sid, d, st in (AttendanceRecord.objects.filter(student_id__in=ids, class_group=class_group,
                                                       date__gte=period.start, date__lte=period.end)
                       .order_by("date").values_list("student_id", "date", "status")):
        attendance[sid].append((d, st))
    rules = rules_by_subject(class_group.school)
    limit = float(school_max_absences(class_group.school))
    return [{"enrollment": e, "student": e.student,
             "subjects": _averages_from_grades(grades.get(e.student_id, []), rules),
             "attendance": bi.attendance_summary(attendance.get(e.student_id, []), limit)}
            for e in enrollments]


def class_report_cards(request, class_group_id):
    cg = get_object_or_404(ClassGroup.objects.select_related("school_year", "school"), pk=class_group_id,
                           school=request.user.school)
    if not can_print_report_cards(request.user, cg):
        raise PermissionDenied
    period = bi.resolve_period(request.GET, cg.school)
    cards = build_cards(cg, period)
    create_audit_log(user=request.user, action="view", request=request, target=cg,
                     detail=f"Abriu os boletins da turma {cg.name} ({len(cards)} estudante(s), {period.label})")
    return render(request, "analytics/class_report_cards.html", {
        "class_group": cg, "cards": cards, "period": period, "presets": bi.presets_for(cg.school),
        "generated_at": timezone.now(),
    })
