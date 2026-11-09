"""Cadastro do calendário escolar oficial e visão mensal/semanal."""

import calendar as pycal
from datetime import timedelta

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.academics.models import SchoolYear
from apps.communication.models import Notification
from apps.communication.services import notify_many
from apps.core.models import Role, User, create_audit_log
from apps.core.params import digits

from .models import CalendarEvent, CalendarPeriod, CalendarPublication
from .services import countdown, events_for_user, school_days

MANAGERS = (Role.SECRETARIA.value, Role.DIRECAO.value, Role.ADMIN.value)
DATE = forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})


def can_manage_calendar(user):
    return user.is_authenticated and user.role in MANAGERS


class PeriodForm(forms.ModelForm):
    class Meta:
        model = CalendarPeriod
        fields = ["kind", "name", "start", "end"]
        widgets = {"start": DATE, "end": DATE}

    def __init__(self, *args, year=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.year = year

    def clean(self):
        data = super().clean()
        s, e = data.get("start"), data.get("end")
        if s and e and e < s:
            self.add_error("end", "O término não pode ser antes do início.")
        y = self.year
        if s and e and y and y.start_date and y.end_date and (s < y.start_date or e > y.end_date):
            self.add_error("start", f"O período precisa caber no ano letivo ({y.start_date:%d/%m/%Y} a {y.end_date:%d/%m/%Y}).")
        if s and e and y and data.get("kind"):
            overlap = CalendarPeriod.objects.filter(school_year=y, kind=data["kind"], start__lte=e, end__gte=s)
            if overlap.exists():
                self.add_error("start", f"Sobrepõe {overlap.first().name}.")
        return data


class EventForm(forms.ModelForm):
    notify = forms.BooleanField(required=False, label="Avisar a comunidade por notificação")

    class Meta:
        model = CalendarEvent
        fields = ["kind", "title", "start", "end", "no_classes", "audience", "description"]
        widgets = {"start": DATE, "end": DATE, "description": forms.Textarea(attrs={"rows": 2})}

    def clean(self):
        data = super().clean()
        s, e = data.get("start"), data.get("end")
        if s and e and e < s:
            self.add_error("end", "A data final não pode ser antes da inicial.")
        if data.get("kind") in CalendarEvent.NO_CLASS_KINDS:
            data["no_classes"] = True
        if data.get("kind") == CalendarEvent.Kind.EXTRA_DAY:
            data["no_classes"] = False
        return data


def official_manage(request):
    if not can_manage_calendar(request.user):
        raise PermissionDenied
    school = request.user.school
    years = SchoolYear.objects.filter(school=school).order_by("-name")
    year = None
    if digits(request.GET.get("ano") or ""):
        year = get_object_or_404(SchoolYear, pk=request.GET["ano"], school=school)
    year = year or years.filter(is_current=True).first() or years.first()
    period_form = PeriodForm(prefix="p", year=year)
    event_form = EventForm(prefix="e")
    if request.method == "POST" and year:
        if request.POST.get("form") == "period":
            period_form = PeriodForm(request.POST, prefix="p", year=year)
            if period_form.is_valid():
                p = period_form.save(commit=False)
                p.school, p.school_year = school, year
                p.save()
                create_audit_log(user=request.user, action="create", request=request, target=p,
                                 detail=f"Cadastrou o período {p}")
                messages.success(request, "Período cadastrado.")
                return redirect(f"{reverse('school_calendar:official')}?ano={year.pk}")
        elif request.POST.get("form") == "event":
            event_form = EventForm(request.POST, prefix="e")
            if event_form.is_valid():
                with transaction.atomic():
                    ev = event_form.save(commit=False)
                    ev.school, ev.school_year, ev.created_by = school, year, request.user
                    ev.save()
                    create_audit_log(user=request.user, action="create", request=request, target=ev,
                                     detail=f"Cadastrou no calendário: {ev.get_kind_display()} — {ev}")
                    sent = 0
                    if event_form.cleaned_data.get("notify"):
                        roles = [Role.RESPONSAVEL.value, Role.ESTUDANTE.value] if ev.audience == "todos" else []
                        audience = User.objects.filter(school=school, is_active=True).filter(
                            role__in=roles + [r for r in Role.values if r not in (Role.RESPONSAVEL.value, Role.ESTUDANTE.value)]
                        ).exclude(pk=request.user.pk)
                        when = ev.start.strftime("%d/%m") + (f" a {ev.end:%d/%m}" if ev.end and ev.end != ev.start else "")
                        notify_many(school, audience, Notification.Kind.CALENDAR,
                                    f"Calendário: {ev.title} ({when})",
                                    body=(ev.description or ev.get_kind_display())
                                    + (" Não haverá aula." if ev.no_classes else ""),
                                    url=reverse("school_calendar:calendar_index") + f"?ver=mes&mes={ev.start:%Y-%m}",
                                    dedupe_key=f"calendario-{ev.pk}")
                        sent = audience.count()
                messages.success(request, "Evento cadastrado. A contagem de dias letivos já considera a mudança."
                                 + (f" {sent} pessoa(s) avisada(s)." if sent else ""))
                return redirect(f"{reverse('school_calendar:official')}?ano={year.pk}")
    periods = CalendarPeriod.objects.filter(school_year=year).order_by("kind", "start") if year else []
    events = CalendarEvent.objects.filter(school=school, school_year=year).order_by("start") if year else []
    total = None
    if year and year.start_date and year.end_date:
        total = len(school_days(year, year.start_date, year.end_date))
        for p in periods:
            p.days = len(school_days(year, p.start, p.end))
    return render(request, "school_calendar/official_manage.html", {
        "years": years, "year": year, "periods": periods, "events": events, "total_days": total,
        "period_form": period_form, "event_form": event_form,
        "published": bool(year) and CalendarPublication.objects.filter(school_year=year).first(),
        "summary": countdown(school),
    })


@require_POST
def official_delete(request, kind, pk):
    if not can_manage_calendar(request.user):
        raise PermissionDenied
    model = CalendarPeriod if kind == "periodo" else CalendarEvent
    obj = get_object_or_404(model, pk=pk, school=request.user.school)
    year_id = obj.school_year_id
    create_audit_log(user=request.user, action="delete", request=request, target_type=model.__name__,
                     target_id=str(obj.pk), detail=f"Retirou do calendário: {obj}")
    obj.delete()
    messages.success(request, "Retirado do calendário.")
    return redirect(f"{reverse('school_calendar:official')}?ano={year_id or ''}")


@require_POST
def official_publish(request, year_id):
    if not can_manage_calendar(request.user):
        raise PermissionDenied
    year = get_object_or_404(SchoolYear, pk=year_id, school=request.user.school)
    if request.POST.get("action") == "unpublish":
        CalendarPublication.objects.filter(school_year=year).delete()
        detail, msg = f"Retirou a publicação do calendário de {year}", "Calendário volta a ser rascunho."
    else:
        if not (year.start_date and year.end_date):
            messages.error(request, "Cadastre o início e o término do ano letivo antes de publicar.")
            return redirect(f"{reverse('school_calendar:official')}?ano={year.pk}")
        CalendarPublication.objects.update_or_create(school_year=year, defaults={"published_by": request.user})
        detail, msg = f"Publicou o calendário oficial de {year}", "Calendário publicado: a contagem de dias letivos aparece para todos."
    create_audit_log(user=request.user, action="update", request=request, target=year, detail=detail)
    messages.success(request, msg)
    return redirect(f"{reverse('school_calendar:official')}?ano={year.pk}")


def month_grid(user, ref, extra_events=()):
    """Semanas do mês com eventos oficiais e dos módulos, para a visão mensal."""
    first = ref.replace(day=1)
    last = first.replace(day=pycal.monthrange(first.year, first.month)[1])
    official = list(events_for_user(user, first, last))
    by_day = {}
    for ev in official:
        d = max(ev.start, first)
        while d <= min(ev.last_day, last):
            by_day.setdefault(d, []).append({"title": ev.title, "kind": ev.kind, "label": ev.get_kind_display(),
                                             "off": ev.no_classes, "official": True})
            d += timedelta(days=1)
    for e in extra_events:
        if first <= e["date"] <= last:
            by_day.setdefault(e["date"], []).append({"title": e["title"], "kind": e["kind"],
                                                     "label": e["kind_label"], "url": e.get("url"), "official": False})
    weeks = []
    for week in pycal.Calendar().monthdatescalendar(first.year, first.month):
        weeks.append([{"date": d, "in_month": d.month == first.month, "events": by_day.get(d, []),
                       "weekend": d.weekday() >= 5} for d in week])
    return {"weeks": weeks, "month": first, "prev": (first - timedelta(days=1)).strftime("%Y-%m"),
            "next": (last + timedelta(days=1)).strftime("%Y-%m")}
