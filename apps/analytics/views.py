"""Views dos painéis e relatórios (Fase 6).

Toda barreira de acesso é verificada aqui, no servidor, para a tela, o CSV e a
impressão. Os painéis só apresentam dados que a matriz RBAC permite ao perfil
do usuário.
"""

import csv
from datetime import datetime

from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.text import slugify

from apps.academics.models import ClassGroup
from apps.core.params import id_param
from apps.core.models import Role
from apps.pedagogy.access import (
    can_view_observations,
    can_view_occurrences,
    can_view_plans,
)
from apps.registry.access import guardian_of
from apps.registry.models import Enrollment, GuardianLink, Student

from . import charts, reports, services
from .access import (
    can_view_class_dashboard,
    can_view_institutional_dashboard,
    can_view_reports,
    can_view_secretaria_panel,
    can_view_student_dashboard,
)


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _csv_safe(value):
    """Evita que um texto importado execute fórmula ao abrir o CSV no Excel."""
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def _report_params(request, for_csv=False):
    student = None
    if id_param(request, "student"):
        student = get_object_or_404(
            Student, pk=id_param(request, "student"), school=request.user.school
        )
    class_group = None
    if id_param(request, "class"):
        class_group = get_object_or_404(
            ClassGroup, pk=id_param(request, "class"), school=request.user.school
        )
    subject = None
    if id_param(request, "subject"):
        from apps.academics.models import Subject

        subject = Subject.objects.filter(
            school=request.user.school, pk=id_param(request, "subject")
        ).first()
    return {
        "student": student,
        "class_group": class_group,
        "subject": subject,
        "start": _parse_date(request.GET.get("start")),
        "end": _parse_date(request.GET.get("end")),
    }


def _enforce_scope(user, report, params):
    if params["student"] is not None:
        if not can_view_student_dashboard(user, params["student"]):
            raise PermissionDenied("Estudante fora do seu escopo de acesso.")
    if params["class_group"] is not None:
        if not can_view_class_dashboard(user, params["class_group"]):
            raise PermissionDenied("Turma fora do seu escopo de acesso.")


def _filters_context(user):
    return {
        "filter_students": reports.allowed_students(user).order_by("first_name", "last_name"),
        "filter_classes": reports.allowed_classes(user).order_by("name"),
        "filter_subjects": reports.subjects_for(user),
    }


def _default_student(user):
    """Responsável com um único dependente já abre o relatório preenchido."""
    if user.role == Role.RESPONSAVEL.value:
        students = list(reports.allowed_students(user)[:2])
        if len(students) == 1:
            return students[0]
    return None


# --------------------------------------------------------------------------- #
# Painel individual do estudante
# --------------------------------------------------------------------------- #
def student_dashboard(request, student_id):
    student = get_object_or_404(Student.objects.select_related("school"), pk=student_id)
    if not can_view_student_dashboard(request.user, student):
        raise PermissionDenied("Você não tem acesso ao painel deste estudante.")

    averages = services.subject_averages(student)
    evolution = services.grade_evolution(student)
    distribution = services.grade_distribution(student)
    attendance = services.attendance_stats(student)
    attendance_evo = services.attendance_evolution(student)
    activities = services.activity_stats(student)
    justifications = services.justification_stats(student)
    occurrences = services.occurrence_stats(student)
    plans = services.plan_stats(student)

    can_view_obs = can_view_observations(request.user, student)
    # Ocorrências e planos de acompanhamento têm regra própria e não seguem o
    # acesso ao prontuário. O estudante, em particular, vê o progresso
    # acadêmico e a frequência dele, mas não o registro disciplinar nem as
    # anotações feitas sobre ele — requisito da seção 7.5 do prompt de design.
    can_view_occ = can_view_occurrences(request.user, student)
    can_view_plan = can_view_plans(request.user, student)
    skills, strategies = services.consolidated_skills(student)
    difficulties = services.difficulty_contents(student)

    context = {
        "student": student,
        "active_class": services.active_class_group(student),
        "subject_averages": averages,
        "subject_chart": charts.bar_chart(
            [
                {
                    "label": a["subject"].name,
                    "value": a["average"],
                    "below": a["below"],
                }
                for a in averages
            ],
            suffix="",
        ),
        "evolution": evolution[-12:],
        "evolution_chart": charts.line_chart(
            [
                {"label": e["date"].strftime("%d/%m"), "value": e["value"]}
                for e in evolution[-12:]
            ],
            suffix=" pontos",
        ),
        "distribution_chart": charts.bar_chart(
            [{"label": d["label"], "value": d["count"]} for d in distribution],
            suffix=" notas",
        ),
        "attendance": attendance,
        "attendance_gauge": charts.gauge(
            attendance["percent"],
            limit=attendance["limit"],
            label="de presença",
        ),
        "attendance_chart": charts.line_chart(
            [{"label": a["month"], "value": a["percent"]} for a in attendance_evo],
            y_min=0,
            y_max=100,
            suffix="%",
        ),
        "activities": activities,
        "activity_chart": charts.h_bars(
            [
                {"label": "Entregues", "value": activities["delivered"]},
                {"label": "Pendentes", "value": activities["pending"]},
                {"label": "Atrasadas", "value": activities["late"]},
            ],
            suffix=" atividades",
        ),
        "justifications": justifications,
        "can_view_occ": can_view_occ,
        "occurrences": occurrences if can_view_occ else None,
        "occurrence_chart": charts.h_bars(
            [
                {"label": "Abertas", "value": occurrences["aberta"]},
                {"label": "Em acompanhamento", "value": occurrences["em_acompanhamento"]},
                {"label": "Encaminhadas", "value": occurrences["encaminhada"]},
                {"label": "Concluídas", "value": occurrences["concluida"]},
            ]
        )
        if can_view_occ
        else "",
        "can_view_plan": can_view_plan,
        "plans": plans if can_view_plan else None,
        "can_view_obs": can_view_obs,
        "difficulties": difficulties if can_view_obs else [],
        "skills": skills if can_view_obs else [],
        "strategies": strategies if can_view_obs else [],
        "timeline": services.timeline(student, include_plans=can_view_plan)
        if can_view_occ
        else [],
        "is_guardian": guardian_of(request.user, student),
        "generated_at": timezone.now(),
    }
    return render(request, "analytics/student_dashboard.html", context)


