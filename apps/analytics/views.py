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
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from apps.academics.models import ClassGroup
from apps.academics.permissions import active_assignments
from apps.core.params import id_param
from apps.core.models import Role
from apps.pedagogy.access import (
    can_view_observations,
    can_view_occurrences,
    can_view_plans,
)
from apps.registry.access import guardian_of
from apps.registry.models import Enrollment, GuardianLink, Student

from . import bi, charts, reports, services
from .access import (
    can_view_class_dashboard,
    can_view_data_quality,
    can_view_teacher_dashboard,
    subject_classes_for,
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
def _student_timeline(student, report, *, can_occ, can_plan, can_just):
    """Trajetória do estudante, só com o que quem consulta pode ver."""
    events = []
    for e in report["enrollments"]:
        if e.started_on:
            events.append({"date": e.started_on, "kind": "Matrícula",
                           "text": f"Entrada na turma {e.class_group.name} ({e.school_year.name})"})
        if e.ended_on:
            events.append({"date": e.ended_on, "kind": "Matrícula",
                           "text": f"Saída da turma {e.class_group.name}: {e.get_status_display().lower()}"})
    for ev in report["academic"]["evaluations"][:15]:
        events.append({"date": ev["evaluation"].date, "kind": "Avaliação",
                       "text": f"{ev['evaluation'].subject.name} · {ev['evaluation'].title}: "
                               f"{str(ev['value']).replace('.', ',')}"})
    if can_just:
        for j in student.justifications.all()[:15]:
            events.append({"date": j.start_date, "kind": "Justificativa",
                           "text": f"Falta justificada: {j.get_status_display().lower()}"})
    if can_occ:
        for o in student.occurrences.all()[:15]:
            events.append({"date": o.date, "kind": "Ocorrência", "text": o.description[:100]})
    if can_plan:
        for pl in student.plans.all()[:15]:
            events.append({"date": pl.created_at.date(), "kind": "Plano de acompanhamento", "text": pl.title})
    period = report["period"]
    events = [e for e in events if period.start <= e["date"] <= period.end]
    return sorted(events, key=lambda e: e["date"], reverse=True)[:40]


def _switchable_students(user, student):
    """Outros estudantes que esta pessoa pode abrir (para trocar de painel)."""
    from apps.registry.access import students_visible_to

    qs = students_visible_to(user)
    if qs is None:
        return []
    if user.role != Role.RESPONSAVEL.value:
        current = Enrollment.objects.filter(student=student, status="ativo").values("class_group_id")
        qs = qs.filter(enrollments__class_group_id__in=current, enrollments__status="ativo").distinct()
    return list(qs.order_by("first_name", "last_name")[:200])


def _teacher_only_subjects(user, student=None, class_group=None):
    """Disciplinas que o professor pode ver neste painel, ou None (sem limite).

    O professor vê só as disciplinas que leciona (ou tem permissão de
    consultar) nas turmas do estudante / na turma: notas de colegas de outras
    disciplinas ficam fora, por padrão.
    """
    if user.role != Role.PROFESSOR.value:
        return None
    from apps.academics.permissions import teacher_subject_ids

    if class_group is not None:
        class_ids = {class_group.pk}
    else:
        class_ids = set(Enrollment.objects.filter(student=student).values_list("class_group_id", flat=True))
    return teacher_subject_ids(user, class_ids=class_ids)


def student_dashboard(request, student_id):
    from apps.pedagogy.access import can_view_justifications
    from apps.registry.access import ADMIN_RECORD_ROLES, can_view_birth_date

    student = get_object_or_404(Student.objects.select_related("school"), pk=student_id)
    user = request.user
    if not can_view_student_dashboard(user, student):
        raise PermissionDenied("Você não tem acesso ao painel deste estudante.")

    period = bi.resolve_period(request.GET, student.school)
    is_team = user.role in ADMIN_RECORD_ROLES or user.role == Role.PROFESSOR.value
    # Ocorrências, observações e planos têm regra própria e não seguem o
    # acesso ao painel: o estudante vê o próprio progresso, não o registro
    # disciplinar nem as anotações feitas sobre ele.
    can_view_occ = can_view_occurrences(user, student)
    can_view_plan = can_view_plans(user, student)
    can_view_obs = can_view_observations(user, student)
    can_just = can_view_justifications(user, student)

    only_subjects = _teacher_only_subjects(user, student=student)
    report = bi.student_report(
        student, period, show_class_comparison=is_team, show_observations=can_view_obs,
        only_subjects=only_subjects,
    )
    if not can_view_plan:
        report["interventions"] = []
    acad = report["academic"]
    subject_filter = id_param(request, "disciplina")
    evaluations = [
        e for e in acad["evaluations"]
        if not subject_filter or e["evaluation"].subject_id == subject_filter
    ]
    base_qs = period.querystring()
    skills, strategies = services.consolidated_skills(student, only_subjects) if can_view_obs else ([], [])

    context = {
        "student": student,
        "report": report,
        "period": period,
        "presets": bi.PRESETS,
        "is_team": is_team,
        "subject_limited": only_subjects is not None,
        "can_view_occ": can_view_occ,
        "can_view_plan": can_view_plan,
        "can_view_obs": can_view_obs,
        "can_view_birth": can_view_birth_date(user),
        "is_guardian": guardian_of(user, student),
        "occurrences": services.occurrence_stats(student) if can_view_occ else None,
        "difficulties": services.difficulty_contents(student) if can_view_obs else [],
        "skills": skills,
        "strategies": strategies,
        # Compatibilidade: lista de médias por disciplina do período.
        "subject_averages": acad["subjects"],
        "evaluations": evaluations,
        "subject_filter": subject_filter,
        "switch_students": _switchable_students(user, student),
        "timeline": _student_timeline(student, report, can_occ=can_view_occ,
                                      can_plan=can_view_plan, can_just=can_just),
        "sections": [
            ("visao-geral", "Visão geral"), ("desempenho", "Desempenho"),
            ("frequencia", "Frequência"), ("atividades", "Atividades"),
            ("trajetoria", "Trajetória"), ("inteligencia", "Inteligência pedagógica"),
        ] + ([("qualidade", "Qualidade dos dados")] if is_team else []),
        "export_links": [
            {"label": "CSV", "url": reverse("analytics:student_export", args=[student.pk, "csv"]) + "?" + base_qs},
            {"label": "Excel", "url": reverse("analytics:student_export", args=[student.pk, "xlsx"]) + "?" + base_qs},
        ],
        "subject_chart": charts.bar_chart(
            [
                {"label": s["subject"].name, "value": s["average"], "below": s["below"],
                 "url": f"?{base_qs}&disciplina={s['subject'].pk}#avaliacoes"}
                for s in acad["subjects"]
            ],
        ),
        "evolution_chart": charts.line_chart(
            [{"label": m["label"], "value": m["value"]} for m in acad["monthly"]],
            y_min=0, y_max=10,
        ),
        "distribution_chart": charts.bar_chart(acad["distribution"], suffix=" nota(s)"),
        "attendance_chart": charts.line_chart(
            [{"label": m["label"], "value": m["percent"]} for m in report["attendance"]["by_month"]],
            y_min=0, y_max=100, suffix="%",
        ),
        "weekday_chart": charts.bar_chart(
            [{"label": w["label"], "value": w["value"]} for w in report["attendance"]["by_weekday"]],
            max_value=100, suffix="% de faltas",
        ),
        "delivery_chart": charts.line_chart(
            [{"label": m["label"], "value": m["value"]} for m in report["activities"]["monthly"]],
            y_min=0, y_max=100, suffix="%",
        ),
        "generated_at": timezone.now(),
    }
    return render(request, "analytics/student_dashboard.html", context)


# --------------------------------------------------------------------------- #
# Painel por turma
# --------------------------------------------------------------------------- #
def _visible_classes(user):
    from apps.academics.models import TeacherAssignment
    from apps.registry.access import ADMIN_RECORD_ROLES

    qs = ClassGroup.objects.filter(school=user.school).select_related("school_year")
    if user.role == Role.PROFESSOR.value:
        from apps.academics.permissions import teacher_class_ids

        qs = qs.filter(pk__in=teacher_class_ids(user))
    elif user.role not in ADMIN_RECORD_ROLES:
        return ClassGroup.objects.none()
    return qs.order_by("name")


def _int_param(request, name, default, lo, hi):
    try:
        return max(lo, min(hi, int(request.GET.get(name, default))))
    except (TypeError, ValueError):
        return default


def class_dashboard(request, class_group_id):
    class_group = get_object_or_404(
        ClassGroup.objects.select_related("school", "school_year"), pk=class_group_id
    )
    if not can_view_class_dashboard(request.user, class_group):
        raise PermissionDenied("Você não tem acesso ao painel desta turma.")
    period = bi.resolve_period(request.GET, class_group.school)
    n_below = _int_param(request, "disciplinas", 1, 1, 10)
    min_delivery = _int_param(request, "entrega", 60, 0, 100)
    only_subjects = _teacher_only_subjects(request.user, class_group=class_group)
    report = bi.class_report(class_group, period, min_subjects_below=n_below, min_delivery=min_delivery,
                             only_subjects=only_subjects)
    only_follow = request.GET.get("acompanhamento") == "1"
    rows = report["follow_up"] if only_follow else report["rows"]
    qs = period.querystring() + f"&disciplinas={n_below}&entrega={min_delivery}"
    classes = _visible_classes(request.user)
    return render(request, "analytics/class_dashboard.html", {
        "class_group": class_group,
        "report": report,
        "subject_limited": only_subjects is not None,
        "rows": rows,
        "only_follow": only_follow,
        "period": period,
        "presets": bi.PRESETS,
        "qs": qs,
        "extra_filters": [
            {"name": "disciplinas", "label": "Acompanhamento: disciplinas abaixo", "selected": n_below,
             "options": [(i, f"{i} ou mais") for i in range(1, 5)]},
            {"name": "entrega", "label": "Acompanhamento: entrega abaixo de", "selected": min_delivery,
             "options": [(v, f"{v}%") for v in (40, 50, 60, 70, 80)]},
        ],
        "class_options": [
            (reverse("analytics:class_dashboard", args=[c.pk]) + "?" + qs, f"{c.name} · {c.school_year.name}", c.pk)
            for c in classes
        ],
        "export_links": [
            {"label": "CSV", "url": reverse("analytics:class_export", args=[class_group.pk, "csv"]) + "?" + qs},
            {"label": "Excel", "url": reverse("analytics:class_export", args=[class_group.pk, "xlsx"]) + "?" + qs},
        ],
        "subject_chart": charts.bar_chart([
            {"label": s["subject"].name, "value": s["mean"], "below": s["mean"] is not None and s["mean"] < s["passing"]}
            for s in report["subject_summary"]
        ]),
        "distribution_chart": charts.bar_chart(report["distribution"], suffix=" estudante(s)"),
        "grade_chart": charts.line_chart(
            [{"label": m["label"], "value": m["grade"]} for m in report["monthly"]], y_min=0, y_max=10),
        "attendance_chart": charts.line_chart(
            [{"label": m["label"], "value": m["attendance"]} for m in report["monthly"]],
            y_min=0, y_max=100, suffix="%"),
        "sections": [("visao-geral", "Visão geral"), ("disciplinas", "Disciplinas"), ("evolucao", "Evolução"),
                     ("avaliacoes", "Avaliações"), ("mapa", "Mapa de acompanhamento")],
        "generated_at": timezone.now(),
    })


def class_export(request, class_group_id, fmt):
    class_group = get_object_or_404(ClassGroup.objects.select_related("school", "school_year"), pk=class_group_id)
    if not can_view_class_dashboard(request.user, class_group):
        raise PermissionDenied
    period = bi.resolve_period(request.GET, class_group.school)
    r = bi.class_report(class_group, period,
                        min_subjects_below=_int_param(request, "disciplinas", 1, 1, 10),
                        min_delivery=_int_param(request, "entrega", 60, 0, 100),
                        only_subjects=_teacher_only_subjects(request.user, class_group=class_group))
    mapa = [["Estudante"] + [s.name for s in r["subjects"]]
            + ["Média geral", "Frequência (%)", "Taxa de entrega (%)", "Sem registro", "Evolução", "Acompanhamento"]]
    for row in r["rows"]:
        mapa.append([row["student"].full_name] + [c["value"] for c in row["cells"]]
                    + [row["overall"], row["attendance"]["percent"], row["delivery_rate"], row["no_record"],
                       row["evolution"], "; ".join(row["reasons"])])
    disciplinas = [["Disciplina", "Média da turma", "Mediana", "Mínimo", "Máximo", "Desvio", "Estudantes", "Abaixo da aprovação"]]
    for s in r["subject_summary"]:
        disciplinas.append([s["subject"].name, s["mean"], s["median"], s["min"], s["max"], s["stdev"], s["n"], s["below_count"]])
    avaliacoes = [["Data", "Disciplina", "Avaliação", "Tipo", "Notas", "Pendentes", "Média", "Mediana", "Mínimo", "Máximo", "Desvio"]]
    for e in r["evaluations"]:
        ev = e["evaluation"]
        avaliacoes.append([ev.date, ev.subject.name, ev.title, ev.get_kind_display(), e["n"], e["missing"],
                           e["mean"], e["median"], e["min"], e["max"], e["stdev"]])
    return _bi_export(request, title="Painel da turma", context=f"{class_group.name} ({class_group.school_year})",
                      period=period, fmt=fmt, target=class_group,
                      sheets=[("Mapa de acompanhamento", mapa), ("Disciplinas", disciplinas), ("Avaliações", avaliacoes)])


# --------------------------------------------------------------------------- #
# Painel institucional
# --------------------------------------------------------------------------- #
def institutional_dashboard(request):
    if not can_view_institutional_dashboard(request.user):
        raise PermissionDenied("Painel restrito à coordenação e direção.")
    school = request.user.school
    period = bi.resolve_period(request.GET, school)
    r = bi.institutional_report(school, period)
    min_attendance = round(100 - r["limit"], 1)
    return render(request, "analytics/institutional_dashboard.html", {
        "report": r,
        "period": period,
        "presets": bi.PRESETS,
        # Chaves mantidas por compatibilidade com telas e testes anteriores.
        "total_students": r["students_active"],
        "active_enrollments": r["enrollments_active"],
        "class_groups_count": len(r["classes"]),
        "attendance_rate": r["attendance"],
        "min_attendance": min_attendance,
        "class_chart": charts.bar_chart(
            [
                {"label": c["class_group"].name, "value": c["attendance"],
                 "below": c["attendance"] is not None and c["attendance"] < min_attendance,
                 "url": reverse("analytics:class_dashboard", args=[c["class_group"].pk]) + "?" + period.querystring()}
                for c in r["classes"] if not c["small"]
            ],
            max_value=100, suffix="%",
        ),
        "subject_chart": charts.bar_chart(
            [{"label": s["subject"].name, "value": s["mean"],
              "url": reverse("analytics:subject_dashboard", args=[s["subject"].pk]) + "?" + period.querystring()}
             for s in r["subjects"]],
        ),
        "trend_chart": charts.line_chart(
            [{"label": m["label"], "value": m["attendance"]} for m in r["monthly"]], y_min=0, y_max=100, suffix="%"),
        "grade_trend_chart": charts.line_chart(
            [{"label": m["label"], "value": m["grade"]} for m in r["monthly"]], y_min=0, y_max=10),
        "sections": [("visao-geral", "Visão geral"), ("turmas", "Turmas"), ("disciplinas", "Disciplinas"),
                     ("composicao", "Série e turno"), ("evolucao", "Evolução"), ("gestao", "Gestão")],
        "generated_at": timezone.now(),
    })


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
    if report.slug == "frequencia":
        # Aceita estudante OU turma. Antes a regra geral de "precisa de
        # estudante" vinha primeiro e o relatório por turma nunca era gerado.
        if not params["student"] and not params["class_group"]:
            missing.append("um estudante ou uma turma")
    elif report.needs_student and params["student"] is None:
        missing.append("um estudante")
    if report.needs_class and report.slug == "turma_indicadores" and not params["class_group"]:
        missing.append("uma turma")

    result = None
    error = None
    if not missing:
        try:
            result = report.run(request.user, params)
        except PermissionDenied as exc:
            error = str(exc)
    else:
        error = "Escolha " + " e ".join(missing) + " para gerar o relatório."

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
    # Mesma regra da tela: frequência aceita estudante OU turma.
    if report.slug == "frequencia":
        if not params["student"] and not params["class_group"]:
            raise PermissionDenied("Escolha um estudante ou uma turma.")
    elif report.needs_student and params["student"] is None:
        raise PermissionDenied("Escolha um estudante.")
    if report.needs_class and params["class_group"] is None and not params["student"]:
        raise PermissionDenied("Escolha uma turma.")

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


# --------------------------------------------------------------------------- #
# Exportação dos painéis de BI (CSV e Excel)
# --------------------------------------------------------------------------- #
def _bi_export(request, *, title, context, period, sheets, fmt, target=None):
    """Exporta as tabelas de um painel, com cabeçalho de contexto e auditoria.

    Cada arquivo diz o que é, de quem/qual turma, o período, quando foi gerado
    e onde está a metodologia — um número solto numa planilha perde o sentido.
    """
    from apps.core.models import create_audit_log

    from . import xlsx

    if fmt not in ("csv", "xlsx"):
        raise PermissionDenied
    gerado = timezone.localtime().strftime("%d/%m/%Y %H:%M")
    cabecalho = [
        [title], [context],
        [f"Período: {period.start:%d/%m/%Y} a {period.end:%d/%m/%Y} ({period.label})"],
        [f"Gerado em {gerado} por {request.user.get_full_name() or request.user.username}"],
        ["Ausência de dado aparece em branco (não é zero). Metodologia: Painéis > Metodologia dos indicadores."],
    ]
    nome = slugify(f"{title} {context}")[:80] or "painel"
    create_audit_log(
        user=request.user, action="export", request=request, target=target,
        detail=f"Exportou {title} — {context} ({period.start:%d/%m/%Y}–{period.end:%d/%m/%Y}) em {fmt.upper()}",
    )
    if fmt == "xlsx":
        data = xlsx.build([("Sobre", cabecalho)] + sheets)
        resp = HttpResponse(
            data, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        resp["Content-Disposition"] = f'attachment; filename="{nome}.xlsx"'
        return resp
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{nome}.csv"'
    resp.write("﻿")
    writer = csv.writer(resp, delimiter=";")
    for row in cabecalho:
        writer.writerow(row)
    for nome_aba, rows in sheets:
        writer.writerow([])
        writer.writerow([f"== {nome_aba} =="])
        for row in rows:
            writer.writerow([_csv_safe(_csv_value(v)) for v in row])
    return resp


def _csv_value(v):
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v}".replace(".", ",")
    if hasattr(v, "strftime"):
        return v.strftime("%d/%m/%Y")
    return v


def student_export(request, student_id, fmt):
    student = get_object_or_404(Student.objects.select_related("school"), pk=student_id)
    user = request.user
    if not can_view_student_dashboard(user, student):
        raise PermissionDenied
    from apps.registry.access import ADMIN_RECORD_ROLES

    is_team = user.role in ADMIN_RECORD_ROLES or user.role == Role.PROFESSOR.value
    period = bi.resolve_period(request.GET, student.school)
    r = bi.student_report(student, period, show_class_comparison=is_team,
                          only_subjects=_teacher_only_subjects(user, student=student))
    a, att, act = r["academic"], r["attendance"], r["activities"]
    resumo = [
        ["Indicador", "Valor", "Período anterior"],
        ["Média geral", a["overall"], a["prev_overall"]],
        ["Frequência (%)", att["percent"], att["prev_percent"]],
        ["Faltas", att["absent"], None],
        ["Faltas justificadas", att["justified"], None],
        ["Taxa de entrega (%)", act["delivery_rate"], act["prev_rate"]],
        ["Atividades propostas", act["proposed"], None],
        ["Entregues no prazo", act["on_time"], None],
        ["Entregues com atraso", act["late"], None],
        ["Não entregues", act["not_delivered"], None],
        ["Sem registro (prazo vencido)", act["no_record"], None],
        ["Tendência das notas", a["trend"]["label"], None],
    ]
    disciplinas = [["Disciplina", "Média", "Aprovação", "Variação", "Notas", "Regra", "Abaixo da aprovação"]
                   + (["Média da turma"] if a["class_comparison"] else [])]
    for s in a["subjects"]:
        disciplinas.append([s["subject"].name, s["average"], s["passing"], s["delta"], s["count"],
                            s["formula_label"], s["below"]] + ([s["class_mean"]] if a["class_comparison"] else []))
    avaliacoes = [["Data", "Disciplina", "Avaliação", "Tipo", "Peso", "Nota"]]
    for e in a["evaluations"]:
        ev = e["evaluation"]
        avaliacoes.append([ev.date, ev.subject.name, ev.title, ev.get_kind_display(), float(ev.weight), e["value"]])
    faltas = [["Data", "Justificada"]] + [[x["date"], x["justified"]] for x in att["absences"]]
    atividades = [["Entrega", "Disciplina", "Atividade", "Situação"]]
    nomes = {"no_prazo": "Entregue no prazo", "atrasada": "Entregue com atraso", "nao_entregue": "Não entregue",
             "sem_registro": "Sem registro", "em_aberto": "Em aberto"}
    for row in act["rows"]:
        atividades.append([row["activity"].deadline, row["activity"].subject.name, row["activity"].title,
                           nomes[row["state"]]])
    return _bi_export(
        request, title="Painel individual", context=student.full_name, period=period, fmt=fmt,
        target=student,
        sheets=[("Resumo", resumo), ("Disciplinas", disciplinas), ("Avaliações", avaliacoes),
                ("Faltas", faltas), ("Atividades", atividades)],
    )


def methodology(request):
    from .metrics import GROUPS, INSIGHT_RULES, METRICS

    grupos = [(g, [m for m in METRICS.values() if m.group == g]) for g in GROUPS]
    return render(request, "analytics/methodology.html", {"groups": grupos, "rules": INSIGHT_RULES})


# --------------------------------------------------------------------------- #
# Painel por disciplina
# --------------------------------------------------------------------------- #
def _subject_options(user):
    from apps.academics.models import Subject, TeacherAssignment
    from apps.registry.access import ADMIN_RECORD_ROLES

    qs = Subject.objects.filter(school=user.school).order_by("name")
    if user.role == Role.PROFESSOR.value:
        from apps.academics.permissions import teacher_subject_ids

        return qs.filter(pk__in=teacher_subject_ids(user))
    return qs if user.role in ADMIN_RECORD_ROLES else Subject.objects.none()


def _subject_scope(request, subject_id):
    from apps.academics.models import Subject

    if subject_id is None:
        first = _subject_options(request.user).first()
        if first is None:
            raise PermissionDenied("Nenhuma disciplina disponível para análise.")
        subject_id = first.pk
    subject = get_object_or_404(Subject.objects.select_related("school"), pk=subject_id)
    classes = subject_classes_for(request.user, subject)
    if classes is None:
        raise PermissionDenied("Você não tem acesso a esta disciplina.")
    turma = id_param(request, "turma")
    chosen = classes.filter(pk=turma) if turma else classes
    if turma and not chosen.exists():
        raise PermissionDenied("Turma fora do seu acesso nesta disciplina.")
    return subject, classes, list(chosen), turma


def subject_dashboard(request, subject_id=None):
    subject, classes, chosen, turma = _subject_scope(request, subject_id)
    period = bi.resolve_period(request.GET, subject.school)
    r = bi.subject_report(subject, chosen, period)
    qs = period.querystring() + (f"&turma={turma}" if turma else "")
    return render(request, "analytics/subject_dashboard.html", {
        "subject": subject, "report": r, "period": period, "presets": bi.PRESETS, "qs": qs,
        "subject_options": [
            (reverse("analytics:subject_dashboard", args=[sj.pk]) + "?" + period.querystring(), sj.name, sj.pk)
            for sj in _subject_options(request.user)
        ],
        "extra_filters": [{"name": "turma", "label": "Turma", "empty_label": "Todas as turmas",
                           "selected": turma or "", "options": [(c.pk, c.name) for c in classes]}],
        "export_links": [
            {"label": "CSV", "url": reverse("analytics:subject_export", args=[subject.pk, "csv"]) + "?" + qs},
            {"label": "Excel", "url": reverse("analytics:subject_export", args=[subject.pk, "xlsx"]) + "?" + qs},
        ],
        "class_chart": charts.bar_chart([
            {"label": c["class_group"].name, "value": c["mean"] if not c["small"] else None,
             "url": reverse("analytics:class_dashboard", args=[c["class_group"].pk]) + "?" + period.querystring()}
            for c in r["classes"]
        ]),
        "distribution_chart": charts.bar_chart(r["distribution"], suffix=" estudante(s)"),
        "monthly_chart": charts.line_chart([{"label": m["label"], "value": m["value"]} for m in r["monthly"]],
                                           y_min=0, y_max=10),
        "sections": [("visao-geral", "Visão geral"), ("turmas", "Turmas"), ("avaliacoes", "Avaliações"),
                     ("retomada", "Retomada"), ("acompanhamento", "Acompanhamento")],
    })


def subject_export(request, subject_id, fmt):
    subject, classes, chosen, turma = _subject_scope(request, subject_id)
    period = bi.resolve_period(request.GET, subject.school)
    r = bi.subject_report(subject, chosen, period)
    turmas = [["Turma", "Estudantes", "Com média", "Média", "Mediana", "Mín.", "Máx.", "Desvio",
               "Abaixo da aprovação", "Taxa de entrega (%)"]]
    for c in r["classes"]:
        oculto = c["small"]
        turmas.append([c["class_group"].name, c["students"], c["n"],
                       None if oculto else c["mean"], None if oculto else c["median"],
                       None if oculto else c["min"], None if oculto else c["max"],
                       None if oculto else c["stdev"], c["below_count"], c["delivery_rate"]])
    avaliacoes = [["Data", "Turma", "Avaliação", "Tipo", "Notas", "Média", "Mediana", "Mín.", "Máx.", "Desvio"]]
    for e in r["evaluations"]:
        ev = e["evaluation"]
        avaliacoes.append([ev.date, ev.class_group.name, ev.title, ev.get_kind_display(), e["n"],
                           e["mean"], e["median"], e["min"], e["max"], e["stdev"]])
    acomp = [["Estudante", "Turma", "Média", "Aprovação", "Notas"]] + [
        [x["student"].full_name, x["class_group"].name, x["average"], x["passing"], x["count"]]
        for x in r["follow_up"]
    ]
    return _bi_export(request, title="Painel da disciplina", context=subject.name, period=period, fmt=fmt,
                      target=subject, sheets=[("Turmas", turmas), ("Avaliações", avaliacoes),
                                              ("Para acompanhamento", acomp)])


# --------------------------------------------------------------------------- #
# Painel do professor
# --------------------------------------------------------------------------- #
def teacher_dashboard(request):
    from apps.academics.models import TeacherAssignment

    user = request.user
    if not can_view_teacher_dashboard(user):
        raise PermissionDenied("Painel do professor: somente o próprio professor.")
    period = bi.resolve_period(request.GET, user.school)
    todas = list(
        active_assignments(user)
        .select_related("class_group", "subject", "school_year")
        .order_by("class_group__name", "subject__name")
    )
    turma, disciplina = id_param(request, "turma"), id_param(request, "disciplina")
    escolhidas = [a for a in todas if (not turma or a.class_group_id == turma)
                  and (not disciplina or a.subject_id == disciplina)]
    r = bi.teacher_report(user, period, escolhidas)
    turmas = sorted({(a.class_group_id, a.class_group.name) for a in todas}, key=lambda t: t[1])
    disciplinas = sorted({(a.subject_id, a.subject.name) for a in todas}, key=lambda t: t[1])
    return render(request, "analytics/teacher_dashboard.html", {
        "report": r, "period": period, "presets": bi.PRESETS,
        "extra_filters": [
            {"name": "turma", "label": "Turma", "empty_label": "Todas", "selected": turma or "", "options": turmas},
            {"name": "disciplina", "label": "Disciplina", "empty_label": "Todas", "selected": disciplina or "",
             "options": disciplinas},
        ],
        "totals": {
            "students": sum(x["students"] for x in r["rows"]),
            "records_pending": sum(x["records_pending"] for x in r["rows"]),
            "drafts": sum(x["evaluations_draft"] for x in r["rows"]),
            "evaluations": sum(x["evaluations_published"] for x in r["rows"]),
            "observations": sum(x["observations"] for x in r["rows"]),
        },
        "average_chart": charts.bar_chart([
            {"label": f"{x['class_group'].name} · {x['subject'].name}", "tick": x["class_group"].name,
             "sub": x["subject"].name, "value": x["average"],
             "url": reverse("analytics:subject_dashboard", args=[x["subject"].pk])
             + f"?turma={x['class_group'].pk}&{period.querystring()}"}
            for x in r["rows"]
        ]),
    })


# --------------------------------------------------------------------------- #
# Qualidade dos dados
# --------------------------------------------------------------------------- #
def data_quality_dashboard(request):
    if not can_view_data_quality(request.user):
        raise PermissionDenied("Painel restrito à gestão da escola.")
    period = bi.resolve_period(request.GET, request.user.school)
    return render(request, "analytics/data_quality.html", {
        "q": bi.data_quality(request.user.school, period), "period": period, "presets": bi.PRESETS,
    })
