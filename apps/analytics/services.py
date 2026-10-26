"""Cálculo determinístico dos indicadores dos painéis e relatórios.

Cada função documenta sua regra de cálculo. Nada é inferido: quando não há
dados suficientes, devolve-se ``None`` ou uma lista vazia em vez de inventar
valores. Métricas de nota usam apenas avaliações **publicadas** (o registro
oficial); rascunhos nunca entram em indicadores agregados.
"""

from collections import defaultdict
from decimal import Decimal

from django.utils import timezone

from apps.pedagogy.models import (
    AbsenceJustification,
    AcademicRule,
    Activity,
    AttendanceRecord,
    Evaluation,
    Grade,
    InterventionPlan,
    Occurrence,
    PedagogicalObservation,
    SchoolConfig,
    Submission,
)
from apps.registry.models import Enrollment

PUBLISHED = Evaluation.Status.PUBLISHED


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
def _active_enrollments(student):
    return Enrollment.objects.filter(student=student, status="ativo").select_related(
        "class_group", "school_year"
    )


def active_class_group(student):
    enroll = _active_enrollments(student).first()
    return enroll.class_group if enroll else None


def school_max_absences(school):
    config = SchoolConfig.objects.filter(school=school).first()
    return config.max_absences_percent if config else Decimal("25.0")


def rules_by_subject(school):
    return {r.subject_id: r for r in AcademicRule.objects.filter(school=school)}


def _apply_formula(values_weights, formula):
    """values_weights: lista de (valor Decimal, peso Decimal)."""
    if not values_weights:
        return None
    values = [v for v, _ in values_weights if v is not None]
    if not values:
        return None
    if formula == AcademicRule.Formula.WEIGHTED:
        total_w = sum((w or Decimal("1")) for _, w in values_weights)
        if total_w == 0:
            return None
        acc = sum(v * (w or Decimal("1")) for v, w in values_weights)
        return acc / total_w
    if formula == AcademicRule.Formula.BEST:
        return max(values)
    if formula == AcademicRule.Formula.SUM:
        return sum(values)
    return sum(values) / Decimal(len(values))  # ARITHMETIC (padrão)


def _round(value):
    return round(value, 2) if value is not None else None


# --------------------------------------------------------------------------- #
# Desempenho acadêmico
# --------------------------------------------------------------------------- #
def published_grades(student, subject=None, start=None, end=None):
    qs = (
        Grade.objects.filter(student=student, evaluation__status=PUBLISHED)
        .select_related("evaluation", "evaluation__subject")
        .order_by("evaluation__date", "evaluation_id")
    )
    if subject is not None:
        qs = qs.filter(evaluation__subject=subject)
    if start is not None:
        qs = qs.filter(evaluation__date__gte=start)
    if end is not None:
        qs = qs.filter(evaluation__date__lte=end)
    return qs


def subject_averages(student, start=None, end=None):
    """Média por disciplina segundo a fórmula configurada (ou aritmética)."""
    rules = rules_by_subject(student.school)
    grouped = defaultdict(list)
    for grade in published_grades(student, start=start, end=end):
        if grade.value is None:
            continue
        grouped[grade.evaluation.subject].append(
            (grade.value, grade.evaluation.weight or Decimal("1"))
        )
    result = []
    for subject, vw in grouped.items():
        rule = rules.get(subject.pk)
        formula = rule.formula if rule else AcademicRule.Formula.ARITHMETIC
        passing = rule.passing_grade if rule else Decimal("6.0")
        average = _apply_formula(vw, formula)
        result.append(
            {
                "subject": subject,
                "average": _round(average),
                "passing": float(passing),
                "count": len(vw),
                "below": average is not None and average < passing,
                "formula_label": (
                    rule.get_formula_display()
                    if rule
                    else AcademicRule.Formula.ARITHMETIC.label
                ),
            }
        )
    return sorted(result, key=lambda r: r["subject"].name)


