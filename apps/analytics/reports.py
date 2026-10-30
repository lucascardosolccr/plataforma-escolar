"""Registro de relatórios (seção 16 do Prompt 1).

Cada relatório declara os perfis autorizados e uma função ``run`` que devolve
colunas, linhas e um texto de critérios (período analisado, filtros e regra de
cálculo). O mesmo ``run`` alimenta a tela, a exportação CSV e a impressão, de
modo que a permissão é aplicada de forma idêntica em todos os formatos.

Escopo: professor enxerga apenas turmas que leciona; responsável apenas os
estudantes vinculados; perfis administrativos enxergam a escola.
"""

from collections import defaultdict
from dataclasses import dataclass, field

from django.core.exceptions import PermissionDenied
from django.db.models import Q

from apps.academics.models import Subject, TeacherAssignment
from apps.communication.models import ServiceRequest
from apps.core.models import Role
from apps.pedagogy.models import (
    AbsenceJustification,
    AttendanceRecord,
    Occurrence,
    PedagogicalObservation,
)
from apps.registry.models import Enrollment, GuardianLink, Student

from . import services

ADMIN = Role.ADMIN.value
DIRECAO = Role.DIRECAO.value
COORD = Role.COORDENACAO.value
SECRETARIA = Role.SECRETARIA.value
PROF = Role.PROFESSOR.value
RESP = Role.RESPONSAVEL.value

ALL = (ADMIN, DIRECAO, COORD, SECRETARIA, PROF, RESP)
STAFF = (ADMIN, DIRECAO, COORD, SECRETARIA)


@dataclass
class ReportResult:
    title: str
    criteria: str
    period: str
    columns: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    note: str = ""


@dataclass
class Report:
    slug: str
    title: str
    description: str
    roles: tuple
    run: object  # callable(user, params) -> ReportResult
    needs_student: bool = False
    needs_class: bool = False
    category: str = "Geral"


# --------------------------------------------------------------------------- #
# Escopo (quais estudantes/turmas o usuário pode ver)
# --------------------------------------------------------------------------- #
def allowed_students(user):
    base = Student.objects.filter(school=user.school)
    if user.role in STAFF:
        from apps.coordination.scope import student_ids

        ids = student_ids(user)  # coordenação restrita à designação
        return base if ids is None else base.filter(pk__in=ids)
    if user.role == PROF:
        from apps.academics.permissions import teacher_class_ids

        class_ids = teacher_class_ids(user)
        return base.filter(
            enrollments__class_group_id__in=list(class_ids),
            enrollments__status="ativo",
        ).distinct()
    if user.role == RESP:
        return base.filter(
            guardian_links__guardian=user, guardian_links__status="aprovado"
        ).distinct()
    return base.none()


def allowed_classes(user):
    from apps.academics.models import ClassGroup

    base = ClassGroup.objects.filter(school=user.school)
    if user.role in STAFF:
        from apps.coordination.scope import class_scope

        scope = class_scope(user)
        return base if scope is None else base.filter(pk__in=scope)
    if user.role == PROF:
        from apps.academics.permissions import teacher_class_ids

        class_ids = teacher_class_ids(user)
        return base.filter(pk__in=list(class_ids))
    return base.none()


def _student_names(students):
    return {s.pk: str(s) for s in students}


def _period_label(start, end):
    if start and end:
        return f"{start:%d/%m/%Y} a {end:%d/%m/%Y}"
    if start:
        return f"a partir de {start:%d/%m/%Y}"
    if end:
        return f"até {end:%d/%m/%Y}"
    return "todo o histórico disponível"


def _monthly_attendance(records):
    buckets = defaultdict(lambda: [0, 0, 0])
    for r in records:
        key = r.date.strftime("%m/%Y")
        if r.status == AttendanceRecord.Status.PRESENT:
            buckets[key][0] += 1
        elif r.status == AttendanceRecord.Status.LATE:
            buckets[key][1] += 1
        else:
            buckets[key][2] += 1
    return buckets


def _attendance_rows(records, extra_label=None):
    buckets = _monthly_attendance(records)
    rows = []
    for key, (present, late, absent) in sorted(
        buckets.items(), key=lambda kv: (kv[0][3:], kv[0][:2])
    ):
        total = present + late + absent
        pct = round((present + late) / total * 100, 1) if total else 0
        label = extra_label or "Mês"
        rows.append([key, present, late, absent, f"{pct}%"])
    return rows


