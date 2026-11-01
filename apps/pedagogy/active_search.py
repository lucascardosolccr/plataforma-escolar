"""Busca ativa e notificação ao Conselho Tutelar por infrequência.

Base legal:
- LDB (Lei 9.394/96), art. 12, VIII, com a redação da Lei 13.803/2019: a escola notifica ao Conselho
  Tutelar do Município a relação dos alunos com faltas acima de 30% do percentual permitido em lei.
- LDB, art. 24, VI: frequência mínima de 75%, ou seja, o percentual de faltas permitido em lei é 25%.
- ECA (Lei 8.069/90), art. 56, II: comunicar a reiteração de faltas injustificadas e de evasão escolar,
  esgotados os recursos escolares (por isso as ações da escola ficam registradas).

Conta: limite = dias letivos do ano × 25% × 30%. Em 200 dias letivos, 15 faltas. "Acima de" é estrito:
com exatamente 15, o estudante aparece em "atenção", com o aviso de que a próxima falta o coloca na
relação. O percentual da lei não muda com o limite de faltas que a escola configurou para aprovação.

Nada disto é automático: a lista orienta a direção, que decide e registra a notificação.
"""

import datetime
from collections import defaultdict
from decimal import Decimal

from django.utils import timezone

from apps.core.models import Role

LEGAL_ABSENCE_SHARE = Decimal("0.25")  # LDB art. 24, VI
NOTIFY_SHARE = Decimal("0.30")  # LDB art. 12, VIII
MIN_SCHOOL_DAYS = 200  # LDB art. 24, I
ATTENTION_SHARE = Decimal("0.7")  # atenção a partir de 70% do limite
STREAK = 3  # faltas seguidas nos dias de chamada da turma

ROLES = (Role.DIRECAO.value, Role.COORDENACAO.value, Role.SECRETARIA.value)


def can_use(user):
    return getattr(user, "is_authenticated", False) and user.role in ROLES


def reaches(user, student):
    """Coordenação só nos estudantes das turmas que acompanha; direção e secretaria, na escola toda."""
    if not can_use(user) or student.school_id != user.school_id:
        return False
    if user.role != Role.COORDENACAO.value:
        return True
    from apps.coordination.scope import student_ids

    ids = student_ids(user)
    return ids is None or student.pk in ids


def school_days_in_year(school):
    """(número de dias letivos do ano, de onde veio o número)."""
    from apps.school_calendar.services import current_year, is_published, school_days

    year = current_year(school)
    days = school_days(year, year.start_date, year.end_date) if year and year.start_date and year.end_date else None
    if days:
        source = ("calendário oficial publicado" if is_published(year)
                  else "dias úteis do ano letivo (o calendário oficial ainda não foi publicado)")
        return len(days), source, year
    if year is None:
        missing = "não há ano letivo atual cadastrado"
    elif not (year.start_date or year.end_date):
        missing = "o ano letivo não tem início nem término cadastrados"
    else:
        missing = f"o ano letivo não tem {'término' if year.start_date else 'início'} cadastrado"
    return MIN_SCHOOL_DAYS, f"mínimo da LDB; {missing}", year


def limit_for(n_days):
    return float(Decimal(n_days) * LEGAL_ABSENCE_SHARE * NOTIFY_SHARE)


def _scope_students(user, year):
    from apps.registry.models import Enrollment

    qs = Enrollment.objects.filter(school=user.school, status="ativo").select_related("student", "class_group")
    if year is not None:
        qs = qs.filter(class_group__school_year=year)
    if user.role == Role.COORDENACAO.value:
        from apps.coordination.scope import class_scope

        scope = class_scope(user)
        if scope is not None:
            qs = qs.filter(class_group_id__in=scope)
    out = {}
    for e in qs.order_by("student__first_name", "student__last_name"):
        out.setdefault(e.student_id, (e.student, e.class_group))
    return out


def _justified(student_ids):
    from apps.pedagogy.models import AbsenceJustification

    ranges = defaultdict(list)
    for sid, start, end in AbsenceJustification.objects.filter(
            student_id__in=student_ids, status=AbsenceJustification.Status.APPROVED) \
            .values_list("student_id", "start_date", "end_date"):
        ranges[sid].append((start, end))
    return ranges


