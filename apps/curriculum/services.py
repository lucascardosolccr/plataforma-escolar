"""Quem alcança quais pares turma+disciplina e os indicadores de acompanhamento curricular.

Os indicadores servem ao planejamento e à reflexão pedagógica. Não há
ranking de professores nem de estudantes, e nenhum número aqui alimenta
avaliação de desempenho (Prompt 15, seção 3.3).
"""

import datetime
from collections import OrderedDict

from django.utils import timezone

from apps.academics.models import ClassGroup, Subject, TeacherAssignment
from apps.core.models import Role

from .models import CurriculumItem, LearningEvidence, component_for, year_for

STAFF_ROLES = (Role.PROFESSOR.value, Role.COORDENACAO.value, Role.DIRECAO.value)
REFERENCE_ROLES = STAFF_ROLES + (Role.SECRETARIA.value, Role.ADMIN.value)


def can_use(user):
    return getattr(user, "is_authenticated", False) and user.role in STAFF_ROLES


def can_manage_items(user):
    return getattr(user, "is_authenticated", False) and user.role in (Role.COORDENACAO.value, Role.DIRECAO.value)


def pairs_for(user):
    """(turma_id, disciplina_id) que a pessoa acompanha."""
    from apps.academics.permissions import teacher_pairs
    from apps.coordination.scope import class_scope

    if not can_use(user):
        return set()
    if user.role == Role.PROFESSOR.value:
        return set(teacher_pairs(user))
    qs = TeacherAssignment.objects.filter(school=user.school, school_year__is_current=True)
    if user.role == Role.COORDENACAO.value:
        scope = class_scope(user)
        if scope is not None:
            qs = qs.filter(class_group_id__in=scope)
    return set(qs.values_list("class_group_id", "subject_id"))


def pair_options(user):
    pairs = pairs_for(user)
    classes = {c.pk: c for c in ClassGroup.objects.filter(pk__in={c for c, _ in pairs})}
    subjects = {s.pk: s for s in Subject.objects.filter(pk__in={s for _, s in pairs})}
    rows = [(classes[c], subjects[s]) for c, s in pairs if c in classes and s in subjects]
    rows.sort(key=lambda r: (r[0].name, r[1].name))
    return rows


PICKER_SOURCES = [
    (CurriculumItem.Kind.SKILL, ""),
    (CurriculumItem.Kind.DF_OBJECTIVE, " · Currículo em Movimento: objetivos"),
    (CurriculumItem.Kind.DF_CONTENT, " · Currículo em Movimento: conteúdos"),
    (CurriculumItem.Kind.OWN, " · objetivos da escola"),
]


def picker_groups(user, selected=(), focus_class=None):
    """Grupos de itens para marcar no formulário (atividade, prova, plano).

    Para o professor, um grupo por par turma+disciplina com as habilidades do
    componente e do ano; depois as competências gerais; por fim, os itens já
    marcados que não caberiam em nenhum grupo (item de outro ano, por exemplo).
    """
    school = user.school
    groups, used = [], set()
    seen_keys = set()
    pairs = pair_options(user)
    if focus_class:
        # Com a turma já definida (edição, ou criação a partir da turma), só os grupos dela: um professor
        # de 22 turmas recebia 390 KB de habilidades de todos os anos. Turma sem par: lista completa.
        pairs = [p for p in pairs if p[0].pk == focus_class] or pairs
    by_comp = {}  # uma consulta por componente; o ano é filtrado aqui (antes, duas por componente × ano)
    for cg, subject in pairs:
        comp, year = component_for(subject), year_for(cg)
        if not comp:
            continue
        key = (comp, year)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        if comp not in by_comp:
            by_comp[comp] = list(CurriculumItem.for_pair(school, comp, None).order_by("code"))
        items = [i for i in by_comp[comp] if not year or year in i.year_list or not i.year_list]
        label = f"{comp} — {year}º ano" if year else comp
        # um grupo por fonte, BNCC primeiro: com o Currículo em Movimento importado, um grupo único
        # passaria de cem itens e abriria pelos conteúdos
        for kind, suffix in PICKER_SOURCES:
            part = [i for i in items if i.kind == kind]
            if part:
                groups.append((label + suffix, part))
                used |= {i.pk for i in part}
    general = list(CurriculumItem.objects.filter(kind=CurriculumItem.Kind.GENERAL, active=True,
                                                 school__isnull=True).order_by("code"))
    groups.append(("Competências gerais da BNCC", general))
    used |= {i.pk for i in general}
    extra = [i for i in CurriculumItem.objects.filter(pk__in=selected).order_by("code") if i.pk not in used]
    if extra:
        groups.insert(0, ("Já selecionados", extra))
    return groups