# --------------------------------------------------------------------------- #
# Relatórios
# --------------------------------------------------------------------------- #
def _prof_subjects(user):
    """Disciplinas que o professor alcança (None para os demais perfis)."""
    if user.role != PROF:
        return None
    from apps.academics.permissions import teacher_subject_ids

    return teacher_subject_ids(user)


def _r_boletim(user, params):
    student = params["student"]
    averages = services.subject_averages(student, params["start"], params["end"])
    allowed = _prof_subjects(user)
    if allowed is not None:  # professor: só as disciplinas que leciona
        averages = [a for a in averages if a["subject"].pk in allowed]
    rows = [
        [
            a["subject"].name,
            a["count"],
            a["average"] if a["average"] is not None else "—",
            "Abaixo da média" if a["below"] else "Na média",
        ]
        for a in averages
    ]
    formulas = sorted({a["formula_label"] for a in averages})
    criteria = (
        f"Estudante: {student}. Considera apenas avaliações publicadas. "
        f"Fórmula de cálculo: {', '.join(formulas) if formulas else 'média aritmética'}."
    )
    return ReportResult(
        title=f"Boletim — {student}",
        columns=["Disciplina", "Avaliações", "Média", "Situação"],
        rows=rows,
        criteria=criteria,
        period=_period_label(params["start"], params["end"]),
    )


def _r_evolucao(user, params):
    student = params["student"]
    evolution = services.grade_evolution(
        student, params["subject"], params["start"], params["end"]
    )
    allowed = _prof_subjects(user)
    if allowed is not None:
        from apps.academics.models import Subject

        names = set(Subject.objects.filter(pk__in=allowed).values_list("name", flat=True))
        evolution = [e for e in evolution if str(e["subject"]) in names]
    rows = [
        [e["date"].strftime("%d/%m/%Y"), e["subject"], e["title"], e["value"]]
        for e in evolution
    ]
    criteria = (
        f"Estudante: {student}. Série cronológica das notas publicadas"
        + (f", disciplina {params['subject']}." if params["subject"] else ".")
    )
    return ReportResult(
        title=f"Evolução acadêmica — {student}",
        columns=["Data", "Disciplina", "Avaliação", "Nota"],
        rows=rows,
        criteria=criteria,
        period=_period_label(params["start"], params["end"]),
    )


def _r_frequencia(user, params):
    start, end = params["start"], params["end"]
    student, class_group = params["student"], params["class_group"]
    if student:
        qs = AttendanceRecord.objects.filter(student=student)
        if start:
            qs = qs.filter(date__gte=start)
        if end:
            qs = qs.filter(date__lte=end)
        rows = _attendance_rows(qs)
        summary = services.attendance_stats(student, start, end)
        criteria = (
            f"Estudante: {student}. Presença = presentes + atrasos. "
            f"Limite de faltas: {summary['limit']}%."
        )
        title = f"Frequência — {student}"
    elif class_group:
        records = AttendanceRecord.objects.filter(class_group=class_group)
        if start:
            records = records.filter(date__gte=start)
        if end:
            records = records.filter(date__lte=end)
        students = services.class_students(class_group)
        # Uma consulta para a turma inteira (antes, uma por estudante).
        counts = {}
        for sid, status in records.values_list("student_id", "status"):
            counts.setdefault(sid, {"presente": 0, "atraso": 0, "falta": 0})[status] += 1
        rows = []
        for s in students:
            c = counts.get(s.pk, {"presente": 0, "atraso": 0, "falta": 0})
            total = c["presente"] + c["atraso"] + c["falta"]
            # Sem registro no período: "—", nunca 0% (seria afirmar ausência total).
            pct = f"{round((c['presente'] + c['atraso']) / total * 100, 1)}%" if total else "—"
            rows.append([str(s), c["presente"], c["atraso"], c["falta"], pct])
        criteria = f"Turma: {class_group}. Presença = presentes + atrasos."
        title = f"Frequência — {class_group}"
    else:
        raise PermissionDenied("Informe o estudante ou a turma.")
    return ReportResult(
        title=title,
        columns=["Referência", "Presenças", "Atrasos", "Faltas", "% Presença"],
        rows=rows,
        criteria=criteria,
        period=_period_label(start, end),
    )


