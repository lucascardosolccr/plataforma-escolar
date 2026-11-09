"""Contagem de dias letivos a partir do calendário oficial cadastrado.

Dia letivo = dia útil (segunda a sexta) dentro do ano letivo, menos os dias
cobertos por eventos "sem aula" (feriado, recesso, férias, planejamento,
suspensão...), mais os "dias letivos extras" (sábado letivo). Mudou o
calendário, mudou a conta: nada é guardado, tudo é recalculado na hora.

Sem ano letivo com início e fim, ou sem calendário publicado, as funções
devolvem ``None`` e as telas dizem isso, em vez de mostrar número inventado.
"""

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from .models import CalendarEvent, CalendarPeriod, CalendarPublication

VACATION_KINDS = ("ferias", "recesso")


def current_year(school):
    from apps.academics.models import SchoolYear

    return SchoolYear.objects.filter(school=school, is_current=True).first()


def is_published(year):
    return bool(year) and CalendarPublication.objects.filter(school_year=year).exists()


def _events(school, start, end):
    return list(
        CalendarEvent.objects.filter(school=school, start__lte=end)
        .filter(Q(end__gte=start) | Q(end__isnull=True, start__gte=start))
    )


def school_days(year, start, end, events=None):
    """Lista dos dias letivos entre ``start`` e ``end`` (inclusive), ou None
    se o ano letivo não tem início e fim cadastrados."""
    if not (year and year.start_date and year.end_date):
        return None
    start, end = max(start, year.start_date), min(end, year.end_date)
    if end < start:
        return []
    if events is None:
        events = _events(year.school, start, end)
    off = [e for e in events if e.no_classes]
    extra = [e for e in events if e.kind == CalendarEvent.Kind.EXTRA_DAY]
    days, day = [], start
    while day <= end:
        letivo = day.weekday() < 5 or any(e.covers(day) for e in extra)
        if letivo and not any(e.covers(day) for e in off):
            days.append(day)
        day += timedelta(days=1)
    return days


def next_school_day(year, after):
    days = school_days(year, after + timedelta(days=1), after + timedelta(days=120)) or []
    return days[0] if days else None


def countdown(school, today=None):
    """Resumo para os cartões da tela inicial e do calendário."""
    today = today or timezone.localdate()
    year = current_year(school)
    out = {"year": year, "published": is_published(year), "today": today}
    if not year or not (year.start_date and year.end_date):
        out["reason"] = "O ano letivo atual não tem datas de início e término cadastradas."
        return out
    if not out["published"]:
        out["reason"] = "O calendário escolar deste ano ainda não foi publicado pela escola."
        return out
    events = _events(school, min(today, year.start_date), year.end_date + timedelta(days=120))
    remaining_year = school_days(year, today, year.end_date, events)
    out["year_left"] = len(remaining_year)
    out["year_end"] = year.end_date
    out["is_school_day"] = today in (school_days(year, today, today, events) or [])
    periods = []
    for p in CalendarPeriod.objects.filter(school_year=year, start__lte=today, end__gte=today):
        periods.append({"period": p, "left": len(school_days(year, today, p.end, events)), "end": p.end})
    out["periods"] = periods
    upcoming = sorted(
        (e for e in events if e.kind in VACATION_KINDS and e.last_day >= today),
        key=lambda e: e.start,
    )
    if upcoming:
        v = upcoming[0]
        out["vacation"] = {
            "event": v, "ongoing": v.start <= today, "days_until": (v.start - today).days,
            "school_days_until": len(school_days(year, today, v.start - timedelta(days=1), events)),
            "return": next_school_day(year, v.last_day),
        }
    out["next_events"] = [
        e for e in sorted(events, key=lambda e: e.start)
        if e.start >= today and e.kind not in VACATION_KINDS
    ][:4]
    return out


def events_for_user(user, start, end):
    """Eventos oficiais que esta pessoa pode ver (os da equipe ficam fora
    para famílias e estudantes)."""
    from apps.core.models import Role

    qs = CalendarEvent.objects.filter(school=user.school, start__lte=end).filter(
        Q(end__gte=start) | Q(end__isnull=True, start__gte=start)
    )
    if user.role in (Role.RESPONSAVEL.value, Role.ESTUDANTE.value):
        qs = qs.filter(audience=CalendarEvent.Audience.ALL)
    return qs.order_by("start")