def grade_evolution(student, subject=None):
    """Série cronológica das notas publicadas (para gráfico de linhas)."""
    return [
        {
            "date": g.evaluation.date,
            "title": g.evaluation.title,
            "subject": g.evaluation.subject.name,
            "value": float(g.value) if g.value is not None else None,
        }
        for g in published_grades(student, subject=subject)
        if g.value is not None
    ]


def grade_distribution(student):
    """Quantas notas publicadas caíram em cada faixa (distribuição)."""
    buckets = [
        ("0–2", 0, 2),
        ("2–4", 2, 4),
        ("4–6", 4, 6),
        ("6–8", 6, 8),
        ("8–10", 8, 10.0001),
    ]
    values = [
        float(g.value)
        for g in published_grades(student)
        if g.value is not None
    ]
    dist = []
    for label, lo, hi in buckets:
        dist.append({"label": label, "count": sum(1 for v in values if lo <= v < hi)})
    return dist


def activity_stats(student):
    """Percentual de entregas, pendentes e atrasadas.

    Considera as atividades das turmas com matrícula ativa do estudante.
    Entrega = ``Submission`` com situação "entregue". Atrasada = prazo vencido
    sem entrega registrada; pendente = prazo ainda por vencer sem entrega.
    """
    class_ids = list(_active_enrollments(student).values_list("class_group_id", flat=True))
    activities = Activity.objects.filter(class_group_id__in=class_ids)
    total = activities.count()
    submissions = {
        s.activity_id: s
        for s in Submission.objects.filter(student=student, activity__in=activities)
    }
    delivered = sum(
        1 for s in submissions.values() if s.status == Submission.Status.DELIVERED
    )
    today = timezone.localdate()
    pending = 0
    late = 0
    for activity in activities:
        sub = submissions.get(activity.pk)
        ok = sub is not None and sub.status == Submission.Status.DELIVERED
        if ok:
            continue
        if activity.deadline and activity.deadline < today:
            late += 1
        else:
            pending += 1
    percent = round(delivered / total * 100, 1) if total else None
    return {
        "total": total,
        "delivered": delivered,
        "pending": pending,
        "late": late,
        "percent": percent,
    }


def difficulty_contents(student):
    """Conteúdos com dificuldades registradas (observações pedagógicas)."""
    rows = []
    for obs in student.observations.exclude(dificuldades="").order_by("-observed_at")[:50]:
        rows.append(
            {
                "content": obs.content,
                "subject": obs.subject.name if obs.subject else "—",
                "date": obs.observed_at,
                "detail": obs.dificuldades,
            }
        )
    return rows


def consolidated_skills(student):
    """Habilidades consolidadas e reforços recomendados (observações)."""
    skills, strategies = [], []
    for obs in student.observations.order_by("-observed_at")[:50]:
        if obs.habilidades:
            skills.append(
                {"content": obs.content, "date": obs.observed_at, "detail": obs.habilidades}
            )
        if obs.estrategias:
            strategies.append(
                {
                    "content": obs.content,
                    "date": obs.observed_at,
                    "detail": obs.estrategias,
                }
            )
    return skills, strategies


# --------------------------------------------------------------------------- #
# Frequência
# --------------------------------------------------------------------------- #
def attendance_stats(student, start=None, end=None):
    qs = AttendanceRecord.objects.filter(student=student)
    if start is not None:
        qs = qs.filter(date__gte=start)
    if end is not None:
        qs = qs.filter(date__lte=end)
    total = qs.count()
    present = qs.filter(status=AttendanceRecord.Status.PRESENT).count()
    late = qs.filter(status=AttendanceRecord.Status.LATE).count()
    absent = qs.filter(status=AttendanceRecord.Status.ABSENT).count()
    presence = present + late
    percent = round(presence / total * 100, 1) if total else None
    absence_percent = round(absent / total * 100, 1) if total else None
    limit = float(school_max_absences(student.school))
    return {
        "total": total,
        "present": present,
        "late": late,
        "absent": absent,
        "percent": percent,
        "absence_percent": absence_percent,
        "limit": limit,
        "near_limit": absence_percent is not None and absence_percent >= limit,
    }