def _r_dificuldades(user, params):
    students = allowed_students(user)
    qs = (
        PedagogicalObservation.objects.filter(
            school=user.school, student__in=students
        )
        .exclude(dificuldades="")
        .select_related("student", "subject")
        .order_by("-observed_at")
    )
    if params["class_group"]:
        qs = qs.filter(student__enrollments__class_group=params["class_group"])
    if params["subject"]:
        qs = qs.filter(subject=params["subject"])
    allowed = _prof_subjects(user)
    if allowed is not None:
        qs = qs.filter(Q(teacher=user) | Q(subject__isnull=True) | Q(subject_id__in=allowed))
    if params["start"]:
        qs = qs.filter(observed_at__gte=params["start"])
    if params["end"]:
        qs = qs.filter(observed_at__lte=params["end"])
    rows = [
        [
            str(o.student),
            o.observed_at.strftime("%d/%m/%Y"),
            o.subject.name if o.subject else "—",
            o.content,
            o.dificuldades,
        ]
        for o in qs
    ]
    criteria = "Observações pedagógicas com dificuldades registradas."
    return ReportResult(
        title="Estudantes com dificuldades",
        columns=["Estudante", "Data", "Disciplina", "Conteúdo", "Dificuldade"],
        rows=rows,
        criteria=criteria,
        period=_period_label(params["start"], params["end"]),
    )


def _r_atividades_pendentes(user, params):
    from apps.pedagogy.models import Activity, Submission
    from django.utils import timezone

    class_group = params["class_group"]
    classes = allowed_classes(user)
    today = timezone.localdate()
    qs = Activity.objects.filter(
        school=user.school,
        class_group__in=classes,
        status=Activity.Status.PUBLISHED,
        published_date__lte=today,
    )
    if class_group:
        qs = qs.filter(class_group=class_group)
    if params["subject"]:
        qs = qs.filter(subject=params["subject"])
    if params["start"]:
        qs = qs.filter(published_date__gte=params["start"])
    if params["end"]:
        qs = qs.filter(published_date__lte=params["end"])

    activities = list(qs.select_related("class_group", "subject").order_by("deadline"))
    rows = []
    if activities:
        act_ids = [a.id for a in activities]
        delivered_pairs = set(
            Submission.objects.filter(
                activity_id__in=act_ids,
                status__in=Submission.DELIVERED_STATUSES,
            ).values_list("activity_id", "student_id")
        )
        students_by_class = {}
        for activity in activities:
            cg = activity.class_group
            if cg.id not in students_by_class:
                students_by_class[cg.id] = list(services.class_students(cg))
            for student in students_by_class[cg.id]:
                if (activity.id, student.id) in delivered_pairs:
                    continue
                if activity.deadline and activity.deadline < today:
                    situacao = "Atrasada"
                else:
                    situacao = "Pendente"
                rows.append(
                    [
                        str(student),
                        activity.title,
                        activity.subject.name,
                        activity.deadline.strftime("%d/%m/%Y") if activity.deadline else "—",
                        situacao,
                    ]
                )
    criteria = "Atividades publicadas sem entrega registrada nas turmas do escopo."
    return ReportResult(
        title="Atividades pendentes",
        columns=["Estudante", "Atividade", "Disciplina", "Prazo", "Situação"],
        rows=rows,
        criteria=criteria,
        period=_period_label(params["start"], params["end"]),
    )


def _r_acompanhamento(user, params):
    students = allowed_students(user)
    plans = services.InterventionPlan.objects.filter(
        school=user.school, student__in=students
    ).select_related("student")
    if params["class_group"]:
        plans = plans.filter(student__enrollments__class_group=params["class_group"])
    start, end = params["start"], params["end"]
    rows = []
    for plan in plans.order_by("-created_at"):
        notes = plan.notes.all()
        if start:
            notes = notes.filter(created_at__date__gte=start)
        if end:
            notes = notes.filter(created_at__date__lte=end)
        notes = list(notes.order_by("-created_at"))
        created = plan.created_at.date()
        if notes:
            for note in notes:
                rows.append(
                    [
                        str(plan.student),
                        plan.title,
                        note.note,
                        note.created_at.strftime("%d/%m/%Y"),
                        plan.get_status_display(),
                    ]
                )
        elif (not start or created >= start) and (not end or created <= end):
            rows.append(
                [
                    str(plan.student),
                    plan.title,
                    plan.description[:200],
                    plan.created_at.strftime("%d/%m/%Y"),
                    plan.get_status_display(),
                ]
            )
    criteria = "Planos de intervenção e seus registros de evolução."
    return ReportResult(
        title="Histórico de acompanhamento",
        columns=["Estudante", "Plano", "Registro/objetivo", "Data", "Situação"],
        rows=rows,
        criteria=criteria,
        period=_period_label(params["start"], params["end"]),
    )


