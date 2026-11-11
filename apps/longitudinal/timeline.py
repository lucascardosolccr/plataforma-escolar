"""Linha do tempo do estudante: um registro por ano, juntando os anos anteriores lançados do histórico em
papel (``PriorYear``) e os anos cursados na plataforma (matrículas, notas publicadas e chamada).

Cada ano traz série e etapa, escola, resultado final e a ORIGEM do resultado:

- ``oficial``: lançado pela secretaria (``YearResult``) ou copiado do histórico (``PriorYear``);
- ``deduzido``: pela série do ano seguinte (mesma série = retido; série seguinte = promovido) ou pela situação
  da matrícula (transferido, desistente);
- ``estimado``: pelas médias e pela frequência, quando não há outra fonte. Não considera recuperação nem
  conselho de classe, e a tela diz isso;
- ``cursando``: ano letivo em andamento.

A média geral do ano é a média das médias por componente (mesma regra do BI). Componentes com média acima de 10
(fórmula "soma") ficam fora da média geral, porque não estão na escala de 0 a 10.

``build_many`` monta tudo com poucas consultas e serve tanto à página do estudante quanto aos painéis da escola.
"""

from collections import defaultdict
from statistics import mean

from django.db.models import Count
from django.utils import timezone

from apps.analytics.bi import _Ev, _LightGrade
from apps.analytics.services import _averages_from_grades, rules_by_subject, school_max_absences
from apps.pedagogy.models import AcademicRule, AttendanceRecord, Evaluation, Grade
from apps.registry.models import Enrollment, Student

from . import stages as st
from .models import PROMOTED, RETAINED, Outcome, PriorYear

MIN_PEERS = 5
CHRONIC = 90.0  # presença abaixo de 90% = ausência crônica (Balfanz & Byrnes, 2012)


def year_number(school_year):
    digits = "".join(c for c in school_year.name if c.isdecimal())[:4]
    if len(digits) == 4:
        return int(digits)
    return school_year.start_date.year if school_year.start_date else None


def in_progress(school_year, today):
    if school_year.end_date:
        return school_year.end_date >= today and (not school_year.start_date or school_year.start_date <= today)
    return school_year.is_current


def default_passing(school):
    """Média de aprovação mais comum nas regras da escola (6,0 sem regra)."""
    values = [float(r.passing_grade) for r in rules_by_subject(school).values() if r.passing_grade is not None]
    if not values:
        return 6.0
    return max(set(values), key=values.count)


def _percentile(value, peers):
    if value is None or len(peers) < MIN_PEERS:
        return None
    below = sum(1 for p in peers if p < value)
    equal = sum(1 for p in peers if p == value)
    return round(100.0 * (below + 0.5 * equal) / len(peers))


def _overall(subjects):
    values = [s["value"] for s in subjects if s["value"] is not None and s["value"] <= 10]
    return round(mean(values), 2) if values else None


def _platform_rows(school, students, today):
    """Anos na plataforma por estudante: {student_id: [linha]} e as médias de cada turma (para o percentil)."""
    ids = [s.pk for s in students]
    enrollments = list(Enrollment.objects.filter(student_id__in=ids, school=school)
                       .select_related("class_group", "school_year", "year_result")
                       .order_by("school_year__start_date", "school_year__name", "started_on", "pk"))
    class_ids = {e.class_group_id for e in enrollments}
    rules = rules_by_subject(school)
    limit = float(school_max_absences(school))

    # Notas publicadas de TODOS os estudantes dessas turmas: as do próprio estudante e as dos colegas (percentil).
    grades = defaultdict(list)  # (student_id, class_id) -> notas
    subjects = {}
    from apps.academics.models import Subject

    for sid, value, subj_id, subj_name, weight, d, ev_id, cg_id in (
            Grade.objects.filter(evaluation__class_group_id__in=class_ids, evaluation__status=Evaluation.Status.PUBLISHED,
                                 value__isnull=False)
            .values_list("student_id", "value", "evaluation__subject_id", "evaluation__subject__name",
                         "evaluation__weight", "evaluation__date", "evaluation_id", "evaluation__class_group_id")):
        subj = subjects.get(subj_id) or subjects.setdefault(subj_id, Subject(pk=subj_id, name=subj_name))
        grades[(sid, cg_id)].append(_LightGrade(value, _Ev(subj, weight, d, cg_id), ev_id))

    att = defaultdict(lambda: [0, 0])  # (student_id, class_id) -> [presentes, total]
    for row in (AttendanceRecord.objects.filter(student_id__in=ids, class_group_id__in=class_ids)
                .values("student_id", "class_group_id", "status").annotate(n=Count("pk"))):
        key = (row["student_id"], row["class_group_id"])
        att[key][1] += row["n"]
        if row["status"] in (AttendanceRecord.Status.PRESENT, AttendanceRecord.Status.LATE):
            att[key][0] += row["n"]

    peers = defaultdict(list)  # class_id -> médias gerais dos estudantes da turma
    by_class_students = defaultdict(set)
    for sid, cg_id in grades:
        by_class_students[cg_id].add(sid)
    for cg_id, sids in by_class_students.items():
        for sid in sids:
            overall = _overall(_subject_rows(grades[(sid, cg_id)], rules))
            if overall is not None:
                peers[cg_id].append(overall)

    per_student = defaultdict(lambda: defaultdict(list))
    for e in enrollments:
        per_student[e.student_id][e.school_year_id].append(e)

    out = defaultdict(list)
    for sid, years in per_student.items():
        for _, ens in years.items():
            sy = ens[-1].school_year
            year = year_number(sy)
            if year is None:
                continue
            all_grades = [g for e in ens for g in grades.get((sid, e.class_group_id), [])]
            subj_rows = _subject_rows(all_grades, rules)
            present = sum(att[(sid, e.class_group_id)][0] for e in ens)
            total = sum(att[(sid, e.class_group_id)][1] for e in ens)
            last = ens[-1]
            overall = _overall(subj_rows)
            out[sid].append({
                "year": year, "source": "plataforma", "school_name": school.name,
                "grade_label": last.class_group.grade or last.class_group.name,
                "stage": st.stage_of_class(last.class_group), "class_group": last.class_group,
                "enrollments": ens, "school_year": sy,
                "subjects": subj_rows, "average": overall,
                "attendance": round(100.0 * present / total, 1) if total else None, "attendance_records": total,
                "min_attendance": round(100 - limit, 1),
                "percentile": _percentile(overall, peers.get(last.class_group_id, [])),
                "peers": len(peers.get(last.class_group_id, [])),
                "in_progress": in_progress(sy, today),
                "result": getattr(last, "year_result", None),
                "enrollment_status": last.status,
            })
    return out