def attendance_evolution(student, start=None, end=None):
    """Percentual de presença por mês (para gráfico de linhas)."""
    qs = AttendanceRecord.objects.filter(student=student)
    if start is not None:
        qs = qs.filter(date__gte=start)
    if end is not None:
        qs = qs.filter(date__lte=end)
    buckets = defaultdict(lambda: {"present": 0, "total": 0})
    for record in qs.only("date", "status"):
        key = record.date.strftime("%Y-%m")
        buckets[key]["total"] += 1
        if record.status in (
            AttendanceRecord.Status.PRESENT,
            AttendanceRecord.Status.LATE,
        ):
            buckets[key]["present"] += 1
    return [
        {
            "month": key,
            "percent": round(data["present"] / data["total"] * 100, 1)
            if data["total"]
            else 0,
        }
        for key, data in sorted(buckets.items())
    ]


def justification_stats(student):
    """Justificativas por situação (NÃO alteram a frequência oficial)."""
    qs = student.justifications.all()
    return {
        "total": qs.count(),
        "recebida": qs.filter(status=AbsenceJustification.Status.RECEIVED).count(),
        "em_analise": qs.filter(status=AbsenceJustification.Status.UNDER_REVIEW).count(),
        "aprovada": qs.filter(status=AbsenceJustification.Status.APPROVED).count(),
        "recusada": qs.filter(status=AbsenceJustification.Status.REFUSED).count(),
    }


# --------------------------------------------------------------------------- #
# Acompanhamento comportamental / pedagógico
# --------------------------------------------------------------------------- #
def occurrence_stats(student):
    qs = student.occurrences.all()
    return {
        "total": qs.count(),
        "aberta": qs.filter(status=Occurrence.Status.OPEN).count(),
        "em_acompanhamento": qs.filter(status=Occurrence.Status.FOLLOW_UP).count(),
        "encaminhada": qs.filter(status=Occurrence.Status.REFERRED).count(),
        "concluida": qs.filter(status=Occurrence.Status.CLOSED).count(),
    }


def plan_stats(student):
    qs = student.plans.all()
    active = qs.filter(status=InterventionPlan.Status.ACTIVE)
    return {
        "total": qs.count(),
        "ativos": active.count(),
        "concluidos": qs.filter(status=InterventionPlan.Status.DONE).count(),
        "cancelados": qs.filter(status=InterventionPlan.Status.CANCELED).count(),
        "registros": sum(p.notes.count() for p in qs),
        "plans": list(qs.prefetch_related("notes").order_by("-created_at")[:20]),
    }


def timeline(student, limit=25):
    """Linha do tempo de acontecimentos relevantes do estudante."""
    events = []
    for g in published_grades(student):
        if g.value is not None:
            events.append(
                {
                    "date": g.evaluation.date,
                    "kind": "Nota",
                    "text": f"{g.evaluation.subject.name} · {g.evaluation.title}: {g.value}",
                }
            )
    for e in _active_enrollments(student):
        events.append(
            {
                "date": e.registered_at.date(),
                "kind": "Matrícula",
                "text": f"{e.class_group} ({e.school_year})",
            }
        )
    for o in student.occurrences.all()[:30]:
        events.append(
            {
                "date": o.date,
                "kind": "Ocorrência",
                "text": o.description[:120],
            }
        )
    for j in student.justifications.all()[:30]:
        events.append(
            {
                "date": j.start_date,
                "kind": "Justificativa",
                "text": f"{j.get_status_display()}: {j.reason[:80]}",
            }
        )
    for p in student.plans.all()[:30]:
        events.append(
            {"date": p.created_at.date(), "kind": "Plano", "text": p.title}
        )
    events.sort(key=lambda ev: ev["date"], reverse=True)
    return events[:limit]


