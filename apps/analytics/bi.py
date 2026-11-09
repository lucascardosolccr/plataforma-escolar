"""Motor dos painéis de BI (Prompt 13).

Cada função recebe um período e devolve somente números calculados a partir
de registros reais, seguindo a definição em ``metrics.py``. Regras gerais:

- Ausência de dado é ``None`` (exibido como "—"), nunca zero.
- Notas: só de avaliações publicadas; média por disciplina pela regra da
  escola (``services._averages_from_grades``, a mesma do boletim).
- Média da turma por disciplina = média das médias individuais dos
  estudantes (não a regra aplicada a todas as notas da turma misturadas).
- Carga em lote: cada painel faz um número pequeno e fixo de consultas,
  independente da quantidade de estudantes (testes de orçamento em
  ``tests/test_bi.py``).
"""

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from django.db.models import Count, Max, Q
from django.utils import timezone

from apps.core.params import digits
from apps.pedagogy.models import (
    AbsenceJustification,
    Activity,
    AttendanceRecord,
    Evaluation,
    Grade,
    GroupWork,
    GroupWorkDelivery,
    InterventionPlan,
    Occurrence,
    PedagogicalObservation,
    Submission,
    WorkGroupMember,
)
from apps.registry.models import Enrollment

from .services import _averages_from_grades, rules_by_subject, school_max_absences

PUBLISHED = Evaluation.Status.PUBLISHED
PRESENCE = (AttendanceRecord.Status.PRESENT, AttendanceRecord.Status.LATE)
SMALL_GROUP = 5
WEEKDAYS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


