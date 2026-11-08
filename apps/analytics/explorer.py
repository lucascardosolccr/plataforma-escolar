"""Dados do painel interativo (estilo BI) do estudante e da turma.

O painel interativo (``static/js/bi-explorer.js``) recebe, uma vez, os fatos do período em forma compacta e
recalcula indicadores e gráficos no navegador a cada clique, sem recarregar a página: filtro cruzado entre
os gráficos, seleção por arraste na linha do tempo e no gráfico de dispersão, matriz clicável.

Regras (as mesmas dos painéis do servidor, para os números baterem):

- notas só de avaliações publicadas, com o peso e a fórmula da disciplina (``AcademicRule``); a média geral é
  a média das médias por disciplina;
- o professor vê só as disciplinas que leciona (``only_subjects``);
- a média da turma por avaliação só aparece para a equipe e com 5 ou mais notas (grupo pequeno identifica);
- frequência = (presenças + atrasos) / registros;
- entrega = entregues (no prazo ou com atraso) / atividades com registro.

Nada de ocorrência, observação ou dado sensível vai para cá: isso continua no relatório detalhado, com as
regras próprias de cada um.
"""

from collections import defaultdict
from datetime import date

from django.urls import reverse
from django.utils import timezone

from apps.pedagogy.models import Activity, Evaluation, Grade, Submission
from apps.registry.models import Enrollment

from . import bi
from .services import rules_by_subject, school_max_absences

ATT_CODE = {"presente": "P", "atraso": "A", "falta": "F"}
SUB_CODE = {"entregue": "E", "atrasado": "T", "nao_entregue": "N"}
ACT_STATE = {"no_prazo": "E", "atrasada": "T", "nao_entregue": "N", "sem_registro": "S", "em_aberto": "O"}


def _iso(d):
    return d.isoformat() if d else None


def _f(v):
    return None if v is None else round(float(v), 2)


def _rules(school, subject_ids):
    rules = rules_by_subject(school)
    out = {}
    for sid in subject_ids:
        r = rules.get(sid)
        out[str(sid)] = {"formula": r.formula if r else "aritmetica",
                         "passing": float(r.passing_grade) if r else 6.0}
    return out


def _terms(school, period):
    """Bimestres (ou trimestres…) do calendário que cruzam o período, para os botões de recorte."""
    from apps.school_calendar.models import CalendarPeriod

    qs = CalendarPeriod.objects.filter(school=school, start__lte=period.end, end__gte=period.start).order_by("start")
    return [{"name": p.name, "start": _iso(max(p.start, period.start)), "end": _iso(min(p.end, period.end))}
            for p in qs]


def _meta(school, period, subjects):
    limit = float(school_max_absences(school))
    return {
        "period": {"start": _iso(period.start), "end": _iso(period.end), "label": period.label},
        "today": _iso(timezone.localdate()),
        "terms": _terms(school, period),
        "rules": _rules(school, [s["id"] for s in subjects]),
        "min_attendance": round(100 - limit, 1),
    }


def student_payload(student, period, *, only_subjects=None, show_class_comparison=False):
    grades = bi.load_grades([student.pk], period.start, period.end, subject_ids=only_subjects).get(student.pk, [])
    subjects = {}
    for g in grades:
        subjects[g.evaluation.subject_id] = g.evaluation.subject.name

    class_means = {}
    if show_class_comparison and grades:
        acc = defaultdict(list)
        for eid, v in Grade.objects.filter(evaluation_id__in={g.evaluation_id for g in grades},
                                           value__isnull=False).values_list("evaluation_id", "value"):
            acc[eid].append(float(v))
        class_means = {k: round(sum(v) / len(v), 2) for k, v in acc.items() if len(v) >= bi.SMALL_GROUP}

    records = bi.load_attendance([student.pk], period.start, period.end).get(student.pk, [])
    justified = bi._justified(student, records)

    enrollments = list(Enrollment.objects.filter(student=student).select_related("class_group", "school_year"))
    act = bi._activity_breakdown(student, enrollments, period, timezone.localdate(), only_subjects)
    for row in act["rows"]:
        subjects.setdefault(row["activity"].subject_id, row["activity"].subject.name)

    subject_list = [{"id": k, "name": v} for k, v in sorted(subjects.items(), key=lambda kv: kv[1])]
    active = [e for e in enrollments if e.status == "ativo"]
    current = max(active, key=lambda e: (e.started_on or date.min)) if active else None
    return {
        "kind": "student",
        "meta": {**_meta(student.school, period, subject_list),
                 "student": {"id": student.pk, "name": student.full_name,
                             "class": current.class_group.name if current else ""},
                 "class_comparison": bool(class_means)},
        "subjects": subject_list,
        # [data, disciplina, nota, peso, título, tipo, média da turma ou null]
        "grades": [[_iso(g.evaluation.date), g.evaluation.subject_id, _f(g.value), _f(g.evaluation.weight or 1),
                    g.evaluation.title, g.evaluation.get_kind_display(), class_means.get(g.evaluation_id)]
                   for g in grades],
        # [data, situação P/A/F, falta justificada 0/1]
        "attendance": [[_iso(d), ATT_CODE.get(s, s), 1 if d in justified else 0] for d, s in records],
        # [prazo (ou publicação), disciplina, situação E/T/N/S/O, título]
        "activities": [[_iso(r["activity"].deadline or r["activity"].published_date), r["activity"].subject_id,
                        ACT_STATE[r["state"]], r["activity"].title] for r in act["rows"]],
    }


