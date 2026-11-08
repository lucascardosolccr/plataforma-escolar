"""Para a família e o estudante: quantas faltas ainda cabem no ano, onde as faltas pesam e o que vence logo.

**Faltas que ainda cabem**

- Regra: frequência mínima de 75% do total de horas letivas (LDB, Lei 9.394/1996, art. 24, VI), ou seja, até
  25% de faltas. A escola pode configurar outro limite (``SchoolConfig.max_absences_percent``), por exemplo
  quando a rede tem regra própria.
- Base: os dias letivos do calendário oficial publicado do ano letivo. Sem calendário publicado, 200 dias (o
  mínimo da LDB, art. 24, I), e a tela avisa que é estimativa.
- Máximo de faltas no ano = parte inteira de (dias letivos × limite). Ainda cabem = máximo − faltas já
  registradas. Conta exata com fração (em ponto flutuante, 50 viraria 49,999… e sairia 49).
- Atraso conta como presença (a mesma regra do resto da plataforma). Falta justificada também conta: a LDB
  não a exclui do cálculo. Os regimes especiais (Decreto-Lei 1.044/1969, Lei 6.202/1975), com compensação de
  ausências, são tratados pela secretaria à parte, e a tela diz isso.

**Onde as faltas pesam (por disciplina)**

A chamada é diária. Cada dia de falta vale as aulas que a turma tem naquele dia da semana no quadro de
horários. Aulas dadas até hoje e aulas do ano saem dos dias letivos × quadro. É informativo: mostra em quais
disciplinas o estudante mais perdeu aula, mas a regra legal é sobre o total.

**Próximas entregas**

Atividades, trabalhos em grupo e provas com data divulgada, numa linha do tempo única, com as mesmas regras de
visibilidade das telas da família (nada em rascunho, agendado para depois ou de turma em que o estudante não
estava). Entra também o que venceu nos últimos 7 dias sem entrega registrada pelo professor.
"""

import math
from collections import Counter, defaultdict
from datetime import date, timedelta
from fractions import Fraction

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from . import access as acc
from .models import (Activity, AttendanceRecord, Evaluation, GroupWork, GroupWorkDelivery, Submission,
                     WorkGroupMember)

LDB_MIN_DAYS = 200
LEVELS = [  # (parte do limite usada, nível, rótulo)
    (Fraction(1), "acima", "acima do limite"),
    (Fraction(3, 4), "alerta", "perto do limite"),
    (Fraction(1, 2), "atencao", "metade do limite"),
]
AGENDA_DAYS = 21
OVERDUE_DAYS = 7


def _current_enrollment(student):
    from apps.registry.models import Enrollment

    active = list(Enrollment.objects.filter(student=student, status="ativo")
                  .select_related("class_group", "class_group__school_year"))
    return max(active, key=lambda e: (e.started_on or date.min)) if active else None


def max_absences(total_days, limit_percent):
    """Parte inteira de dias × limite, em fração exata."""
    return math.floor(Fraction(total_days) * Fraction(str(limit_percent)) / 100)


def level_for(absences, allowed):
    if allowed <= 0:
        return ("acima", "acima do limite") if absences else ("ok", "dentro do limite")
    used = Fraction(absences, allowed)
    if absences > allowed:
        return "acima", "acima do limite"
    for share, key, label in LEVELS[1:]:
        if used >= share:
            return key, label
    return "ok", "dentro do limite"