# --------------------------------------------------------------------------- #
# Período
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Period:
    start: date
    end: date
    preset: str
    label: str
    prev: tuple = None  # (início, fim, rótulo) do período anterior do calendário, quando houver

    @property
    def days(self):
        return (self.end - self.start).days + 1

    def previous(self):
        if self.prev:
            return Period(self.prev[0], self.prev[1], "anterior", self.prev[2])
        end = self.start - timedelta(days=1)
        start = end - timedelta(days=self.days - 1)
        return Period(start, end, "anterior", f"{start:%d/%m/%Y} a {end:%d/%m/%Y}")

    def halves(self):
        mid = self.start + timedelta(days=self.days // 2)
        return (self.start, mid - timedelta(days=1)), (mid, self.end)

    def querystring(self):
        return f"periodo={self.preset}&inicio={self.start:%Y-%m-%d}&fim={self.end:%Y-%m-%d}"


PRESETS = [
    ("ano", "Ano letivo atual"),
    ("tudo", "Todo o histórico"),
    ("90d", "Últimos 90 dias"),
    ("30d", "Últimos 30 dias"),
    ("mes", "Mês atual"),
    ("personalizado", "Personalizado"),
]


def _calendar_periods(school):
    """Bimestres (ou trimestres, semestres) do ano letivo atual, cadastrados no calendário."""
    from apps.school_calendar.models import CalendarPeriod
    from apps.school_calendar.services import current_year

    year = current_year(school)
    if not year:
        return []
    return list(CalendarPeriod.objects.filter(school=school, school_year=year).order_by("start"))


def presets_for(school):
    """Opções do seletor de período: as fixas e, antes de "Personalizado", os períodos do calendário."""
    periods = [(f"p{p.pk}", f"{p.name} ({p.start:%d/%m} a {p.end:%d/%m})") for p in _calendar_periods(school)]
    return PRESETS[:-1] + periods + PRESETS[-1:]


def _school_year_dates(school, today):
    from apps.academics.models import SchoolYear

    years = SchoolYear.objects.filter(school=school)
    year = (
        years.filter(is_current=True).first()
        or years.filter(start_date__lte=today, end_date__gte=today).first()
    )
    if year and year.start_date and year.end_date:
        return year.start_date, year.end_date, f"Ano letivo {year.name}"
    return date(today.year, 1, 1), date(today.year, 12, 31), f"Ano de {today.year}"


def _parse(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def resolve_period(params, school):
    """Período escolhido nos filtros (GET). Padrão: ano letivo atual.

    Datas inválidas ou invertidas voltam ao padrão em vez de quebrar a tela.
    """
    today = timezone.localdate()
    preset = params.get("periodo") or "ano"
    if preset == "personalizado":
        start, end = _parse(params.get("inicio")), _parse(params.get("fim"))
        if start and end and start <= end:
            return Period(start, end, preset, f"{start:%d/%m/%Y} a {end:%d/%m/%Y}")
        preset = "ano"
    if preset == "30d":
        return Period(today - timedelta(days=29), today, preset, "Últimos 30 dias")
    if preset == "90d":
        return Period(today - timedelta(days=89), today, preset, "Últimos 90 dias")
    if preset == "tudo":
        from apps.academics.models import SchoolYear

        first = (
            SchoolYear.objects.filter(school=school, start_date__isnull=False)
            .order_by("start_date").values_list("start_date", flat=True).first()
        )
        start = min(first, today) if first else today.replace(year=today.year - 5)
        return Period(start, today, preset, "Todo o histórico")
    if preset.startswith("p") and digits(preset[1:]):
        periods = _calendar_periods(school)
        for i, p in enumerate(periods):
            if p.pk == int(preset[1:]):
                before = periods[i - 1] if i else None
                return Period(p.start, p.end, preset, p.name,
                              prev=(before.start, before.end, before.name) if before else None)
        preset = "ano"
    if preset == "mes":
        start = today.replace(day=1)
        return Period(start, today, preset, f"{MONTHS[today.month - 1]}/{today.year}")
    start, end, label = _school_year_dates(school, today)
    return Period(start, end, "ano", label)


# --------------------------------------------------------------------------- #
# Estatística descritiva
# --------------------------------------------------------------------------- #
def _r(value, places=1):
    return None if value is None else round(float(value), places)


def pct(part, whole):
    return round(part / whole * 100, 1) if whole else None


def describe(values):
    """Média, mediana, mínimo, máximo e desvio padrão (populacional)."""
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return {"n": 0, "mean": None, "median": None, "min": None, "max": None, "stdev": None}
    return {
        "n": len(vals),
        "mean": round(statistics.fmean(vals), 2),
        "median": round(statistics.median(vals), 2),
        "min": round(min(vals), 2),
        "max": round(max(vals), 2),
        "stdev": round(statistics.pstdev(vals), 2) if len(vals) >= 3 else None,
    }


def trend(points):
    """Inclinação (pontos por mês) da reta de mínimos quadrados.

    ``points``: lista de (data, valor). Exige 4 pontos em 2 meses ou mais.
    """
    pts = [(d, float(v)) for d, v in points if v is not None]
    months = {(d.year, d.month) for d, _ in pts}
    if len(pts) < 4 or len(months) < 2:
        return {"slope": None, "label": "Dados insuficientes", "direction": "insuficiente"}
    x0 = min(d for d, _ in pts)
    xs = [(d - x0).days / 30.44 for d, _ in pts]
    ys = [v for _, v in pts]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return {"slope": None, "label": "Dados insuficientes", "direction": "insuficiente"}
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
    if slope >= 0.3:
        direction, label = "alta", "Alta"
    elif slope <= -0.3:
        direction, label = "queda", "Queda"
    else:
        direction, label = "estavel", "Estável"
    return {"slope": round(slope, 2), "label": label, "direction": direction}


def bands(values):
    """Distribuição em faixas de 2 pontos (e "acima de 10")."""
    edges = [("0–2", 0, 2), ("2–4", 2, 4), ("4–6", 4, 6), ("6–8", 6, 8), ("8–10", 8, 10.0001)]
    vals = [float(v) for v in values if v is not None]
    out = [{"label": lab, "value": sum(1 for v in vals if lo <= v < hi)} for lab, lo, hi in edges]
    over = sum(1 for v in vals if v >= 10.0001)
    if over:
        out.append({"label": "> 10", "value": over})
    return out


def month_key(d):
    return f"{d.year}-{d.month:02d}"


def month_label(key):
    y, m = key.split("-")
    return f"{MONTHS[int(m) - 1]}/{y[2:]}"


def months_between(start, end):
    keys, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        keys.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return keys


# --------------------------------------------------------------------------- #
# Carga em lote
# --------------------------------------------------------------------------- #
def load_grades(student_ids, start, end, class_group=None, subject=None, subject_ids=None):
    """{estudante: [Grade]} de avaliações publicadas no período, com nota.

    ``subject_ids``: restringe às disciplinas dadas (o professor só vê as
    disciplinas que leciona)."""
    qs = (
        Grade.objects.filter(
            student_id__in=list(student_ids),
            evaluation__status=PUBLISHED,
            evaluation__date__gte=start,
            evaluation__date__lte=end,
            value__isnull=False,
        )
        .select_related("evaluation", "evaluation__subject")
        .order_by("evaluation__date", "evaluation_id")
    )
    if class_group is not None:
        qs = qs.filter(evaluation__class_group=class_group)
    if subject is not None:
        qs = qs.filter(evaluation__subject=subject)
    if subject_ids is not None:
        qs = qs.filter(evaluation__subject_id__in=list(subject_ids))
    out = defaultdict(list)
    for g in qs:
        out[g.student_id].append(g)
    return out


class _Ev:
    __slots__ = ("subject", "subject_id", "weight", "date", "class_group_id")

    def __init__(self, subject, weight, date, class_group_id=None):
        self.subject, self.subject_id, self.weight, self.date = subject, subject.pk, weight, date
        self.class_group_id = class_group_id


class _LightGrade:
    """Nota sem o objeto completo: só o que médias, evolução mensal e estatística por avaliação usam."""
    __slots__ = ("value", "evaluation", "evaluation_id")

    def __init__(self, value, evaluation, evaluation_id):
        self.value, self.evaluation, self.evaluation_id = value, evaluation, evaluation_id


def load_grades_light(student_ids, start, end, class_group=None, subject_ids=None, class_ids=None):
    """Como ``load_grades``, mas para agregados da escola inteira: na escala de uma escola real (20 mil
    notas) montar cada Grade com avaliação e disciplina levava mais de 1 s no painel institucional.
    Devolve objetos com ``value`` e ``evaluation.subject/weight/date`` — o que ``_averages_from_grades``
    e ``_monthly_grades`` leem."""
    from apps.academics.models import Subject

    qs = Grade.objects.filter(
        student_id__in=list(student_ids), evaluation__status=PUBLISHED, evaluation__date__gte=start,
        evaluation__date__lte=end, value__isnull=False,
    )
    if class_group is not None:
        qs = qs.filter(evaluation__class_group=class_group)
    if class_ids is not None:
        qs = qs.filter(evaluation__class_group_id__in=list(class_ids))
    if subject_ids is not None:
        qs = qs.filter(evaluation__subject_id__in=list(subject_ids))
    rows = list(qs.order_by("evaluation__date", "evaluation_id").values_list(
        "student_id", "value", "evaluation__subject_id", "evaluation__subject__name", "evaluation__weight",
        "evaluation__date", "evaluation_id", "evaluation__class_group_id"))
    # Disciplina montada da mesma consulta (só id e nome, o que as telas usam): uma consulta a mais aqui
    # mudava o número de consultas conforme houvesse notas, e o teste de orçamento vigia isso.
    subjects, out = {}, defaultdict(list)
    for sid, value, subj_id, subj_name, weight, d, ev_id, cg_id in rows:
        subj = subjects.get(subj_id) or subjects.setdefault(subj_id, Subject(pk=subj_id, name=subj_name))
        out[sid].append(_LightGrade(value, _Ev(subj, weight, d, cg_id), ev_id))
    return out


def load_attendance(student_ids, start, end, class_group=None):
    """{estudante: [(data, situação)]} ordenado por data."""
    qs = AttendanceRecord.objects.filter(
        student_id__in=list(student_ids), date__gte=start, date__lte=end
    ).order_by("date")
    if class_group is not None:
        qs = qs.filter(class_group=class_group)
    out = defaultdict(list)
    for sid, d, status in qs.values_list("student_id", "date", "status"):
        out[sid].append((d, status))
    return out


def attendance_summary(records, limit):
    """Totais, percentuais e alerta de limite a partir de [(data, situação)]."""
    total = len(records)
    present = sum(1 for _, s in records if s == AttendanceRecord.Status.PRESENT)
    late = sum(1 for _, s in records if s == AttendanceRecord.Status.LATE)
    absent = sum(1 for _, s in records if s == AttendanceRecord.Status.ABSENT)
    absence_pct = pct(absent, total)
    level = None
    if absence_pct is not None and limit:
        if absence_pct >= limit:
            level = "acima"
        elif absence_pct >= limit * 0.8:
            level = "perto"
    return {
        "total": total, "present": present, "late": late, "absent": absent,
        "percent": pct(present + late, total), "absence_percent": absence_pct,
        "limit": limit, "min_percent": round(100 - limit, 1) if limit is not None else None,
        "limit_level": level,
    }


# --------------------------------------------------------------------------- #
# Painel individual
# --------------------------------------------------------------------------- #
def _subject_rows(grades, rules):
    return {a["subject"].pk: a for a in _averages_from_grades(grades, rules)}


def _overall(rows):
    vals = [float(a["average"]) for a in rows.values() if a["average"] is not None]
    return round(statistics.fmean(vals), 2) if vals else None


def _class_subject_means(class_group, start, end, rules):
    """{disciplina: (média das médias individuais, n estudantes)} da turma."""
    ids = list(
        Enrollment.objects.filter(class_group=class_group, status="ativo").values_list(
            "student_id", flat=True
        )
    )
    per_student = load_grades(ids, start, end, class_group=class_group)
    acc = defaultdict(list)
    for sid in ids:
        for subj_id, row in _subject_rows(per_student.get(sid, []), rules).items():
            if row["average"] is not None:
                acc[subj_id].append(float(row["average"]))
    return {k: (round(statistics.fmean(v), 2), len(v)) for k, v in acc.items()}


def _activity_breakdown(student, enrollments, period, today, subject_ids=None):
    """Atividades que alcançam o estudante, classificadas pela situação."""
    from apps.pedagogy.access import reaches

    class_ids = {e.class_group_id for e in enrollments}
    acts = list(
        Activity.objects.filter(
            class_group_id__in=class_ids,
            status=Activity.Status.PUBLISHED,
            published_date__lte=today,
        )
        .filter(
            Q(deadline__gte=period.start, deadline__lte=period.end)
            | Q(deadline__isnull=True, published_date__gte=period.start, published_date__lte=period.end)
        )
        .select_related("subject")
        .order_by("deadline", "published_date")
    )
    acts = [a for a in acts if reaches(enrollments, a)
            and (subject_ids is None or a.subject_id in subject_ids)]
    subs = {
        s.activity_id: s
        for s in Submission.objects.filter(student=student, activity__in=acts)
    }
    S = Submission.Status
    counts = defaultdict(int)
    by_subject = defaultdict(lambda: defaultdict(int))
    by_month = defaultdict(lambda: defaultdict(int))
    rows, activity_grades, feedback = [], [], []
    for a in acts:
        sub = subs.get(a.pk)
        if sub is not None:
            state = {S.DELIVERED: "no_prazo", S.LATE: "atrasada", S.NOT_DELIVERED: "nao_entregue"}[sub.status]
            if sub.grade is not None:
                activity_grades.append(float(sub.grade))
            if sub.comment:
                feedback.append({"activity": a, "comment": sub.comment, "date": sub.updated_at})
        elif a.deadline and a.deadline < today:
            state = "sem_registro"
        else:
            state = "em_aberto"
        counts[state] += 1
        by_subject[a.subject.name][state] += 1
        by_month[month_key(a.deadline or a.published_date)][state] += 1
        rows.append({"activity": a, "state": state, "submission": sub})
    delivered = counts["no_prazo"] + counts["atrasada"]
    registered = delivered + counts["nao_entregue"]
    overdue = registered + counts["sem_registro"]
    subj_rows = []
    for name, c in sorted(by_subject.items()):
        d = c["no_prazo"] + c["atrasada"]
        r = d + c["nao_entregue"]
        subj_rows.append({"subject": name, "total": sum(c.values()), "delivered": d,
                          "registered": r, "rate": pct(d, r), "no_record": c["sem_registro"]})
    return {
        "proposed": len(acts),
        "on_time": counts["no_prazo"], "late": counts["atrasada"],
        "not_delivered": counts["nao_entregue"], "no_record": counts["sem_registro"],
        "open": counts["em_aberto"], "delivered": delivered, "registered": registered,
        "delivery_rate": pct(delivered, registered),
        "coverage": pct(registered, overdue),
        "on_time_rate": pct(counts["no_prazo"], delivered),
        "grade_mean": round(statistics.fmean(activity_grades), 2) if activity_grades else None,
        "by_subject": subj_rows,
        "by_month": dict(by_month),
        "rows": rows,
        "feedback": sorted(feedback, key=lambda f: f["date"], reverse=True)[:10],
    }


def _group_participation(student, period):
    members = list(
        WorkGroupMember.objects.filter(
            student=student,
            removed_at__isnull=True,
            group__group_work__status=GroupWork.Status.PUBLISHED,
            group__group_work__published_date__gte=period.start,
            group__group_work__published_date__lte=period.end,
        ).select_related("group", "group__group_work", "group__group_work__subject")
    )
    works = [m.group.group_work for m in members]
    deliveries = GroupWorkDelivery.objects.filter(group_work__in=works).filter(
        Q(student=student) | Q(student__isnull=True, group__in=[m.group for m in members])
    )
    status = defaultdict(int)
    for d in deliveries:
        status[d.status] += 1
    return {
        "count": len(works),
        "works": [{"work": m.group.group_work, "group": m.group} for m in members],
        "delivered": status["entregue"], "late": status["atrasado"],
        "not_delivered": status["nao_entregue"],
    }


def _weekday_absences(records):
    total = defaultdict(int)
    absent = defaultdict(int)
    for d, s in records:
        total[d.weekday()] += 1
        if s == AttendanceRecord.Status.ABSENT:
            absent[d.weekday()] += 1
    return [
        {"label": WEEKDAYS[i], "value": pct(absent[i], total[i]), "absent": absent[i], "total": total[i]}
        for i in range(7) if total[i]
    ]


def _longest_streak(records):
    best, cur, cur_start, best_range = 0, 0, None, None
    for d, s in records:
        if s == AttendanceRecord.Status.ABSENT:
            if cur == 0:
                cur_start = d
            cur += 1
            if cur > best:
                best, best_range = cur, (cur_start, d)
        else:
            cur = 0
    return {"length": best, "start": best_range[0] if best_range else None,
            "end": best_range[1] if best_range else None}


def _justified(student, records):
    ranges = list(
        AbsenceJustification.objects.filter(
            student=student, status=AbsenceJustification.Status.APPROVED
        ).values_list("start_date", "end_date")
    )
    absences = [d for d, s in records if s == AttendanceRecord.Status.ABSENT]
    covered = {d for d in absences for a, b in ranges if a <= d <= b}
    return covered


def _monthly_grades(grades):
    acc = defaultdict(list)
    for g in grades:
        acc[month_key(g.evaluation.date)].append(float(g.value))
    return {k: round(statistics.fmean(v), 2) for k, v in acc.items()}


def _heatmap(grades, months):
    """Disciplina × mês: média das notas da célula."""
    acc = defaultdict(lambda: defaultdict(list))
    for g in grades:
        acc[g.evaluation.subject.name][month_key(g.evaluation.date)].append(float(g.value))
    rows = []
    for subject in sorted(acc):
        cells = []
        for m in months:
            vals = acc[subject].get(m)
            cells.append({"month": m, "value": round(statistics.fmean(vals), 1) if vals else None,
                          "n": len(vals) if vals else 0})
        rows.append({"subject": subject, "cells": cells})
    return rows


def _interventions(student, today):
    """Notas e frequência 60 dias antes × 60 dias depois de cada plano."""
    out = []
    for plan in InterventionPlan.objects.filter(student=student).order_by("-created_at")[:10]:
        pivot = plan.created_at.date()
        before = (pivot - timedelta(days=60), pivot - timedelta(days=1))
        after = (pivot, min(pivot + timedelta(days=60), today))
        def grade_mean(a, b):
            vals = list(
                Grade.objects.filter(
                    student=student, evaluation__status=PUBLISHED, value__isnull=False,
                    evaluation__date__gte=a, evaluation__date__lte=b,
                ).values_list("value", flat=True)
            )
            return (round(statistics.fmean(float(v) for v in vals), 2) if len(vals) >= 2 else None, len(vals))
        def att(a, b):
            recs = list(AttendanceRecord.objects.filter(
                student=student, date__gte=a, date__lte=b).values_list("status", flat=True))
            return pct(sum(1 for s in recs if s in PRESENCE), len(recs))
        gb, nb = grade_mean(*before)
        ga, na = grade_mean(*after)
        out.append({
            "plan": plan, "grade_before": gb, "grade_after": ga, "n_before": nb, "n_after": na,
            "att_before": att(*before), "att_after": att(*after),
            "delta": round(ga - gb, 2) if ga is not None and gb is not None else None,
            "after_complete": pivot + timedelta(days=60) <= today,
        })
    return out


def _student_quality(student, enrollments, period, act):
    """Lacunas de registro que afetam a leitura do painel do estudante."""
    class_ids = {e.class_group_id for e in enrollments}
    evals = Evaluation.objects.filter(
        class_group_id__in=class_ids, status=PUBLISHED,
        date__gte=period.start, date__lte=period.end,
    ).exclude(grades__student=student, grades__value__isnull=False)
    from apps.pedagogy.access import enrollment_window_q

    evals = evals.filter(enrollment_window_q(enrollments, "date")).select_related("subject")
    class_days = set(
        AttendanceRecord.objects.filter(
            class_group_id__in=class_ids, date__gte=period.start, date__lte=period.end
        ).values_list("date", flat=True).distinct()
    )
    own_days = set(
        AttendanceRecord.objects.filter(
            student=student, date__gte=period.start, date__lte=period.end
        ).values_list("date", flat=True)
    )
    window_days = {
        d for d in class_days
        if any((e.started_on is None or d >= e.started_on) and (e.ended_on is None or d <= e.ended_on)
               for e in enrollments)
    }
    return {
        "evaluations_without_grade": list(evals[:20]),
        "attendance_days_missing": len(window_days - own_days),
        "activities_without_record": act["no_record"],
    }


def student_report(student, period, *, show_class_comparison=False, show_observations=False,
                   only_subjects=None, shared_only=False):
    today = timezone.localdate()
    school = student.school
    rules = rules_by_subject(school)
    limit = float(school_max_absences(school))
    enrollments = list(
        Enrollment.objects.filter(student=student).select_related("class_group", "school_year")
    )
    active = [e for e in enrollments if e.status == "ativo"]
    current = max(active, key=lambda e: (e.started_on or date.min)) if active else None

    prev = period.previous()
    grades = load_grades([student.pk], period.start, period.end, subject_ids=only_subjects).get(student.pk, [])
    prev_grades = load_grades([student.pk], prev.start, prev.end, subject_ids=only_subjects).get(student.pk, [])
    subj = _subject_rows(grades, rules)
    prev_subj = _subject_rows(prev_grades, rules)
    class_means = (
        _class_subject_means(current.class_group, period.start, period.end, rules)
        if (current and show_class_comparison) else {}
    )
    subjects = []
    for sid, row in sorted(subj.items(), key=lambda kv: kv[1]["subject"].name):
        p = prev_subj.get(sid)
        delta = (
            round(float(row["average"]) - float(p["average"]), 2)
            if p and p["average"] is not None and row["average"] is not None
            and p["count"] >= 2 and row["count"] >= 2 else None
        )
        cm = class_means.get(sid)
        subjects.append({
            **row, "average": _r(row["average"], 2), "delta": delta,
            "class_mean": cm[0] if cm and cm[1] >= SMALL_GROUP else None,
            "class_n": cm[1] if cm else 0,
            "margin": round(float(row["average"]) - row["passing"], 2) if row["average"] is not None else None,
        })
    overall, prev_overall = _overall(subj), _overall(prev_subj)
    ranked = [s for s in subjects if s["margin"] is not None]
    best = sorted(ranked, key=lambda s: -s["margin"])[:3]
    attention = [s for s in sorted(ranked, key=lambda s: s["margin"]) if s["below"] or (s["delta"] or 0) <= -1][:3]
    months = months_between(period.start, period.end)
    monthly = _monthly_grades(grades)
    # Mapa de calor só do primeiro ao último mês com nota: num período longo,
    # colunas vazias empurravam os dados para fora da tela.
    heat_months = months
    if monthly:
        heat_months = months_between(*(
            date(int(k[:4]), int(k[5:]), 1) for k in (min(monthly), max(monthly))
        ))
    evaluations = []
    eval_ids = [g.evaluation_id for g in grades]
    class_eval_means = {}
    if show_class_comparison and eval_ids:
        for row in (
            Grade.objects.filter(evaluation_id__in=eval_ids, value__isnull=False)
            .values("evaluation_id").annotate(n=Count("id"))
        ):
            class_eval_means[row["evaluation_id"]] = row["n"]
        sums = defaultdict(list)
        for eid, v in Grade.objects.filter(evaluation_id__in=eval_ids, value__isnull=False).values_list("evaluation_id", "value"):
            sums[eid].append(float(v))
        class_eval_means = {k: (round(statistics.fmean(v), 2), len(v)) for k, v in sums.items()}
    for g in reversed(grades):
        cm = class_eval_means.get(g.evaluation_id)
        evaluations.append({
            "grade": g, "evaluation": g.evaluation, "value": float(g.value),
            "class_mean": cm[0] if cm and cm[1] >= SMALL_GROUP else None,
        })
    recovery = []
    for g in grades:
        if g.evaluation.kind == Evaluation.Kind.RECOVERY:
            antes = [x for x in grades if x.evaluation.subject_id == g.evaluation.subject_id
                     and x.evaluation.date < g.evaluation.date and x.evaluation.kind != Evaluation.Kind.RECOVERY]
            before = _overall(_subject_rows(antes, rules)) if antes else None
            passing = subj.get(g.evaluation.subject_id, {}).get("passing", 6.0)
            recovery.append({"evaluation": g.evaluation, "value": float(g.value), "before": before,
                             "reached": float(g.value) >= passing, "passing": passing})

    records = load_attendance([student.pk], period.start, period.end).get(student.pk, [])
    prev_records = load_attendance([student.pk], prev.start, prev.end).get(student.pk, [])
    att = attendance_summary(records, limit)
    prev_att = attendance_summary(prev_records, limit)
    justified = _justified(student, records)
    att_month = defaultdict(list)
    for d, s in records:
        att_month[month_key(d)].append(s)
    attendance_by_month = [
        {"month": m, "label": month_label(m), "percent": pct(sum(1 for s in att_month[m] if s in PRESENCE), len(att_month[m])),
         "absent": sum(1 for s in att_month[m] if s == AttendanceRecord.Status.ABSENT), "total": len(att_month[m])}
        for m in months if att_month.get(m)
    ]
    absences_list = [
        {"date": d, "justified": d in justified}
        for d, s in reversed(records) if s == AttendanceRecord.Status.ABSENT
    ][:30]

    act = _activity_breakdown(student, enrollments, period, today, only_subjects)
    prev_act = _activity_breakdown(student, enrollments, prev, today, only_subjects)
    groups = _group_participation(student, period)
    trd = trend([(g.evaluation.date, g.value) for g in grades])

    report = {
        "period": period,
        "previous": prev,
        "current_enrollment": current,
        "enrollments": sorted(enrollments, key=lambda e: e.started_on or date.min, reverse=True),
        "academic": {
            "subjects": subjects, "overall": overall, "prev_overall": prev_overall,
            "overall_delta": round(overall - prev_overall, 2) if overall is not None and prev_overall is not None else None,
            "best": best, "attention": attention, "n_grades": len(grades),
            "n_evaluations": len({g.evaluation_id for g in grades}),
            "monthly": [{"label": month_label(m), "value": monthly.get(m), "month": m} for m in months],
            "distribution": bands([g.value for g in grades]),
            "heatmap": _heatmap(grades, heat_months), "months": [month_label(m) for m in heat_months],
            "evaluations": evaluations, "trend": trd, "recovery": recovery,
            "class_comparison": bool(class_means),
        },
        "attendance": {
            **att,
            "prev_percent": prev_att["percent"],
            "delta": round(att["percent"] - prev_att["percent"], 1)
            if att["percent"] is not None and prev_att["percent"] is not None else None,
            "justified": len(justified), "unjustified": att["absent"] - len(justified),
            "by_month": attendance_by_month,
            "by_weekday": _weekday_absences(records) if len(records) >= 10 else [],
            "streak": _longest_streak(records),
            "absences": absences_list,
        },
        "activities": {**act, "prev_rate": prev_act["delivery_rate"],
                       "delta": round(act["delivery_rate"] - prev_act["delivery_rate"], 1)
                       if act["delivery_rate"] is not None and prev_act["delivery_rate"] is not None else None,
                       "groups": groups,
                       "monthly": [
                           {"label": month_label(m), "month": m,
                            "value": pct(act["by_month"].get(m, {}).get("no_prazo", 0) + act["by_month"].get(m, {}).get("atrasada", 0),
                                         sum(act["by_month"].get(m, {}).get(k, 0) for k in ("no_prazo", "atrasada", "nao_entregue")))}
                           for m in months]},
        "quality": _student_quality(student, enrollments, period, act),
    }
    report["interventions"] = _interventions(student, today)
    report["insights"] = student_insights(student, report, show_observations=show_observations,
                                          only_subjects=only_subjects, shared_only=shared_only)
    return report


# --------------------------------------------------------------------------- #
# Inteligência pedagógica (regras transparentes; ver metrics.INSIGHT_RULES)
# --------------------------------------------------------------------------- #
def _fmt(v, places=1):
    return f"{v:.{places}f}".replace(".", ",")


def student_insights(student, report, *, show_observations=False, only_subjects=None, shared_only=False):
    out = []
    acad, att, act = report["academic"], report["attendance"], report["activities"]
    for s in acad["subjects"]:
        if s["below"] and s["average"] is not None:
            worst = sorted(
                (e for e in acad["evaluations"] if e["evaluation"].subject_id == s["subject"].pk),
                key=lambda e: e["value"],
            )[:2]
            itens = ", ".join(f"“{e['evaluation'].title}” ({_fmt(e['value'])})" for e in worst)
            out.append({
                "kind": "atencao", "title": f"{s['subject'].name}: média abaixo da aprovação",
                "observed": f"Média {_fmt(s['average'], 2)} com {s['count']} nota(s); aprovação {_fmt(s['passing'])}.",
                "rule": "Média da disciplina no período < média de aprovação.",
                "suggestion": f"Avaliar a retomada dos conteúdos das avaliações com menor resultado: {itens}." if itens
                else "Avaliar a retomada dos conteúdos recentes da disciplina.",
                "anchor": "desempenho",
            })
        if s["delta"] is not None and s["delta"] <= -1:
            out.append({
                "kind": "atencao", "title": f"{s['subject'].name}: queda em relação ao período anterior",
                "observed": f"Variação de {_fmt(s['delta'], 2)} ponto(s).",
                "rule": "Queda de 1,0 ponto ou mais, com ao menos 2 notas em cada período.",
                "suggestion": "Conversar com o estudante sobre a disciplina e acompanhar as próximas avaliações.",
                "anchor": "desempenho",
            })
        elif s["delta"] is not None and s["delta"] >= 1:
            out.append({
                "kind": "evolucao", "title": f"{s['subject'].name}: melhora em relação ao período anterior",
                "observed": f"Variação de +{_fmt(s['delta'], 2)} ponto(s).",
                "rule": "Alta de 1,0 ponto ou mais, com ao menos 2 notas em cada período.",
                "suggestion": "Reconhecer a evolução com o estudante e a família.",
                "anchor": "desempenho",
            })
    if acad["trend"]["direction"] == "alta":
        out.append({
            "kind": "evolucao", "title": "Tendência de alta nas notas",
            "observed": f"Inclinação de +{_fmt(acad['trend']['slope'], 2)} ponto(s) por mês.",
            "rule": "Inclinação ≥ +0,3/mês com ao menos 4 notas em 2 meses.",
            "suggestion": "Manter as estratégias que vêm funcionando.",
            "anchor": "trajetoria",
        })
    if att["limit_level"]:
        out.append({
            "kind": "atencao",
            "title": "Faltas acima do limite da escola" if att["limit_level"] == "acima" else "Faltas perto do limite da escola",
            "observed": f"{att['absent']} falta(s) em {att['total']} dia(s) com chamada ({_fmt(att['absence_percent'])}%); limite {_fmt(att['limit'])}%.",
            "rule": "Faltas ≥ 80% do limite de faltas configurado (ou acima dele).",
            "suggestion": "Contato com a família para entender as ausências e orientar sobre justificativas.",
            "anchor": "frequencia",
        })
    if att["streak"]["length"] >= 3:
        st = att["streak"]
        out.append({
            "kind": "atencao", "title": "Sequência de faltas",
            "observed": f"{st['length']} faltas seguidas entre {st['start']:%d/%m} e {st['end']:%d/%m}.",
            "rule": "3 ou mais faltas em dias de chamada consecutivos.",
            "suggestion": "Verificar com a família se houve algum motivo e se cabe justificativa.",
            "anchor": "frequencia",
        })
    if act["delivery_rate"] is not None and act["registered"] >= 3 and act["delivery_rate"] < 60:
        out.append({
            "kind": "atencao", "title": "Entrega de atividades baixa",
            "observed": f"{act['delivered']} de {act['registered']} atividades com registro ({_fmt(act['delivery_rate'])}%).",
            "rule": "Taxa de entrega < 60% com ao menos 3 entregas registradas.",
            "suggestion": "Conversar sobre a rotina de estudos em casa; avaliar atividades complementares.",
            "anchor": "atividades",
        })
    if act["no_record"] >= 3:
        out.append({
            "kind": "informacao", "title": "Atividades com prazo vencido sem registro de entrega",
            "observed": f"{act['no_record']} atividade(s) sem registro.",
            "rule": "3 ou mais atividades com prazo vencido sem registro (qualidade do dado).",
            "suggestion": "Para o professor: registrar as entregas deixa a taxa de entrega representativa.",
            "anchor": "atividades",
        })
    if show_observations:
        counts = defaultdict(int)
        obs = PedagogicalObservation.objects.filter(student=student).exclude(dificuldades="")
        if shared_only:
            obs = obs.filter(shared_with_family=True)
        if only_subjects is not None:
            obs = obs.filter(Q(subject__isnull=True) | Q(subject_id__in=list(only_subjects)))
        for subj_name in obs.values_list("subject__name", flat=True):
            counts[subj_name or "Geral"] += 1
        for name, n in counts.items():
            if n >= 2:
                out.append({
                    "kind": "atencao", "title": f"Dificuldade recorrente registrada em {name}",
                    "observed": f"{n} observações pedagógicas com dificuldade.",
                    "rule": "2 ou mais observações com dificuldade na mesma disciplina.",
                    "suggestion": "Avaliar a abertura ou revisão de um plano de acompanhamento.",
                    "anchor": "inteligencia",
                })
    order = {"atencao": 0, "informacao": 1, "evolucao": 2}
    return sorted(out, key=lambda i: order[i["kind"]])


# --------------------------------------------------------------------------- #
# Painel da turma
# --------------------------------------------------------------------------- #
def school_rules(school):
    """(regras por disciplina, limite de faltas em %): o que ``class_report`` lê da escola. Quem monta o
    relatório de muitas turmas calcula uma vez e passa em ``rules=``."""
    return rules_by_subject(school), float(school_max_absences(school))


def _period_activities(period, today):
    return Activity.objects.filter(status=Activity.Status.PUBLISHED, published_date__lte=today).filter(
        Q(deadline__gte=period.start, deadline__lte=period.end)
        | Q(deadline__isnull=True, published_date__gte=period.start, published_date__lte=period.end)
    )


def preload_classes(class_groups, period, only_subjects=None):
    """Dados de várias turmas em consultas fixas, para ``class_report(..., preload=...)``.

    O painel da coordenação montava o relatório de cada turma com ~7 consultas próprias (185 consultas e
    0,6 s com 24 turmas). Aqui são 7 no total; o cálculo por turma continua sendo o de ``class_report``."""
    from apps.registry.models import Student

    today = timezone.localdate()
    ids = [cg.pk for cg in class_groups]
    out = {pk: {"enrollments": [], "grades": defaultdict(list), "records": defaultdict(list), "acts": [],
                "subs": defaultdict(dict), "evals": []} for pk in ids}
    enrollments = list(Enrollment.objects.filter(class_group_id__in=ids).select_related("student"))
    for e in enrollments:
        out[e.class_group_id]["enrollments"].append(e)
    active = {e.student_id for e in enrollments if e.status == "ativo"}
    ordered = list(Student.objects.filter(pk__in=active).order_by("first_name", "last_name"))
    for data in out.values():
        data["students"] = ordered
    for sid, grades in load_grades_light(active, period.start, period.end, subject_ids=only_subjects,
                                         class_ids=ids).items():
        for g in grades:
            out[g.evaluation.class_group_id]["grades"][sid].append(g)
    for sid, cg_id, d, status in AttendanceRecord.objects.filter(
            student_id__in=list(active), class_group_id__in=ids, date__gte=period.start, date__lte=period.end,
    ).order_by("date").values_list("student_id", "class_group_id", "date", "status"):
        out[cg_id]["records"][sid].append((d, status))
    acts = [a for a in _period_activities(period, today).filter(class_group_id__in=ids)
            if only_subjects is None or a.subject_id in only_subjects]
    act_class = {}
    for a in acts:
        out[a.class_group_id]["acts"].append(a)
        act_class[a.pk] = a.class_group_id
    for s in Submission.objects.filter(activity__in=acts, student_id__in=list(active)).only(
            "activity_id", "student_id", "status"):
        out[act_class[s.activity_id]]["subs"][s.student_id][s.activity_id] = s.status
    for ev in Evaluation.objects.filter(class_group_id__in=ids, status=PUBLISHED, date__gte=period.start,
                                        date__lte=period.end).select_related("subject").order_by("-date"):
        out[ev.class_group_id]["evals"].append(ev)
    return out


def class_report(class_group, period, *, min_subjects_below=1, min_delivery=60, only_subjects=None, rules=None,
                 preload=None):
    """``preload``: dados de ``preload_classes`` (mesmo período e disciplinas) para não consultar por turma."""
    from apps.registry.models import Student

    today = timezone.localdate()
    rules, limit = rules or school_rules(class_group.school)
    min_att = 100 - limit

    if preload is not None:
        pre = preload[class_group.pk]
        enrollments = pre["enrollments"]
        active_ids = sorted({e.student_id for e in enrollments if e.status == "ativo"})
        wanted = set(active_ids)
        students = {s.pk: s for s in pre["students"] if s.pk in wanted}
        grades, records, acts, subs = pre["grades"], pre["records"], pre["acts"], pre["subs"]
    else:
        enrollments = list(Enrollment.objects.filter(class_group=class_group).select_related("student"))
        active_ids = sorted({e.student_id for e in enrollments if e.status == "ativo"})
        students = {
            s.pk: s for s in Student.objects.filter(pk__in=active_ids).order_by("first_name", "last_name")
        }
        grades = load_grades_light(active_ids, period.start, period.end, class_group=class_group,
                                   subject_ids=only_subjects)
        records = load_attendance(active_ids, period.start, period.end, class_group=class_group)

        acts = list(_period_activities(period, today).filter(class_group=class_group))
        if only_subjects is not None:
            acts = [a for a in acts if a.subject_id in only_subjects]
        subs = defaultdict(dict)
        for s in Submission.objects.filter(activity__in=acts, student_id__in=active_ids).only(
            "activity_id", "student_id", "status"
        ):
            subs[s.student_id][s.activity_id] = s.status

    first_half, second_half = period.halves()
    subject_names = {}
    rows = []
    for sid, student in students.items():
        g = grades.get(sid, [])
        srows = _subject_rows(g, rules)
        for k, v in srows.items():
            subject_names[k] = v["subject"]
        att = attendance_summary(records.get(sid, []), limit)
        st = subs.get(sid, {})
        delivered = sum(1 for v in st.values() if v in Submission.DELIVERED_STATUSES)
        registered = len(st)
        overdue_no_rec = sum(1 for a in acts if a.pk not in st and a.deadline and a.deadline < today)
        delivery_rate = pct(delivered, registered)
        below = [r for r in srows.values() if r["below"]]
        reasons = []
        if len(below) >= min_subjects_below and below:
            reasons.append(f"{len(below)} disciplina(s) abaixo da aprovação")
        if att["percent"] is not None and att["percent"] < min_att:
            reasons.append(f"frequência {_fmt(att['percent'])}%")
        if delivery_rate is not None and registered >= 3 and delivery_rate < min_delivery:
            reasons.append(f"entrega {_fmt(delivery_rate)}%")
        h1 = _overall(_subject_rows([x for x in g if x.evaluation.date <= first_half[1]], rules))
        h2 = _overall(_subject_rows([x for x in g if x.evaluation.date >= second_half[0]], rules))
        rows.append({
            "student": student, "subjects": srows, "overall": _overall(srows),
            "attendance": att, "delivery_rate": delivery_rate, "registered": registered,
            "delivered": delivered, "no_record": overdue_no_rec,
            "reasons": reasons, "evolution": round(h2 - h1, 2) if h1 is not None and h2 is not None else None,
        })

    subjects = sorted(subject_names.values(), key=lambda s: s.name)
    subject_summary = []
    for subj in subjects:
        vals = [float(r["subjects"][subj.pk]["average"]) for r in rows
                if subj.pk in r["subjects"] and r["subjects"][subj.pk]["average"] is not None]
        passing = next((r["subjects"][subj.pk]["passing"] for r in rows if subj.pk in r["subjects"]), 6.0)
        d = describe(vals)
        subject_summary.append({
            "subject": subj, **d, "passing": passing,
            "below_count": sum(1 for v in vals if v < passing),
        })
    # Matriz: cada linha um estudante, cada coluna uma disciplina + indicadores.
    for r in rows:
        r["cells"] = [
            {"subject": s, "value": _r(r["subjects"][s.pk]["average"], 1) if s.pk in r["subjects"] else None,
             "below": r["subjects"][s.pk]["below"] if s.pk in r["subjects"] else False}
            for s in subjects
        ]

    all_records = [rec for sid in active_ids for rec in records.get(sid, [])]
    att_total = attendance_summary(all_records, limit)
    months = months_between(period.start, period.end)
    month_att = defaultdict(lambda: [0, 0])
    for d, s in all_records:
        month_att[month_key(d)][1] += 1
        if s in PRESENCE:
            month_att[month_key(d)][0] += 1
    all_grades = [g for sid in active_ids for g in grades.get(sid, [])]
    monthly_grades = _monthly_grades(all_grades)
    delivered_total = sum(r["delivered"] for r in rows)
    registered_total = sum(r["registered"] for r in rows)

    evals = pre["evals"] if preload is not None else list(
        Evaluation.objects.filter(
            class_group=class_group, status=PUBLISHED, date__gte=period.start, date__lte=period.end,
        ).select_related("subject").order_by("-date")
    )
    by_eval = defaultdict(list)
    for g in all_grades:
        by_eval[g.evaluation_id].append(float(g.value))
    eval_rows = [
        {"evaluation": e, **describe(by_eval.get(e.pk, [])),
         "missing": max(len(active_ids) - len(by_eval.get(e.pk, [])), 0)}
        for e in evals
    ]
    overall_vals = [r["overall"] for r in rows if r["overall"] is not None]
    return {
        "period": period,
        "enrolled": len({e.student_id for e in enrollments}),
        "active": len(active_ids),
        "overall": describe(overall_vals),
        "subjects": subjects,
        "subject_summary": subject_summary,
        "attendance": att_total,
        "delivery_rate": pct(delivered_total, registered_total),
        "registered": registered_total,
        "rows": rows,
        "follow_up": [r for r in rows if r["reasons"]],
        "evolved": sum(1 for r in rows if (r["evolution"] or 0) >= 0.5),
        "evolution_base": sum(1 for r in rows if r["evolution"] is not None),
        "distribution": bands(overall_vals),
        "monthly": [
            {"month": m, "label": month_label(m), "grade": monthly_grades.get(m),
             "attendance": pct(*month_att[m]) if month_att.get(m) else None}
            for m in months
        ],
        "evaluations": eval_rows,
        "criteria": {"min_subjects_below": min_subjects_below, "min_delivery": min_delivery,
                     "min_attendance": round(min_att, 1)},
        "activities_count": len(acts),
    }


# --------------------------------------------------------------------------- #
# Painel por disciplina
# --------------------------------------------------------------------------- #
def subject_report(subject, class_groups, period):
    from apps.registry.models import Student

    today = timezone.localdate()
    rules = rules_by_subject(subject.school)
    classes = []
    all_rows, all_grades = [], []
    # Tudo em lote para todas as turmas (antes, 6 consultas por turma: 140 numa escola de 24 turmas).
    class_groups = list(class_groups)
    cg_ids = [cg.pk for cg in class_groups]
    ids_by_class = defaultdict(list)
    for cid, sid in Enrollment.objects.filter(class_group_id__in=cg_ids, status="ativo")             .values_list("class_group_id", "student_id"):
        ids_by_class[cid].append(sid)
    every_id = {sid for ids in ids_by_class.values() for sid in ids}
    grades_by_pair = defaultdict(lambda: defaultdict(list))
    for sid, gs in load_grades_light(every_id, period.start, period.end, class_ids=cg_ids,
                                     subject_ids=[subject.pk]).items():
        for g in gs:
            grades_by_pair[g.evaluation.class_group_id][sid].append(g)
    names = Student.objects.in_bulk(every_id)
    act_ids_by_class = defaultdict(set)
    for aid, cid in Activity.objects.filter(
            class_group_id__in=cg_ids, subject=subject, status=Activity.Status.PUBLISHED, published_date__lte=today,
            deadline__gte=period.start, deadline__lte=period.end).values_list("pk", "class_group_id"):
        act_ids_by_class[cid].add(aid)
    subs_by_class = defaultdict(lambda: [0, 0])  # [entregues, total] só de estudantes da própria turma
    class_of_act = {aid: cid for cid, aids in act_ids_by_class.items() for aid in aids}
    members = {cid: set(ids) for cid, ids in ids_by_class.items()}
    for aid, sid, st in Submission.objects.filter(activity_id__in=list(class_of_act))             .values_list("activity_id", "student_id", "status"):
        cid = class_of_act[aid]
        if sid in members.get(cid, ()):
            subs_by_class[cid][1] += 1
            if st in Submission.DELIVERED_STATUSES:
                subs_by_class[cid][0] += 1
    for cg in class_groups:
        ids = ids_by_class.get(cg.pk, [])
        grades = grades_by_pair.get(cg.pk, {})
        vals, rows = [], []
        for sid in ids:
            r = _subject_rows(grades.get(sid, []), rules).get(subject.pk)
            if r and r["average"] is not None:
                vals.append(float(r["average"]))
                rows.append({"student": names[sid], "class_group": cg, "average": _r(r["average"], 2),
                             "passing": r["passing"], "below": r["below"], "count": r["count"]})
            all_grades.extend(grades.get(sid, []))
        done, total = subs_by_class[cg.pk]
        d = describe(vals)
        classes.append({
            "class_group": cg, "students": len(ids), **d,
            "below_count": sum(1 for r in rows if r["below"]),
            "delivery_rate": pct(done, total),
            "activities": len(act_ids_by_class.get(cg.pk, ())),
            "small": d["n"] < SMALL_GROUP,
        })
        all_rows.extend(rows)
    evals = list(
        Evaluation.objects.filter(subject=subject, class_group__in=class_groups, status=PUBLISHED,
                                  date__gte=period.start, date__lte=period.end)
        .select_related("class_group").order_by("-date")
    )
    by_eval = defaultdict(list)
    for g in all_grades:
        by_eval[g.evaluation_id].append(float(g.value))
    eval_rows = [{"evaluation": e, **describe(by_eval.get(e.pk, []))} for e in evals]
    kinds = defaultdict(list)
    for e in evals:
        kinds[e.get_kind_display()].extend(by_eval.get(e.pk, []))
    months = months_between(period.start, period.end)
    monthly = _monthly_grades(all_grades)
    lowest = sorted([r for r in eval_rows if r["mean"] is not None], key=lambda r: r["mean"])[:5]
    return {
        "period": period, "classes": classes,
        "overall": describe([r["average"] for r in all_rows]),
        "distribution": bands([r["average"] for r in all_rows]),
        "follow_up": sorted([r for r in all_rows if r["below"]], key=lambda r: r["average"]),
        "evaluations": eval_rows, "lowest": lowest,
        "by_kind": [{"kind": k, **describe(v)} for k, v in sorted(kinds.items())],
        "monthly": [{"label": month_label(m), "month": m, "value": monthly.get(m)} for m in months],
    }


# --------------------------------------------------------------------------- #
# Painel do professor
# --------------------------------------------------------------------------- #
def teacher_report(teacher, period, assignments):
    """Uma linha por turma e disciplina. As contagens saem de consultas únicas para todas as linhas
    (antes eram cerca de 11 consultas por linha); só as notas continuam por linha, como antes."""
    today = timezone.localdate()
    rules = rules_by_subject(teacher.school)
    assignments = list(assignments)
    class_ids = {a.class_group_id for a in assignments}
    subject_ids = {a.subject_id for a in assignments}
    enrolled = defaultdict(list)
    for cid, sid in Enrollment.objects.filter(class_group_id__in=class_ids, status="ativo") \
            .values_list("class_group_id", "student_id"):
        enrolled[cid].append(sid)
    published, drafts = Counter(), Counter()
    for cid, subj_id, status, when in Evaluation.objects.filter(class_group_id__in=class_ids,
                                                                 subject_id__in=subject_ids) \
            .values_list("class_group_id", "subject_id", "status", "date"):
        if status == PUBLISHED and when and period.start <= when <= period.end:
            published[(cid, subj_id)] += 1
        elif status == Evaluation.Status.DRAFT:
            drafts[(cid, subj_id)] += 1
    acts_by_pair = defaultdict(list)
    for act in Activity.objects.filter(class_group_id__in=class_ids, subject_id__in=subject_ids,
                                       status=Activity.Status.PUBLISHED, published_date__lte=today,
                                       deadline__gte=period.start, deadline__lte=period.end):
        acts_by_pair[(act.class_group_id, act.subject_id)].append(act)
    subs_by_activity = defaultdict(list)
    for act_id, sid, status in Submission.objects.filter(
            activity_id__in=[x.pk for acts in acts_by_pair.values() for x in acts]) \
            .values_list("activity_id", "student_id", "status"):
        subs_by_activity[act_id].append((sid, status))
    last_att = dict(AttendanceRecord.objects.filter(class_group_id__in=class_ids).values("class_group_id")
                    .annotate(last=Max("date")).values_list("class_group_id", "last"))
    observed = Counter(PedagogicalObservation.objects.filter(
        teacher=teacher, subject_id__in=subject_ids, observed_at__gte=period.start, observed_at__lte=period.end)
        .values_list("subject_id", "student_id"))
    # Uma consulta de notas para todos os pares (antes, uma por par: 88 com um professor de 22 turmas).
    all_ids = {sid for ids in enrolled.values() for sid in ids}
    by_pair = defaultdict(lambda: defaultdict(list))
    for sid, gs in load_grades_light(all_ids, period.start, period.end, class_ids=class_ids,
                                     subject_ids=subject_ids).items():
        for g in gs:
            by_pair[(g.evaluation.class_group_id, g.evaluation.subject_id)][sid].append(g)
    out = []
    for a in assignments:
        cg, subj = a.class_group, a.subject
        ids = enrolled.get(cg.pk, [])
        id_set = set(ids)
        pair_grades = by_pair.get((cg.pk, subj.pk), {})
        grades = {sid: pair_grades[sid] for sid in ids if sid in pair_grades}
        vals = []
        for sid in ids:
            r = _subject_rows(grades.get(sid, []), rules).get(subj.pk)
            if r and r["average"] is not None:
                vals.append((float(r["average"]), r["below"]))
        acts = acts_by_pair.get((cg.pk, subj.pk), [])
        subs = [(act.pk, sid, st) for act in acts for sid, st in subs_by_activity.get(act.pk, []) if sid in id_set]
        registered = len(subs)
        done = sum(1 for _, _, st in subs if st in Submission.DELIVERED_STATUSES)
        overdue = {x.pk for x in acts if x.deadline < today}
        expected = len(overdue) * len(ids)
        recorded_overdue = sum(1 for act_id, _, _ in subs if act_id in overdue)
        out.append({
            "assignment": a, "class_group": cg, "subject": subj, "students": len(ids),
            "average": round(statistics.fmean(v for v, _ in vals), 2) if vals else None,
            "n_with_average": len(vals), "below": sum(1 for _, b in vals if b),
            "evaluations_published": published[(cg.pk, subj.pk)],
            "evaluations_draft": drafts[(cg.pk, subj.pk)],
            "activities": len(acts), "delivery_rate": pct(done, registered),
            "records_pending": max(expected - recorded_overdue, 0),
            "last_attendance": last_att.get(cg.pk),
            "observations": sum(n for (subj_id, sid), n in observed.items() if subj_id == subj.pk and sid in id_set),
        })
    return {"period": period, "rows": out}


# --------------------------------------------------------------------------- #
# Painel institucional
# --------------------------------------------------------------------------- #
def institutional_report(school, period):
    from apps.academics.models import ClassGroup

    rules = rules_by_subject(school)
    limit = float(school_max_absences(school))
    classes = list(ClassGroup.objects.filter(school=school).select_related("school_year").order_by("name"))
    active = list(Enrollment.objects.filter(school=school, status="ativo").values_list("student_id", "class_group_id"))
    by_class = defaultdict(set)
    for sid, cid in active:
        by_class[cid].add(sid)
    ids = sorted({sid for sid, _ in active})
    grades = load_grades_light(ids, period.start, period.end)
    att = AttendanceRecord.objects.filter(school=school, date__gte=period.start, date__lte=period.end)
    att_by_class = defaultdict(lambda: [0, 0, 0])  # presença, total, faltas
    month_att = defaultdict(lambda: [0, 0])
    for cid, d, s in att.values_list("class_group_id", "date", "status"):
        att_by_class[cid][1] += 1
        month_att[month_key(d)][1] += 1
        if s in PRESENCE:
            att_by_class[cid][0] += 1
            month_att[month_key(d)][0] += 1
        else:
            att_by_class[cid][2] += 1
    rows_by_student = {sid: _subject_rows(grades.get(sid, []), rules) for sid in ids}  # uma vez por estudante
    overall = {sid: _overall(rows_by_student[sid]) for sid in ids}
    subj_acc = defaultdict(list)
    subj_names = {}
    for sid in ids:
        for k, r in rows_by_student[sid].items():
            if r["average"] is not None:
                subj_acc[k].append((float(r["average"]), r["below"]))
                subj_names[k] = r["subject"]
    subs = Submission.objects.filter(
        school=school, activity__status=Activity.Status.PUBLISHED,
        activity__deadline__gte=period.start, activity__deadline__lte=period.end,
    )
    subs_by_class = defaultdict(lambda: [0, 0])
    for cid, st in subs.values_list("activity__class_group_id", "status"):
        subs_by_class[cid][1] += 1
        if st in Submission.DELIVERED_STATUSES:
            subs_by_class[cid][0] += 1

    class_rows = []
    for cg in classes:
        members = by_class.get(cg.pk, set())
        vals = [overall[s] for s in members if overall.get(s) is not None]
        p, t, a = att_by_class[cg.pk]
        dd, dt = subs_by_class[cg.pk]
        small = len(members) < SMALL_GROUP
        class_rows.append({
            "class_group": cg, "students": len(members), "small": small,
            "average": round(statistics.fmean(vals), 2) if vals and not small else None,
            "attendance": pct(p, t) if not small else None,
            "delivery_rate": pct(dd, dt) if not small else None,
            "below_attendance": (pct(p, t) or 100) < 100 - limit if t and not small else False,
        })

    def group_by(attr, labels):
        acc = defaultdict(lambda: {"students": set(), "p": 0, "t": 0})
        for cg in classes:
            key = getattr(cg, attr) or "—"
            acc[key]["students"] |= by_class.get(cg.pk, set())
            acc[key]["p"] += att_by_class[cg.pk][0]
            acc[key]["t"] += att_by_class[cg.pk][1]
        rows = []
        for key, v in sorted(acc.items()):
            n = len(v["students"])
            vals = [overall[s] for s in v["students"] if overall.get(s) is not None]
            small = n < SMALL_GROUP
            rows.append({"label": labels.get(key, key), "students": n, "small": small,
                         "average": round(statistics.fmean(vals), 2) if vals and not small else None,
                         "attendance": pct(v["p"], v["t"]) if not small else None})
        return rows

    turns = dict(ClassGroup._meta.get_field("turn").choices)
    moves = Enrollment.objects.filter(school=school)
    entries = moves.filter(started_on__gte=period.start, started_on__lte=period.end).count()
    exits = dict(
        moves.filter(ended_on__gte=period.start, ended_on__lte=period.end)
        .values("status").annotate(n=Count("id")).values_list("status", "n")
    )
    total_p = sum(v[0] for v in att_by_class.values())
    total_t = sum(v[1] for v in att_by_class.values())
    months = months_between(period.start, period.end)
    all_grades = [g for sid in ids for g in grades.get(sid, [])]
    monthly_grades = _monthly_grades(all_grades)
    total_dd = sum(v[0] for v in subs_by_class.values())
    total_dt = sum(v[1] for v in subs_by_class.values())
    return {
        "period": period,
        "students_active": len(ids),
        "enrollments_active": len(active),
        "classes": class_rows,
        "by_grade": group_by("grade", {}),
        "by_turn": group_by("turn", turns),
        "attendance": pct(total_p, total_t),
        "absence_rate": pct(total_t - total_p, total_t),
        "overall": describe([v for v in overall.values() if v is not None]),
        "subjects": sorted(
            [{"subject": subj_names[k], **describe([v for v, _ in vals]),
              "below_count": sum(1 for _, b in vals if b)} for k, vals in subj_acc.items()],
            key=lambda r: r["subject"].name),
        "delivery_rate": pct(total_dd, total_dt),
        "movement": {"entries": entries, "transferred": exits.get("transferido", 0),
                     "dropped": exits.get("desistente", 0), "concluded": exits.get("concluido", 0)},
        "monthly": [
            {"month": m, "label": month_label(m), "grade": monthly_grades.get(m),
             "attendance": pct(*month_att[m]) if month_att.get(m) else None}
            for m in months
        ],
        "follow_up": {
            "occurrences_open": Occurrence.objects.filter(
                school=school, status__in=[Occurrence.Status.OPEN, Occurrence.Status.FOLLOW_UP]).count(),
            "plans_active": InterventionPlan.objects.filter(school=school, status=InterventionPlan.Status.ACTIVE).count(),
        },
        "limit": limit,
    }


# --------------------------------------------------------------------------- #
# Qualidade dos dados
# --------------------------------------------------------------------------- #
def data_quality(school, period):
    from apps.registry.models import Student

    today = timezone.localdate()
    active = Enrollment.objects.filter(school=school, status="ativo")
    active_by_class = defaultdict(set)
    for sid, cid in active.values_list("student_id", "class_group_id"):
        active_by_class[cid].add(sid)

    evals = list(
        Evaluation.objects.filter(school=school, status=PUBLISHED, date__gte=period.start, date__lte=period.end)
        .select_related("class_group", "subject").annotate(
            graded=Count("grades", filter=Q(grades__value__isnull=False)))
    )
    missing_grades = []
    for e in evals:
        expected = len(active_by_class.get(e.class_group_id, ()))
        if expected and e.graded < expected:
            missing_grades.append({"evaluation": e, "graded": e.graded, "expected": expected,
                                   "missing": expected - e.graded})

    partial_days = []
    days = defaultdict(lambda: defaultdict(set))
    for cid, d, sid in AttendanceRecord.objects.filter(
        school=school, date__gte=period.start, date__lte=period.end
    ).values_list("class_group_id", "date", "student_id"):
        days[cid][d].add(sid)
    from apps.academics.models import ClassGroup

    classes = {c.pk: c for c in ClassGroup.objects.filter(school=school)}
    for cid, per_day in days.items():
        expected = active_by_class.get(cid, set())
        for d, present in sorted(per_day.items()):
            faltando = expected - present
            if expected and faltando and len(faltando) < len(expected):
                partial_days.append({"class_group": classes.get(cid), "date": d, "missing": len(faltando)})
    stale = []
    last = dict(
        AttendanceRecord.objects.filter(school=school).values("class_group_id")
        .annotate(last=Max("date"))
        .values_list("class_group_id", "last")
    )
    for cid, members in active_by_class.items():
        if not members:
            continue
        d = last.get(cid)
        if d is None or (today - d).days > 14:
            stale.append({"class_group": classes.get(cid), "last": d})

    overdue = Activity.objects.filter(
        school=school, status=Activity.Status.PUBLISHED, deadline__lt=today,
        deadline__gte=period.start,
    ).select_related("class_group", "subject").annotate(n=Count("submissions"))
    activities_no_records = [a for a in overdue if a.n == 0]

    dup = (
        active.values("student_id", "school_year_id").annotate(n=Count("id")).filter(n__gt=1)
    )
    dup_ids = [d["student_id"] for d in dup]
    without_enrollment = Student.objects.filter(school=school, status="ativo").exclude(
        enrollments__status="ativo")
    without_guardian = Student.objects.filter(school=school, status="ativo").exclude(
        guardian_links__status="aprovado")
    inconsistent_status = Student.objects.filter(school=school).exclude(status="ativo").filter(
        enrollments__status="ativo").distinct()
    out_of_range = Grade.objects.filter(school=school, value__isnull=False).filter(
        Q(value__lt=0) | Q(value__gt=10)).select_related("evaluation", "student")
    # Prompt 15: sem componente ou sem ano, o acompanhamento curricular não
    # encontra as habilidades da BNCC esperadas para a turma.
    from apps.academics.models import Subject, TeacherAssignment
    from apps.curriculum.models import component_for, year_for

    taught = TeacherAssignment.objects.filter(school=school, school_year__is_current=True)
    subjects_no_component = [s for s in Subject.objects.filter(pk__in=taught.values("subject_id"))
                             if not component_for(s)]
    classes_no_year = [c for c in ClassGroup.objects.filter(pk__in=taught.values("class_group_id"))
                       if year_for(c) is None]
    return {
        "period": period,
        "missing_grades": sorted(missing_grades, key=lambda r: -r["missing"]),
        "partial_days": partial_days[-50:],
        "partial_days_total": len(partial_days),
        "stale_attendance": stale,
        "activities_no_records": activities_no_records,
        "duplicate_enrollments": Student.objects.filter(pk__in=dup_ids),
        "without_enrollment": without_enrollment,
        "without_guardian": without_guardian,
        "inconsistent_status": inconsistent_status,
        "out_of_range": out_of_range[:50],
        "subjects_no_component": subjects_no_component,
        "classes_no_year": classes_no_year,
        "not_computable": [
            ("Frequência por disciplina", "A chamada é diária por turma, não por aula."),
            ("Aulas previstas", "A carga horária planejada não é registrada; o divisor são os dias com chamada."),
            ("Metas por estudante", "A plataforma acompanha metas da escola e das turmas (Metas da escola); "
             "metas individuais de aprendizagem não são cadastradas."),
        ] + ([] if _calendar_periods(school) else [
            ("Bimestres", "O ano letivo não tem bimestres cadastrados. Cadastre-os no calendário oficial para "
             "escolher um bimestre no seletor de período; até lá, use o seletor de datas."),
        ]) + [
            ("Entregas no prazo antes de 30/10/2026", "A situação \"com atraso\" não existia; entregas antigas contam como no prazo."),
        ],
    }



# --------------------------------------------------------------------------- #
# Cadastro, rotina e impressão (Prompt 14)
# --------------------------------------------------------------------------- #
def operational_indicators(school, period):
    """Indicadores dos módulos de cadastro, fotografia, calendário e impressão.

    Mesmas regras do resto do BI: sem dado, ``None`` ("—"), nunca zero.
    """
    from django.db.models import Exists, OuterRef

    from apps.printing.models import PrintEvent, PrintRequest
    from apps.registry.models import ImportBatch, PhotoException, Student, StudentApplication
    from apps.school_calendar.services import countdown

    active = Student.objects.filter(school=school, status="ativo")
    n_active = active.count()
    exempt = PhotoException.objects.filter(student=OuterRef("pk"))
    with_photo = active.exclude(photo="").exclude(photo__isnull=True).count()
    exempted = active.filter(Q(photo="") | Q(photo__isnull=True)).filter(Exists(exempt)).count()
    prints = PrintRequest.objects.filter(school=school, created_at__date__gte=period.start,
                                         created_at__date__lte=period.end)
    delivered = list(prints.filter(status=PrintRequest.Status.DELIVERED))
    on_time = 0
    for req in delivered:
        ev = PrintEvent.objects.filter(request=req, to_status__in=["impressa", "retirada", "entregue"]) \
            .order_by("created_at").first()
        if ev and timezone.localtime(ev.created_at).date() <= req.desired_date:
            on_time += 1
    reviewed = prints.filter(status__in=["aguardando", "imprimindo", "impressa", "retirada", "entregue",
                                         "rejeitada", "correcao"]).count()
    cd = countdown(school)
    return {
        "students_active": n_active,
        "photo_pct": pct(with_photo, n_active),
        "photo_missing": n_active - with_photo - exempted,
        "photo_exempt": exempted,
        "applications_open": StudentApplication.objects.filter(school=school, status="enviado").count(),
        "applications_period": StudentApplication.objects.filter(
            school=school, submitted_at__date__gte=period.start, submitted_at__date__lte=period.end).count(),
        "imports_period": ImportBatch.objects.filter(school=school, status="concluida",
                                                     created_at__date__gte=period.start,
                                                     created_at__date__lte=period.end).count(),
        "prints_total": prints.exclude(status="rascunho").count(),
        "prints_waiting_review": PrintRequest.objects.filter(school=school, status__in=["enviada", "analise"]).count(),
        "prints_rejected_pct": pct(prints.filter(status__in=["rejeitada", "correcao"]).count(), reviewed),
        "prints_on_time_pct": pct(on_time, len(delivered)),
        "prints_copies": sum(prints.exclude(status__in=["rascunho", "rejeitada", "cancelada"])
                             .values_list("copies", flat=True)),
        "school_days_left": cd.get("year_left"),
        "calendar_reason": cd.get("reason", ""),
    }

def module_usage(school, period):
    """Utilização de cada módulo no período (Prompt 9 §6.1): quanto foi
    registrado, contado direto nas tabelas, e quantas contas entraram, por
    perfil (pelos logins na auditoria). Só contagens agregadas: nenhum nome.

    Mede uso da plataforma, não a qualidade do trabalho de ninguém.
    """
    from apps.communication.models import Announcement, Message, ServiceRequest
    from apps.core.models import AuditLog, Role
    from apps.pedagogy.models import GroupWork, LessonPlan, Occurrence
    from apps.study.models import ExamGuide, StudyQuestion

    start, end = period.start, period.end
    created = {"created_at__date__gte": start, "created_at__date__lte": end}

    def n(model, **extra):
        return model.objects.filter(school=school, **created, **extra).count()

    rows = [
        ("Atividades de casa criadas", n(Activity)),
        ("Trabalhos em grupo criados", n(GroupWork)),
        ("Avaliações criadas", n(Evaluation)),
        ("Dias de chamada (turma e data)", AttendanceRecord.objects.filter(
            school=school, date__gte=start, date__lte=end).values("class_group", "date").distinct().count()),
        ("Entregas registradas", Submission.objects.filter(
            school=school, updated_at__date__gte=start, updated_at__date__lte=end).count()),
        ("Ocorrências registradas", n(Occurrence)),
        ("Planos de aula", n(LessonPlan)),
        ("Comunicados", n(Announcement)),
        ("Mensagens trocadas", Message.objects.filter(thread__school=school, **created).count()),
        ("Solicitações abertas", n(ServiceRequest)),
        ("Conteúdos de prova criados", n(ExamGuide)),
        ("Dúvidas enviadas sobre provas", StudyQuestion.objects.filter(guide__school=school, **created).count()),
    ]
    logins = (
        AuditLog.objects.filter(school=school, action="login", **created)
        .values("user__role").annotate(users=Count("user", distinct=True))
    )
    labels = dict(Role.choices)
    by_role = sorted(
        ({"role": labels.get(r["user__role"], "—"), "users": r["users"]} for r in logins if r["user__role"]),
        key=lambda r: -r["users"],
    )
    return {"modules": [{"label": l, "count": c} for l, c in rows], "logins": by_role}