# --------------------------------------------------------------------------- #
# Painel por turma
# --------------------------------------------------------------------------- #
def class_dashboard(request, class_group_id):
    class_group = get_object_or_404(
        ClassGroup.objects.select_related("school", "school_year"), pk=class_group_id
    )
    if not can_view_class_dashboard(request.user, class_group):
        raise PermissionDenied("Você não tem acesso ao painel desta turma.")

    averages = services.class_subject_averages(class_group)
    attendance_percent = services.class_attendance_percent(class_group)
    students = services.class_students(class_group)
    attention = services.students_needing_attention(class_group)

    return render(
        request,
        "analytics/class_dashboard.html",
        {
            "class_group": class_group,
            "students_count": students.count(),
            "subject_averages": averages,
            "subject_chart": charts.bar_chart(
                [
                    {
                        "label": a["subject"].name,
                        "value": a["average"],
                        "below": a["below"],
                    }
                    for a in averages
                ]
            ),
            "attendance_percent": attendance_percent,
            "attendance_gauge": charts.gauge(attendance_percent, label="da turma"),
            "attention": attention,
            "generated_at": timezone.now(),
        },
    )


# --------------------------------------------------------------------------- #
# Painel institucional
# --------------------------------------------------------------------------- #
def institutional_dashboard(request):
    if not can_view_institutional_dashboard(request.user):
        raise PermissionDenied("Painel restrito à coordenação e direção.")
    data = services.institutional_indicators(request.user.school)
    classes = services.class_overview(request.user.school)
    limite = services.school_max_absences(request.user.school)
    min_attendance = 100 - float(limite) if limite is not None else None
    return render(
        request,
        "analytics/institutional_dashboard.html",
        {
            "data": data,
            "classes": classes,
            "total_students": data["students"],
            "active_enrollments": Enrollment.objects.filter(
                school=request.user.school, status="ativo"
            ).count(),
            "class_groups_count": data["class_groups"],
            # Sem registro de frequência é "sem dado" (—), nunca 0%: zero
            # pareceria uma turma inteira faltando.
            "attendance_rate": data["attendance_percent"],
            "min_attendance": min_attendance,
            "class_chart": charts.bar_chart(
                [
                    {
                        "label": c["class_group"].name,
                        "value": c["attendance"],
                        "below": (
                            c["attendance"] is not None
                            and min_attendance is not None
                            and c["attendance"] < min_attendance
                        ),
                    }
                    for c in classes
                ],
                max_value=100,
                suffix="%",
            ),
            "generated_at": timezone.now(),
        },
    )