def _subject_rows(grades, rules):
    out = []
    for a in _averages_from_grades(grades, rules):
        rule = rules.get(a["subject"].pk)
        out.append({"name": a["subject"].name, "key": st.subject_key(a["subject"].name),
                    "value": float(a["average"]) if a["average"] is not None else None,
                    "passing": a["passing"], "below": a["below"], "count": a["count"],
                    "formula": rule.formula if rule else AcademicRule.Formula.ARITHMETIC})
    return out


def year_progress(school_year, today):
    """Fração do ano letivo já decorrida (0 a 1), pelo calendário do ano; None sem datas."""
    if not school_year.start_date or not school_year.end_date or school_year.end_date <= school_year.start_date:
        return None
    total = (school_year.end_date - school_year.start_date).days
    return min(max((today - school_year.start_date).days / total, 0.0), 1.0)


def needed_grades(row, today=None):
    """Quanto falta, por componente, no ano em andamento: a média necessária no restante do ano.

    Suposição declarada na tela: o restante do ano pesa na média o mesmo que a parte do ano que ele representa no
    calendário (ex.: faltando 40% do ano, as próximas notas valem 40% da média). Só para média aritmética ou
    ponderada; melhor nota e soma não admitem essa conta.
    """
    if not row.get("in_progress") or row["source"] != "plataforma":
        return []
    done = year_progress(row["school_year"], today or timezone.localdate())
    if done is None or done <= 0.05 or done >= 0.98:
        return []
    out = []
    for s in row["subjects"]:
        if s["value"] is None or s["formula"] not in (AcademicRule.Formula.ARITHMETIC, AcademicRule.Formula.WEIGHTED):
            continue
        need = (s["passing"] - s["value"] * done) / (1 - done)
        out.append({**s, "need": round(need, 1), "done": done,
                    "status": "impossivel" if need > 10 else "folga" if need <= 0 else
                    "atencao" if need > s["value"] + 1 else "ok"})
    return out


def _prior_rows(students, passing):
    out = defaultdict(list)
    for p in (PriorYear.objects.filter(student__in=students).prefetch_related("grades")
              .order_by("year", "pk")):
        ref = float(p.passing_grade) if p.passing_grade is not None else passing
        subj = []
        for g in p.grades.all():
            v = g.normalized()
            subj.append({"name": g.subject, "key": st.subject_key(g.subject),
                         "value": round(v, 2) if v is not None else None, "concept": g.concept,
                         "passing": ref, "below": v is not None and v < ref})
        out[p.student_id].append({
            "year": p.year, "source": "historico", "school_name": p.school_name, "grade_label": p.grade_label,
            "stage": p.stage or st.parse_stage(p.grade_label), "record": p, "subjects": subj,
            "average": _overall(subj),
            "attendance": float(p.attendance_percent) if p.attendance_percent is not None else None,
            "attendance_records": None, "min_attendance": 75.0, "percentile": None, "peers": 0,
            "in_progress": False, "result": None, "enrollment_status": None,
        })
    return out