# --------------------------------------------------------------------------- #
# Agregados por turma / instituição
# --------------------------------------------------------------------------- #
def class_students(class_group):
    from apps.registry.models import Student

    return (
        Student.objects.filter(
            school=class_group.school,
            enrollments__class_group=class_group,
            enrollments__status="ativo",
        )
        .distinct()
        .order_by("first_name", "last_name")
    )


def class_subject_averages(class_group):
    """Média da turma por disciplina (notas publicadas)."""
    rules = rules_by_subject(class_group.school)
    grouped = defaultdict(list)
    grades = Grade.objects.filter(
        evaluation__class_group=class_group,
        evaluation__status=PUBLISHED,
        value__isnull=False,
    ).select_related("evaluation__subject")
    for grade in grades:
        grouped[grade.evaluation.subject].append(
            (grade.value, grade.evaluation.weight or Decimal("1"))
        )
    result = []
    for subject, vw in grouped.items():
        rule = rules.get(subject.pk)
        formula = rule.formula if rule else AcademicRule.Formula.ARITHMETIC
        passing = rule.passing_grade if rule else Decimal("6.0")
        average = _apply_formula(vw, formula)
        result.append(
            {
                "subject": subject,
                "average": _round(average),
                "passing": float(passing),
                "count": len(vw),
                "below": average is not None and average < passing,
            }
        )
    return sorted(result, key=lambda r: r["subject"].name)


def class_attendance_percent(class_group):
    qs = AttendanceRecord.objects.filter(class_group=class_group)
    total = qs.count()
    if not total:
        return None
    presence = qs.filter(
        status__in=[AttendanceRecord.Status.PRESENT, AttendanceRecord.Status.LATE]
    ).count()
    return round(presence / total * 100, 1)


def students_needing_attention(class_group):
    """Estudantes com sinal objetivo de atenção (média baixa, falta alta ou
    ocorrência aberta). É um alerta para avaliação profissional, não um
    diagnóstico."""
    rules = rules_by_subject(class_group.school)
    default_passing = Decimal("6.0")
    today = timezone.localdate()
    limit = school_max_absences(class_group.school)
    flagged = []
    for student in class_students(class_group):
        reasons = []
        averages = subject_averages(student)
        lows = [
            a for a in averages if a["average"] is not None and a["average"] < a["passing"]
        ]
        if lows:
            reasons.append(f"{len(lows)} disciplina(s) abaixo da média")
        att = attendance_stats(student)
        if att["near_limit"]:
            reasons.append(f"faltas em {att['absence_percent']}% (limite {att['limit']}%)")
        if student.occurrences.filter(
            status__in=[Occurrence.Status.OPEN, Occurrence.Status.FOLLOW_UP]
        ).exists():
            reasons.append("ocorrência em aberto")
        if reasons:
            flagged.append({"student": student, "reasons": reasons})
    return flagged


def institutional_indicators(school):
    from apps.registry.models import GuardianLink, Student

    from apps.academics.models import ClassGroup, TeacherAssignment

    students = Student.objects.filter(school=school, status="ativo")
    attendance = AttendanceRecord.objects.filter(school=school)
    total_att = attendance.count()
    presence = attendance.filter(
        status__in=[AttendanceRecord.Status.PRESENT, AttendanceRecord.Status.LATE]
    ).count()
    return {
        "students": students.count(),
        "class_groups": ClassGroup.objects.filter(school=school).count(),
        "teachers": TeacherAssignment.objects.filter(school=school)
        .values("teacher")
        .distinct()
        .count(),
        "attendance_percent": round(presence / total_att * 100, 1) if total_att else None,
        "occurrences_open": Occurrence.objects.filter(
            school=school,
            status__in=[Occurrence.Status.OPEN, Occurrence.Status.FOLLOW_UP],
        ).count(),
        "plans_active": InterventionPlan.objects.filter(
            school=school, status=InterventionPlan.Status.ACTIVE
        ).count(),
        "links_pending": GuardianLink.objects.filter(
            school=school, status="pendente"
        ).count(),
    }