def _r_justificativas(user, params):
    students = allowed_students(user)
    qs = AbsenceJustification.objects.filter(
        school=user.school, student__in=students
    ).select_related("student")
    if params["class_group"]:
        qs = qs.filter(class_group=params["class_group"])
    if params["start"]:
        qs = qs.filter(start_date__gte=params["start"])
    if params["end"]:
        qs = qs.filter(end_date__lte=params["end"])
    rows = [
        [
            str(j.student),
            f"{j.start_date:%d/%m/%Y}–{j.end_date:%d/%m/%Y}",
            j.reason,
            j.get_status_display(),
            j.note or "—",
        ]
        for j in qs.order_by("-created_at")
    ]
    criteria = "Justificativas de ausência e situação de análise da secretaria."
    return ReportResult(
        title="Solicitações e justificativas",
        columns=["Estudante", "Período", "Motivo", "Situação", "Parecer"],
        rows=rows,
        criteria=criteria,
        period=_period_label(params["start"], params["end"]),
    )


def _r_ocorrencias(user, params):
    students = allowed_students(user)
    qs = Occurrence.objects.filter(school=user.school, student__in=students).select_related(
        "student"
    )
    if params["class_group"]:
        qs = qs.filter(student__enrollments__class_group=params["class_group"])
    if params["start"]:
        qs = qs.filter(date__gte=params["start"])
    if params["end"]:
        qs = qs.filter(date__lte=params["end"])
    rows = [
        [
            o.date.strftime("%d/%m/%Y"),
            str(o.student),
            o.description,
            o.encaminhamento or "—",
            o.get_status_display(),
        ]
        for o in qs.order_by("-date")
    ]
    criteria = "Ocorrências registradas e respectivo encaminhamento."
    return ReportResult(
        title="Ocorrências",
        columns=["Data", "Estudante", "Descrição", "Encaminhamento", "Situação"],
        rows=rows,
        criteria=criteria,
        period=_period_label(params["start"], params["end"]),
    )


def _r_pendencias_documentais(user, params):
    links = (
        GuardianLink.objects.filter(school=user.school, status="pendente")
        .select_related("guardian", "student")
    )
    rows = [
        [
            "Vínculo responsável",
            f"{link.guardian} → {link.student}",
            "Pendente de validação",
            link.get_relation_display() or "—",
        ]
        for link in links
    ]
    without_enrollment = Student.objects.filter(school=user.school, status="ativo").exclude(
        enrollments__status="ativo"
    )
    for student in without_enrollment:
        rows.append(["Matrícula", str(student), "Sem matrícula ativa", "—"])
    criteria = "Vínculos pendentes de validação e estudantes sem matrícula ativa."
    return ReportResult(
        title="Pendências documentais",
        columns=["Tipo", "Referência", "Situação", "Detalhe"],
        rows=rows,
        criteria=criteria,
        period="Posição atual",
    )


def _r_solicitacoes(user, params):
    qs = ServiceRequest.objects.filter(school=user.school).select_related(
        "requester", "student"
    )
    if params["student"]:
        qs = qs.filter(student=params["student"])
    if params["start"]:
        qs = qs.filter(created_at__date__gte=params["start"])
    if params["end"]:
        qs = qs.filter(created_at__date__lte=params["end"])
    rows = [
        [
            r.created_at.strftime("%d/%m/%Y"),
            r.requester.get_full_name() or r.requester.username,
            r.get_category_display(),
            r.title,
            r.get_status_display(),
            (r.response[:120] if r.response else "—"),
        ]
        for r in qs.order_by("-created_at")
    ]
    criteria = "Solicitações registradas junto à secretaria e situação de atendimento."
    return ReportResult(
        title="Solicitações da secretaria",
        columns=["Data", "Solicitante", "Categoria", "Assunto", "Situação", "Resposta"],
        rows=rows,
        criteria=criteria,
        period=_period_label(params["start"], params["end"]),
    )


def _r_turma_indicadores(user, params):
    class_group = params["class_group"]
    if not class_group:
        raise PermissionDenied("Informe a turma.")
    averages = services.class_subject_averages(
        class_group, params["start"], params["end"]
    )
    rows = [
        [
            a["subject"].name,
            a["average"] if a["average"] is not None else "—",
            a["count"],
            "Abaixo da média" if a["below"] else "Na média",
        ]
        for a in averages
    ]
    att = services.class_attendance_percent(
        class_group, params["start"], params["end"]
    )
    rows.append(["Frequência da turma", f"{att}%" if att is not None else "—", "—", "—"])
    criteria = (
        f"Turma: {class_group}. Médias por disciplina (notas publicadas) e "
        "frequência global da turma."
    )
    return ReportResult(
        title=f"Indicadores por turma — {class_group}",
        columns=["Indicador", "Valor", "Avaliações", "Situação"],
        rows=rows,
        criteria=criteria,
        period=_period_label(params["start"], params["end"]),
    )


