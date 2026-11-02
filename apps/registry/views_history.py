"""Histórico escolar consolidado do estudante (Prompt 14 §9.1; Prompt 13 §6.4).

Um quadro por matrícula (ano letivo e turma) com:

- a média de cada disciplina, pela mesma regra do boletim
  (``analytics.services._averages_from_grades``), só com avaliações
  publicadas daquela turma;
- a frequência registrada naquela turma, com o limite de faltas da escola;
- a situação da matrícula.

Não é o histórico escolar oficial (documento da rede, com carga horária e
resultado final homologado): a página diz isso e não declara aprovação nem
reprovação, só a média e a referência de aprovação de cada disciplina.

Acesso: quem pode ver a ficha, menos o professor, que acompanha o estudante
pelo painel restrito às disciplinas que leciona. Toda consulta vai para a
auditoria.
"""

from collections import defaultdict

from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from apps.analytics.bi import attendance_summary
from apps.analytics.services import _averages_from_grades, rules_by_subject, school_max_absences
from apps.core.models import Role, create_audit_log
from apps.pedagogy.models import AttendanceRecord, Evaluation, Grade

from .access import can_view_student
from .models import Student

PUBLISHED = Evaluation.Status.PUBLISHED


def can_view_school_record(user, student):
    return user.is_authenticated and user.role != Role.PROFESSOR.value and can_view_student(user, student)


def build_record(student):
    """Lista de anos, do mais antigo ao mais recente, com médias e frequência."""
    enrollments = list(student.enrollments.select_related("class_group", "school_year")
                       .order_by("school_year__start_date", "school_year__name", "pk"))
    class_ids = [e.class_group_id for e in enrollments]
    grades = defaultdict(list)
    for g in (Grade.objects.filter(student=student, evaluation__class_group_id__in=class_ids,
                                   evaluation__status=PUBLISHED, value__isnull=False)
              .select_related("evaluation", "evaluation__subject")):
        grades[g.evaluation.class_group_id].append(g)
    attendance = defaultdict(list)
    for cid, d, st in (AttendanceRecord.objects.filter(student=student, class_group_id__in=class_ids)
                       .order_by("date").values_list("class_group_id", "date", "status")):
        attendance[cid].append((d, st))
    rules = rules_by_subject(student.school)
    limit = float(school_max_absences(student.school))
    years = []
    for e in enrollments:
        subjects = _averages_from_grades(grades.get(e.class_group_id, []), rules)
        att = attendance_summary(attendance.get(e.class_group_id, []), limit)
        years.append({"enrollment": e, "subjects": subjects, "attendance": att,
                      "below": [s for s in subjects if s["below"]]})
    return years


def school_record(request, student_id):
    student = get_object_or_404(Student.objects.select_related("school"), pk=student_id,
                                school=request.user.school)
    if not can_view_school_record(request.user, student):
        raise PermissionDenied
    create_audit_log(user=request.user, action="view", request=request, target=student,
                     detail=f"Consultou o histórico escolar de {student.full_name}")
    return render(request, "registry/school_record.html", {
        "student": student, "years": build_record(student), "generated_at": timezone.now(),
    })