def coverage(class_group, subject, today=None):
    """Indicadores do par turma+disciplina no ano letivo da turma."""
    from apps.pedagogy.models import Activity, Evaluation, GroupWork, LessonPlan, LessonRecord

    today = today or timezone.localdate()
    year = class_group.school_year
    start = year.start_date or datetime.date(today.year, 1, 1)
    end = year.end_date or datetime.date(today.year, 12, 31)
    base = {"class_group": class_group, "subject": subject}

    plans = LessonPlan.objects.filter(**base).prefetch_related("curriculum")
    acts = (Activity.objects.filter(**base, status=Activity.Status.PUBLISHED, class_date__gte=start,
                                    class_date__lte=min(today, end)).prefetch_related("curriculum"))
    works = (GroupWork.objects.filter(**base, status=GroupWork.Status.PUBLISHED, published_date__gte=start,
                                      published_date__lte=min(today, end)).prefetch_related("curriculum"))
    evals = (Evaluation.objects.filter(**base, date__gte=start, date__lte=min(today, end))
             .prefetch_related("curriculum"))
    evidence = list(LearningEvidence.objects.filter(**base).select_related("item").order_by("observed_on", "pk"))

    planned, planned_past = {}, {}
    for p in plans:
        for item in p.curriculum.all():
            planned.setdefault(item.pk, item)
            if p.ends_on < today:
                planned_past.setdefault(item.pk, item)
    worked, first_seen = {}, {}

    def mark(item, day, bucket):
        bucket.setdefault(item.pk, item)
        if item.pk not in first_seen or day < first_seen[item.pk]:
            first_seen[item.pk] = day

    for a in acts:
        for item in a.curriculum.all():
            mark(item, a.class_date, worked)
    for w in works:
        for item in w.curriculum.all():
            mark(item, w.published_date, worked)
    # Diário de classe: o que o professor registrou como trabalhado em aula.
    for rec in LessonRecord.objects.filter(**base, date__gte=start, date__lte=min(today, end))             .prefetch_related("curriculum"):
        for item in rec.curriculum.all():
            mark(item, rec.date, worked)
    assessed = {}
    for e in evals:
        for item in e.curriculum.all():
            mark(item, e.date, assessed)
    evidenced, last_judgement = {}, {}
    for ev in evidence:
        mark(ev.item, ev.observed_on, evidenced)
        last_judgement[ev.item_id] = ev.judgement
    retake = {pk: evidenced[pk] for pk, j in last_judgement.items() if j == LearningEvidence.Judgement.RETAKE}
    touched = set(worked) | set(assessed) | set(evidenced)
    not_done = {pk: i for pk, i in planned_past.items() if pk not in touched}

    comp, grade_year = component_for(subject), year_for(class_group)
    expected = list(CurriculumItem.for_pair(class_group.school, comp, grade_year)
                    .filter(kind=CurriculumItem.Kind.SKILL)) if comp else []
    expected_ids = {i.pk for i in expected}
    gaps = [i for i in expected if i.pk not in planned and i.pk not in touched]

    all_ids = set(planned) | touched
    items = {}
    for bucket in (planned, worked, assessed, evidenced):
        items.update(bucket)
    rows = []
    for pk in sorted(all_ids, key=lambda k: items[k].code):
        rows.append({
            "item": items[pk], "planned": pk in planned, "worked": pk in worked, "assessed": pk in assessed,
            "evidenced": pk in evidenced, "retake": pk in retake, "judgement": last_judgement.get(pk),
            "not_done": pk in not_done, "expected": pk in expected_ids,
        })

    months = OrderedDict()
    cursor = start.replace(day=1)
    while cursor <= min(today, end):
        months[cursor] = 0
        cursor = (cursor + datetime.timedelta(days=32)).replace(day=1)
    for day in first_seen.values():
        key = day.replace(day=1)
        if key in months:
            months[key] += 1
    running, evolution = 0, []
    for month, n in months.items():
        running += n
        evolution.append({"month": month, "new": n, "total": running})

    return {
        "component": comp, "grade_year": grade_year,
        "counts": {"planned": len(planned), "worked": len(worked), "assessed": len(assessed),
                   "evidenced": len(evidenced), "retake": len(retake), "not_done": len(not_done),
                   "expected": len(expected), "gaps": len(gaps)},
        "rows": rows, "gaps": gaps, "not_done": list(not_done.values()), "retake": list(retake.values()),
        "evolution": evolution, "max_total": max([e["total"] for e in evolution] + [1]),
        "period": (start, end),
    }
