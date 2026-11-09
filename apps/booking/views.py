"""Reserva de espaços e equipamentos.

Quem faz o quê:

- **reservam:** professores, coordenação, direção e secretaria;
- **cadastram os espaços e equipamentos e cancelam qualquer reserva:** direção, coordenação, secretaria e
  administração. Quem tem a reserva cancelada por outra pessoa recebe um aviso.
"""

import datetime

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.academics.models import ClassGroup
from apps.core.models import Role, create_audit_log
from apps.core.params import as_id

from .forms import BookingForm, ResourceForm, conflicts
from .models import Booking, Resource

MANAGERS = (Role.DIRECAO.value, Role.COORDENACAO.value, Role.SECRETARIA.value, Role.ADMIN.value)
BOOKERS = (Role.PROFESSOR.value, Role.DIRECAO.value, Role.COORDENACAO.value, Role.SECRETARIA.value)


def _require(user, roles):
    if user.role not in roles:
        raise PermissionDenied


def _day(request):
    try:
        return datetime.date.fromisoformat((request.GET.get("dia") or "")[:10])
    except ValueError:
        return timezone.localdate()


def _classes(user):
    qs = ClassGroup.objects.filter(school=user.school)
    current = qs.filter(school_year__is_current=True)
    qs = current if current.exists() else qs
    if user.role == Role.PROFESSOR.value:
        from apps.academics.permissions import teacher_class_ids

        qs = qs.filter(pk__in=teacher_class_ids(user))
    return qs.order_by("name")


def agenda(request):
    """Agenda do dia: cada espaço ou equipamento com as reservas, e as próximas reservas da pessoa."""
    user = request.user
    _require(user, BOOKERS + MANAGERS)
    day = _day(request)
    resources = list(Resource.objects.filter(school=user.school, active=True))
    day_bookings = list(Booking.objects.filter(school=user.school, day=day, canceled_at__isnull=True)
                        .select_related("resource", "booked_by", "class_group"))
    by_res = {}
    for b in day_bookings:
        by_res.setdefault(b.resource_id, []).append(b)
    mine = (Booking.objects.filter(booked_by=user, day__gte=timezone.localdate(), canceled_at__isnull=True)
            .select_related("resource", "class_group")[:20])
    return render(request, "booking/agenda.html", {
        "day": day, "prev": day - datetime.timedelta(days=1), "next": day + datetime.timedelta(days=1),
        "is_today": day == timezone.localdate(), "mine": mine,
        "rows": [{"r": r, "bookings": by_res.get(r.pk, [])} for r in resources],
        "can_book": user.role in BOOKERS, "can_manage": user.role in MANAGERS, "day_bookings": day_bookings})


def booking_create(request):
    user = request.user
    _require(user, BOOKERS)
    initial = {"day": _day(request)}
    if as_id(request.GET.get("recurso")):
        initial["resource"] = as_id(request.GET.get("recurso"))
    form = BookingForm(request.POST or None, school=user.school, classes=_classes(user), initial=initial)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():  # IMMEDIATE: duas reservas ao mesmo tempo não passam juntas pela conferência
            d = form.cleaned_data
            if conflicts(d["resource"], d["day"], d["start"], d["end"]).exists():
                form.add_error(None, "Alguém reservou este horário agora mesmo. Escolha outro.")
            else:
                b = form.save(commit=False)
                b.school, b.booked_by = user.school, user
                b.save()
        if not form.errors:
            create_audit_log(user=user, action="create", request=request, target=b, detail=f"Reservou {b}")
            messages.success(request, f"Reservado: {b}.")
            return redirect(f"{reverse('booking:agenda')}?dia={b.day.isoformat()}")
    return render(request, "booking/form.html", {"form": form})


@require_POST
def booking_cancel(request, pk):
    user = request.user
    b = get_object_or_404(Booking, pk=pk, school=user.school, canceled_at__isnull=True)
    if b.booked_by_id != user.pk and user.role not in MANAGERS:
        raise PermissionDenied
    b.canceled_at, b.canceled_by = timezone.now(), user
    b.save(update_fields=["canceled_at", "canceled_by"])
    create_audit_log(user=user, action="update", request=request, target=b, detail=f"Cancelou a reserva {b}")
    if b.booked_by and b.booked_by_id != user.pk and b.booked_by.is_active:
        from apps.communication.models import Notification
        from apps.communication.services import notify

        notify(user.school, b.booked_by, Notification.Kind.CALENDAR, f"Sua reserva foi cancelada: {b}",
               body=f"Cancelada por {user.get_full_name() or user.username}.",
               url=f"{reverse('booking:agenda')}?dia={b.day.isoformat()}", dedupe_key=f"reserva-cancelada:{b.pk}")
    messages.success(request, "Reserva cancelada.")
    return redirect(f"{reverse('booking:agenda')}?dia={b.day.isoformat()}")


def resource_list(request):
    user = request.user
    _require(user, MANAGERS)
    form = ResourceForm(request.POST or None, school=user.school)
    if request.method == "POST" and form.is_valid():
        r = form.save(commit=False)
        r.school = user.school
        r.save()
        create_audit_log(user=user, action="create", request=request, target=r, detail=f"Cadastrou {r} para reserva")
        messages.success(request, f"{r} disponível para reserva.")
        return redirect("booking:resources")
    return render(request, "booking/resources.html", {
        "form": form, "resources": Resource.objects.filter(school=user.school)})


def resource_edit(request, pk):
    user = request.user
    _require(user, MANAGERS)
    r = get_object_or_404(Resource, pk=pk, school=user.school)
    form = ResourceForm(request.POST or None, instance=r, school=user.school)
    if request.method == "POST" and form.is_valid():
        form.save()
        create_audit_log(user=user, action="update", request=request, target=r, detail=f"Alterou {r}")
        messages.success(request, "Alterações salvas.")
        return redirect("booking:resources")
    return render(request, "booking/resource_form.html", {"form": form, "resource": r})