def class_payload(class_group, period, user, *, only_subjects=None):
    from apps.analytics.access import can_view_student_dashboard
    from apps.registry.models import Student

    today = timezone.localdate()
    ids = sorted(set(Enrollment.objects.filter(class_group=class_group, status="ativo")
                     .values_list("student_id", flat=True)))
    students = list(Student.objects.filter(pk__in=ids).select_related("school").order_by("first_name", "last_name"))
    index = {s.pk: i for i, s in enumerate(students)}

    evals = Evaluation.objects.filter(class_group=class_group, status=bi.PUBLISHED, date__gte=period.start,
                                      date__lte=period.end).select_related("subject").order_by("date", "pk")
    if only_subjects is not None:
        evals = evals.filter(subject_id__in=list(only_subjects))
    evals = list(evals)
    eval_index = {e.pk: i for i, e in enumerate(evals)}
    grades = Grade.objects.filter(evaluation_id__in=list(eval_index), student_id__in=ids, value__isnull=False) \
        .values_list("student_id", "evaluation_id", "value")

    records = bi.load_attendance(ids, period.start, period.end, class_group=class_group)

    acts = Activity.objects.filter(class_group=class_group, status=Activity.Status.PUBLISHED,
                                   published_date__lte=today).select_related("subject")
    acts = [a for a in acts.order_by("deadline", "published_date")
            if (a.deadline and period.start <= a.deadline <= period.end)
            or (a.deadline is None and period.start <= a.published_date <= period.end)]
    if only_subjects is not None:
        acts = [a for a in acts if a.subject_id in only_subjects]
    act_index = {a.pk: i for i, a in enumerate(acts)}
    subs = Submission.objects.filter(activity_id__in=list(act_index), student_id__in=ids) \
        .values_list("student_id", "activity_id", "status")

    subjects = {}
    for e in evals:
        subjects[e.subject_id] = e.subject.name
    for a in acts:
        subjects.setdefault(a.subject_id, a.subject.name)
    subject_list = [{"id": k, "name": v} for k, v in sorted(subjects.items(), key=lambda kv: kv[1])]

    return {
        "kind": "class",
        "meta": {**_meta(class_group.school, period, subject_list),
                 "class": {"id": class_group.pk, "name": class_group.name, "year": class_group.school_year.name}},
        "subjects": subject_list,
        "students": [{"id": s.pk, "name": s.full_name,
                      "url": reverse("analytics:student_dashboard", args=[s.pk])
                      if can_view_student_dashboard(user, s) else ""}
                     for s in students],
        # [data, disciplina, peso, título, tipo]
        "evaluations": [[_iso(e.date), e.subject_id, _f(e.weight or 1), e.title, e.get_kind_display()] for e in evals],
        # [estudante, avaliação, nota]
        "grades": [[index[sid], eval_index[eid], _f(v)] for sid, eid, v in grades],
        # [estudante, data, situação P/A/F]
        "attendance": [[index[sid], _iso(d), ATT_CODE.get(st, st)] for sid in ids for d, st in records.get(sid, [])],
        # [prazo (ou publicação), disciplina, título]
        "activities": [[_iso(a.deadline or a.published_date), a.subject_id, a.title] for a in acts],
        # [estudante, atividade, situação E/T/N]
        "submissions": [[index[sid], act_index[aid], SUB_CODE.get(st, st)] for sid, aid, st in subs],
    }