def student_situation(student, records, ranges, actions):
    """records: [(data, situação)] do estudante; ranges: períodos justificados; actions: ações (mais nova antes)."""
    absences = sorted({d for d, s in records if s == "falta"})
    unjustified = [d for d in absences if not any(a <= d <= b for a, b in ranges)]
    streak = 0
    by_date = {}
    for d, s in records:
        by_date[d] = "falta" if s == "falta" or by_date.get(d) == "falta" else s
    for d in sorted(by_date, reverse=True):
        if by_date[d] != "falta":
            break
        streak += 1
    notified = next((a for a in actions if a.kind == "conselho"), None)
    school_actions = [a for a in actions if a.kind not in ("conselho", "retorno")]
    return {"student": student, "absences": len(absences), "unjustified": len(unjustified), "streak": streak,
            "last_absence": absences[-1] if absences else None, "notified": notified,
            "school_actions": len(school_actions), "last_action": actions[0] if actions else None}


def overview(user, today=None):
    """Relação para o Conselho Tutelar, já notificados e atenção, no alcance de quem consulta."""
    from apps.pedagogy.models import ActiveSearchAction, AttendanceRecord

    today = today or timezone.localdate()
    n_days, source, year = school_days_in_year(user.school)
    limit = limit_for(n_days)
    start = year.start_date if year and year.start_date else datetime.date(today.year, 1, 1)
    students = _scope_students(user, year)
    ids = list(students)
    records = defaultdict(list)
    for sid, d, s in AttendanceRecord.objects.filter(student_id__in=ids, date__gte=start, date__lte=today) \
            .values_list("student_id", "date", "status"):
        records[sid].append((d, s))
    ranges = _justified(ids)
    actions = defaultdict(list)
    for a in ActiveSearchAction.objects.filter(student_id__in=ids, date__gte=start).select_related("recorded_by"):
        actions[a.student_id].append(a)
    notify, notified, attention = [], [], []
    for sid, (student, cg) in students.items():
        if sid not in records:
            continue
        row = student_situation(student, records[sid], ranges.get(sid, []), actions.get(sid, []))
        row["class_group"] = cg
        if row["absences"] > limit:
            (notified if row["notified"] else notify).append(row)
        elif row["absences"] >= float(ATTENTION_SHARE) * limit or row["streak"] >= STREAK:
            row["at_limit"] = row["absences"] == limit
            attention.append(row)
    key = (lambda r: (-r["absences"], r["student"].full_name))
    return {"n_days": n_days, "source": source, "limit": limit, "limit_display": f"{limit:g}".replace(".", ","),
            "start": start, "notify": sorted(notify, key=key), "notified": sorted(notified, key=key),
            "attention": sorted(attention, key=key)}


def notify_count(user, today=None):
    """Quantos estão acima do limite sem notificação registrada no ano (para a central de pendências).
    Uma contagem agregada no banco, sem carregar a frequência do ano inteiro."""
    from django.db.models import Count

    from apps.pedagogy.models import ActiveSearchAction, AttendanceRecord

    if not can_use(user):
        return 0
    today = today or timezone.localdate()
    n_days, _source, year = school_days_in_year(user.school)
    start = year.start_date if year and year.start_date else datetime.date(today.year, 1, 1)
    qs = AttendanceRecord.objects.filter(school=user.school, status="falta", date__gte=start, date__lte=today)
    if user.role == Role.COORDENACAO.value:
        from apps.coordination.scope import student_ids

        ids = student_ids(user)
        if ids is not None:
            qs = qs.filter(student_id__in=ids)
    over = set(qs.values("student_id").annotate(n=Count("date", distinct=True)).filter(n__gt=limit_for(n_days))
               .values_list("student_id", flat=True))
    if not over:
        return 0
    notified = set(ActiveSearchAction.objects.filter(student_id__in=over, kind="conselho", date__gte=start)
                   .values_list("student_id", flat=True))
    return len(over - notified)