# --------------------------------------------------------------------------- #
# Painel administrativo da secretaria
# --------------------------------------------------------------------------- #
def secretaria_panel(request):
    if not can_view_secretaria_panel(request.user):
        raise PermissionDenied("Painel restrito à secretaria.")
    school = request.user.school
    students = Student.objects.filter(school=school)
    pending_links = GuardianLink.objects.filter(
        school=school, status="pendente"
    ).select_related("guardian", "student")
    without_enrollment = students.filter(status="ativo").exclude(
        enrollments__status="ativo"
    )
    from apps.pedagogy.models import AbsenceJustification
    from apps.communication.models import ServiceRequest

    pending_justifications = AbsenceJustification.objects.filter(
        school=school, status__in=["recebida", "em_analise"]
    ).select_related("student")
    open_requests = ServiceRequest.objects.filter(school=school).exclude(
        status__in=["concluida", "recusada"]
    ).select_related("requester", "student")

    return render(
        request,
        "analytics/secretaria_panel.html",
        {
            "students_count": students.count(),
            "active_count": students.filter(status="ativo").count(),
            "pending_links": pending_links[:20],
            "pending_links_count": pending_links.count(),
            "without_enrollment": without_enrollment[:20],
            "without_enrollment_count": without_enrollment.count(),
            "pending_justifications": pending_justifications[:20],
            "pending_justifications_count": pending_justifications.count(),
            "open_requests": open_requests[:20],
            "open_requests_count": open_requests.count(),
            "generated_at": timezone.now(),
        },
    )


# --------------------------------------------------------------------------- #
# Relatórios
# --------------------------------------------------------------------------- #
def report_hub(request):
    if not can_view_reports(request.user):
        raise PermissionDenied
    grouped = {}
    for report in reports.reports_for(request.user):
        grouped.setdefault(report.category, []).append(report)
    return render(
        request,
        "analytics/report_hub.html",
        {"grouped": grouped},
    )


def report_detail(request, slug):
    report = reports.get_report(request.user, slug)
    params = _report_params(request)
    _enforce_scope(request.user, report, params)
    if report.needs_student and params["student"] is None:
        params["student"] = _default_student(request.user)

    missing = []
    if report.needs_student and params["student"] is None:
        missing.append("estudante")
    if report.slug == "frequencia" and not params["student"] and not params["class_group"]:
        missing.append("estudante ou turma")
    if report.needs_class and report.slug == "turma_indicadores" and not params["class_group"]:
        missing.append("turma")

    result = None
    error = None
    if not missing:
        try:
            result = report.run(request.user, params)
        except PermissionDenied as exc:
            error = str(exc)
    else:
        error = "Selecione " + " e ".join(missing) + " para gerar o relatório."

    is_print = request.GET.get("print") == "1"
    show_class = report.needs_class or report.slug in (
        "frequencia",
        "dificuldades",
        "ocorrencias",
        "acompanhamento",
        "justificativas",
    )
    show_student = report.needs_student or report.slug in (
        "frequencia",
        "solicitacoes",
    )
    show_subject = report.slug in ("evolucao", "dificuldades", "atividades_pendentes")
    show_dates = report.slug not in ("institucional", "pendencias_documentais", "boletim")
    context = {
        "report": report,
        "result": result,
        "error": error,
        "is_print": is_print,
        "generated_at": timezone.now(),
        "params": request.GET,
        "show_student": show_student,
        "show_class": show_class,
        "show_subject": show_subject,
        "show_dates": show_dates,
        **_filters_context(request.user),
    }
    template = "analytics/report_print.html" if is_print else "analytics/report_view.html"
    response = render(request, template, context)
    if is_print:
        response["Cache-Control"] = "no-store"
    return response


def report_csv(request, slug):
    report = reports.get_report(request.user, slug)
    params = _report_params(request)
    _enforce_scope(request.user, report, params)
    if report.needs_student and params["student"] is None:
        params["student"] = _default_student(request.user)
    if report.needs_student and params["student"] is None:
        raise PermissionDenied("Selecione o estudante.")
    if report.needs_class and params["class_group"] is None and not params["student"]:
        raise PermissionDenied("Selecione a turma.")

    result = report.run(request.user, params)

    filename = f"{slugify(report.title)}-{timezone.localdate():%Y%m%d}.csv"
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("\ufeff")
    writer = csv.writer(response, delimiter=";")
    writer.writerow([_csv_safe(report.title)])
    writer.writerow([_csv_safe(f"Gerado em: {timezone.localtime():%d/%m/%Y %H:%M}")])
    writer.writerow([_csv_safe(f"Período analisado: {result.period}")])
    writer.writerow([_csv_safe(f"Critérios: {result.criteria}")])
    writer.writerow([])
    writer.writerow([_csv_safe(c) for c in result.columns])
    for row in result.rows:
        writer.writerow([_csv_safe(c) for c in row])
    if not result.rows:
        writer.writerow(["(sem registros para os critérios informados)"])
    return response