def _r_institucional(user, params):
    data = services.institutional_indicators(user.school)
    labels = {
        "students": "Estudantes ativos",
        "class_groups": "Turmas",
        "teachers": "Professores com atribuição",
        "attendance_percent": "Frequência global (%)",
        "occurrences_open": "Ocorrências em aberto",
        "plans_active": "Planos de intervenção ativos",
        "links_pending": "Vínculos pendentes",
    }
    rows = [[labels[k], v if v is not None else "—"] for k, v in data.items()]
    criteria = "Indicadores institucionais consolidados da escola."
    return ReportResult(
        title="Relatório institucional",
        columns=["Indicador", "Valor"],
        rows=rows,
        criteria=criteria,
        period="Posição atual",
    )


# --------------------------------------------------------------------------- #
# Registro
# --------------------------------------------------------------------------- #
REPORTS = {
    "boletim": Report(
        "boletim",
        "Boletim individual",
        "Média por disciplina do estudante e situação.",
        ALL,
        _r_boletim,
        needs_student=True,
        category="Acadêmico",
    ),
    "evolucao": Report(
        "evolucao",
        "Evolução acadêmica",
        "Série cronológica das notas publicadas.",
        ALL,
        _r_evolucao,
        needs_student=True,
        category="Acadêmico",
    ),
    "frequencia": Report(
        "frequencia",
        "Frequência por período",
        "Presenças, atrasos e faltas por estudante ou turma.",
        ALL,
        _r_frequencia,
        needs_student=True,
        needs_class=True,
        category="Frequência",
    ),
    "dificuldades": Report(
        "dificuldades",
        "Estudantes com dificuldades",
        "Dificuldades registradas em observações pedagógicas.",
        (DIRECAO, COORD, PROF),
        _r_dificuldades,
        category="Pedagógico",
    ),
    "atividades_pendentes": Report(
        "atividades_pendentes",
        "Atividades pendentes",
        "Entregas não registradas, pendentes e atrasadas.",
        (ADMIN, DIRECAO, COORD, PROF, SECRETARIA),
        _r_atividades_pendentes,
        needs_class=True,
        category="Pedagógico",
    ),
    "acompanhamento": Report(
        "acompanhamento",
        "Histórico de acompanhamento",
        "Planos de intervenção e registros de evolução.",
        (ADMIN, DIRECAO, COORD, PROF),
        _r_acompanhamento,
        category="Pedagógico",
    ),
    "justificativas": Report(
        "justificativas",
        "Solicitações e justificativas",
        "Justificativas de ausência e situação de análise.",
        (ADMIN, DIRECAO, COORD, SECRETARIA),
        _r_justificativas,
        category="Administrativo",
    ),
    "ocorrencias": Report(
        "ocorrencias",
        "Ocorrências",
        "Ocorrências e encaminhamentos por período.",
        (ADMIN, DIRECAO, COORD, PROF),
        _r_ocorrencias,
        category="Pedagógico",
    ),
    "pendencias_documentais": Report(
        "pendencias_documentais",
        "Pendências documentais",
        "Vínculos pendentes e estudantes sem matrícula ativa.",
        (ADMIN, DIRECAO, COORD, SECRETARIA),
        _r_pendencias_documentais,
        category="Administrativo",
    ),
    "solicitacoes": Report(
        "solicitacoes",
        "Solicitações da secretaria",
        "Solicitações das famílias e atendimento.",
        (ADMIN, DIRECAO, COORD, SECRETARIA),
        _r_solicitacoes,
        category="Administrativo",
    ),
    "turma_indicadores": Report(
        "turma_indicadores",
        "Indicadores por turma",
        "Médias por disciplina e frequência da turma.",
        (ADMIN, DIRECAO, COORD, SECRETARIA, PROF),
        _r_turma_indicadores,
        needs_class=True,
        category="Institucional",
    ),
    "institucional": Report(
        "institucional",
        "Relatório institucional",
        "Indicadores consolidados da escola.",
        (ADMIN, DIRECAO, COORD),
        _r_institucional,
        category="Institucional",
    ),
}


def reports_for(user):
    return [r for r in REPORTS.values() if user.role in r.roles]


def get_report(user, slug):
    report = REPORTS.get(slug)
    if report is None or user.role not in report.roles:
        raise PermissionDenied("Relatório indisponível para o seu perfil.")
    return report


def subjects_for(user):
    return Subject.objects.filter(school=user.school).order_by("name")