def attendance_outlook(student, today=None):
    """Situação de faltas do estudante no ano letivo da matrícula ativa, ou None sem matrícula."""
    from apps.analytics.bi import _justified
    from apps.analytics.services import school_max_absences
    from apps.school_calendar.services import is_published, school_days

    today = today or timezone.localdate()
    enrollment = _current_enrollment(student)
    if enrollment is None:
        return None
    cg, year = enrollment.class_group, enrollment.class_group.school_year
    start = year.start_date or date(today.year, 1, 1)
    end = year.end_date or date(today.year, 12, 31)
    days_all = school_days(year, start, end) if is_published(year) else None
    estimated = not days_all
    total_days = len(days_all) if days_all else LDB_MIN_DAYS
    elapsed = [d for d in days_all if d <= today] if days_all else None
    remaining_days = (total_days - len(elapsed)) if days_all else None

    limit = school_max_absences(student.school)
    allowed = max_absences(total_days, limit)
    records = list(AttendanceRecord.objects.filter(student=student, date__gte=start, date__lte=end)
                   .order_by("date").values_list("date", "status", "class_group_id"))
    absent_dates = [d for d, s, _ in records if s == AttendanceRecord.Status.ABSENT]
    absences = len(absent_dates)
    justified = len(_justified(student, [(d, s) for d, s, _ in records]))
    left = allowed - absences
    level, level_label = level_for(absences, allowed)
    present = len(records) - absences
    return {
        "student": student, "class_group": cg, "year": year,
        "limit": float(limit), "min_frequency": round(100 - float(limit), 1),
        "total_days": total_days, "estimated": estimated, "elapsed_days": len(elapsed) if elapsed is not None else None,
        "remaining_days": remaining_days,
        "allowed": allowed, "absences": absences, "justified": justified, "left": left,
        "used_percent": round(absences * 100 / allowed) if allowed else None,
        # Largura da barra em passos de 10% (classe CSS: a CSP não aceita estilo embutido).
        "bar_step": min(100, absences * 10 // allowed * 10) if allowed else (100 if absences else 0),
        "over": max(absences - allowed, 0),
        "level": level, "level_label": level_label,
        "recorded": len(records),
        "frequency_so_far": round(present * 100 / len(records), 1) if records else None,
        # Por disciplina, só a turma atual: o quadro de horários de outra turma seria outro.
        "subjects": _by_subject(cg, [d for d, s, c in records if c == cg.pk],
                                [d for d, s, c in records if c == cg.pk and s == AttendanceRecord.Status.ABSENT],
                                elapsed, days_all),
    }


def _by_subject(cg, recorded_dates, absent_dates, elapsed, days_all):
    """Aulas perdidas por disciplina, pelo quadro de horários da turma (None sem quadro)."""
    from apps.rotina.models import ClassSchedule

    slots = list(ClassSchedule.objects.filter(class_group=cg).values_list("weekday", "subject_id", "subject__name"))
    if not slots:
        return None
    by_weekday, names = defaultdict(Counter), {}
    for wd, sid, name in slots:
        by_weekday[wd][sid] += 1
        names[sid] = name

    def lessons(days):
        out = Counter()
        for d in days:
            out.update(by_weekday.get(d.weekday(), {}))
        return out

    missed = lessons(absent_dates)
    # Aulas dadas até hoje: dias letivos do calendário até hoje; sem calendário, os dias com chamada do estudante.
    given = lessons(elapsed if elapsed is not None else recorded_dates)
    year_total = lessons(days_all) if days_all else Counter()
    rows = []
    for sid, name in names.items():
        g = given.get(sid, 0)
        rows.append({"subject": name, "missed": missed.get(sid, 0), "given": g,
                     "year_total": year_total.get(sid) or None,
                     "missed_percent": round(missed.get(sid, 0) * 100 / g, 1) if g else None})
    rows.sort(key=lambda r: (-r["missed"], -(r["missed_percent"] or 0), r["subject"]))
    return rows


def when_label(d, today):
    days = (d - today).days
    if days == 0:
        return "hoje"
    if days == 1:
        return "amanhã"
    if days == -1:
        return "ontem"
    if days < 0:
        return f"há {-days} dias"
    return f"em {days} dias"


def upcoming(student, today=None, days=AGENDA_DAYS):
    """Atividades, trabalhos em grupo e provas com data nos próximos ``days`` dias (e o que venceu nos últimos 7
    dias sem entrega registrada), em ordem de data. Mesmas regras de visibilidade das telas da família."""
    today = today or timezone.localdate()
    start, end = today - timedelta(days=OVERDUE_DAYS), today + timedelta(days=days)
    enrollments = acc.enrollments_by_student([student.pk]).get(student.pk, [])
    class_ids = {e.class_group_id for e in enrollments}
    items = []

    acts = [a for a in Activity.objects.filter(Activity.family_visible_q(), class_group_id__in=class_ids,
                                               deadline__gte=start, deadline__lte=end)
            .select_related("subject") if acc.reaches(enrollments, a)]
    subs = {s.activity_id: s for s in Submission.objects.filter(student=student, activity__in=acts)}
    for a in acts:
        s = subs.get(a.pk)
        items.append(_item("atividade", "Atividade", a.title, a.subject.name, a.deadline, today,
                           reverse("pedagogy:activity_detail", args=[a.pk]), s.status if s else None,
                           s.get_status_display() if s else ""))

    members = list(WorkGroupMember.objects.filter(
        GroupWork.family_visible_q(prefix="group__group_work__"), student=student, removed_at__isnull=True,
        group__group_work__deadline__gte=start, group__group_work__deadline__lte=end,
    ).select_related("group__group_work__subject"))
    works = [m.group.group_work for m in members]
    delivered = {}
    for d in GroupWorkDelivery.objects.filter(group_work__in=works).filter(
            Q(student=student) | Q(student__isnull=True, group__in=[m.group for m in members])):
        delivered[d.group_work_id] = d
    for w in works:
        if w.status == GroupWork.Status.CANCELED:
            continue
        d = delivered.get(w.pk)
        items.append(_item("trabalho", "Trabalho em grupo", w.title, w.subject.name, w.deadline, today,
                           reverse("pedagogy:group_work_detail", args=[w.pk]), d.status if d else None,
                           d.get_status_display() if d else ""))

    active_classes = {e.class_group_id for e in enrollments if not e.ended_on or e.ended_on >= today}
    exams = Evaluation.objects.filter(class_group_id__in=active_classes, date__gte=today, date__lte=end) \
        .filter(Q(announced=True) | Q(status=Evaluation.Status.PUBLISHED)).select_related("subject")
    guides = _exam_guides(exams)
    for ev in exams:
        items.append(_item("prova", "Prova", ev.title, ev.subject.name, ev.date, today,
                           guides.get(ev.pk) or reverse("pedagogy:evaluation_list"), None, ""))
    # Venceu e foi entregue: sai da lista (já resolvido). Prova passada não entra (data >= hoje acima).
    items = [i for i in items if not (i["date"] < today and i["done"])]
    items.sort(key=lambda i: (i["date"], i["kind_order"], i["title"]))
    return items


def _exam_guides(exams):
    from apps.study.models import ExamGuide

    return {g.evaluation_id: reverse("study:detail", args=[g.pk])
            for g in ExamGuide.objects.filter(evaluation__in=list(exams), status=ExamGuide.Status.PUBLISHED)}


def _item(kind, kind_label, title, subject, when, today, url, status, status_label):
    done = status in ("entregue", "atrasado")
    days = (when - today).days
    if done:
        tone, note = "done", status_label
    elif days < 0:
        tone, note = "late", "venceu sem entrega registrada" if status != "nao_entregue" else status_label
    elif days <= 1:
        tone, note = "urgent", ""
    elif days <= 3:
        tone, note = "soon", ""
    else:
        tone, note = "later", ""
    return {"kind": kind, "kind_label": kind_label, "kind_order": {"prova": 0, "trabalho": 1, "atividade": 2}[kind],
            "title": title, "subject": subject, "date": when, "days": days, "when": when_label(when, today),
            "url": url, "done": done, "tone": tone, "note": note}