def _resolve_outcomes(rows):
    """Resultado de cada ano e a origem dele (oficial, deduzido, estimado, cursando)."""
    for i, r in enumerate(rows):
        nxt = rows[i + 1] if i + 1 < len(rows) else None
        r["outcome"], r["basis"] = Outcome.UNKNOWN, ""
        if r["source"] == "historico" and r["record"].outcome != Outcome.UNKNOWN:
            r["outcome"], r["basis"] = r["record"].outcome, "oficial"
        elif r["result"] is not None:
            r["outcome"], r["basis"] = r["result"].outcome, "oficial"
        elif r["in_progress"]:
            r["basis"] = "cursando"
        elif r["enrollment_status"] == "transferido" and (nxt is None or nxt["year"] > r["year"]):
            r["outcome"], r["basis"] = Outcome.TRANSFERRED, "deduzido"
        elif r["enrollment_status"] == "desistente":
            r["outcome"], r["basis"] = Outcome.DROPOUT, "deduzido"
        elif nxt and r["stage"] and nxt["stage"] and nxt["year"] == r["year"] + 1 and nxt["stage"] == r["stage"]:
            r["outcome"], r["basis"] = Outcome.RETAINED, "deduzido"
        elif nxt and r["stage"] and nxt["stage"] and nxt["stage"] == r["stage"] + 1:
            r["outcome"], r["basis"] = Outcome.APPROVED, "deduzido"
        elif r["subjects"] or r["attendance"] is not None:
            below = any(s["below"] for s in r["subjects"])
            low_att = r["attendance"] is not None and r["attendance"] < r["min_attendance"]
            if not below and not low_att and r["subjects"]:
                r["outcome"], r["basis"] = Outcome.APPROVED, "estimado"
            else:
                r["basis"] = "estimado"
        r["outcome_label"] = Outcome(r["outcome"]).label
        r["promoted"] = r["outcome"] in PROMOTED
        r["retained"] = r["outcome"] in RETAINED


def adverse(row):
    """Desfecho desfavorável do ano (rótulo das previsões), ou None quando não é observável.

    Retenção, abandono ou terminar o ano com algum componente abaixo da média de aprovação. Transferido no
    meio do ano e ano em andamento ficam de fora: o desfecho não foi observado.
    """
    if row["in_progress"] or row["outcome"] == Outcome.TRANSFERRED:
        return None
    if row["retained"] or row["outcome"] == Outcome.DROPOUT:
        return 1
    if row["subjects"]:
        return int(any(s["below"] for s in row["subjects"] if s["value"] is not None))
    if row["promoted"]:
        return 0
    return None


def _annotate(student, rows):
    retentions = 0
    prev_school = None
    changes = 0
    for i, r in enumerate(rows):
        r["n_below"] = sum(1 for s in r["subjects"] if s["below"])
        r["min_subject"] = min((s["value"] for s in r["subjects"] if s["value"] is not None and s["value"] <= 10),
                               default=None)
        r["age"] = st.age_on_cutoff(student.birth_date, r["year"])
        r["expected_age"] = st.expected_age(r["stage"])
        r["distortion"] = st.distortion(student.birth_date, r["year"], r["stage"])
        r["retentions_before"] = retentions
        if r["retained"]:
            retentions += 1
        # Troca de escola fora da passagem de etapa (5º→6º, 9º→1ª série): mobilidade não promocional.
        if prev_school is not None and _norm(r["school_name"]) != _norm(prev_school):
            prev_stage = rows[i - 1]["stage"]
            structural = prev_stage in (5, 9) and r["stage"] == (prev_stage or 0) + 1
            if not structural:
                changes += 1
        r["school_changes"] = changes
        prev_school = r["school_name"]
        prev = rows[i - 1] if i else None
        r["delta"] = (round(r["average"] - prev["average"], 2)
                      if prev and prev["year"] == r["year"] - 1 and r["average"] is not None
                      and prev["average"] is not None else None)
        r["chronic"] = r["attendance"] is not None and r["attendance"] < CHRONIC
        r["adverse"] = adverse(r)
        r["stage_label"] = st.stage_label(r["stage"])


def _norm(name):
    return " ".join((name or "").lower().split())


def build_many(school, students, today=None):
    """{student_id: [ano, …]} do mais antigo ao mais recente."""
    today = today or timezone.localdate()
    students = list(students)
    passing = default_passing(school)
    platform = _platform_rows(school, students, today)
    prior = _prior_rows(students, passing)
    out = {}
    for s in students:
        rows = sorted(prior.get(s.pk, []) + platform.get(s.pk, []),
                      key=lambda r: (r["year"], 0 if r["source"] == "historico" else 1))
        _resolve_outcomes(rows)
        _annotate(s, rows)
        out[s.pk] = rows
    return out


def build(student, today=None):
    return build_many(student.school, [student], today)[student.pk]


def complete(rows):
    return [r for r in rows if not r["in_progress"]]


def students_of(school, ids=None):
    qs = Student.objects.filter(school=school)
    return qs if ids is None else qs.filter(pk__in=ids)

