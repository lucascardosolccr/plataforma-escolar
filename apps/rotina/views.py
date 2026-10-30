"""Cardápio escolar e quadro de horários."""

import calendar as pycal
from datetime import date, timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.academics.models import ClassGroup, TeacherAssignment
from apps.communication.models import Notification
from apps.communication.services import notify_many
from apps.core.models import Role, User, create_audit_log

from .forms import MealForm, ScheduleSlotForm
from .models import ClassSchedule, MealMenu
from .services import _by_meal, week_menu

MENU_MANAGERS = (Role.SECRETARIA.value, Role.DIRECAO.value, Role.ADMIN.value)
SCHEDULE_MANAGERS = (Role.SECRETARIA.value, Role.COORDENACAO.value, Role.DIRECAO.value, Role.ADMIN.value)


def can_manage_menu(user):
    return user.is_authenticated and user.role in MENU_MANAGERS


def _parse(value, default):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return default


def menu_view(request):
    today = timezone.localdate()
    mode = request.GET.get("ver", "semana")
    school = request.user.school
    ctx = {"today": today, "mode": mode, "can_manage": can_manage_menu(request.user),
           "tomorrow": today + timedelta(days=1)}
    if mode == "mes":
        ref = _parse((request.GET.get("mes") or "") + "-01", today.replace(day=1))
        first = ref.replace(day=1)
        last = first.replace(day=pycal.monthrange(first.year, first.month)[1])
        menus = {}
        for m in MealMenu.objects.filter(school=school, date__range=(first, last)).order_by("meal"):
            menus.setdefault(m.date, []).append(m)
        weeks = []
        for week in pycal.Calendar().monthdatescalendar(first.year, first.month):
            weeks.append([{"date": d, "in_month": d.month == first.month, "meals": _by_meal(menus.get(d, []))}
                          for d in week[:5]])
        prev_m = (first - timedelta(days=1)).replace(day=1)
        next_m = (last + timedelta(days=1))
        ctx.update({"weeks": weeks, "month": first, "prev": prev_m.strftime("%Y-%m"), "next": next_m.strftime("%Y-%m")})
    elif mode == "historico":
        past = MealMenu.objects.filter(school=school, date__lt=today).order_by("-date", "meal")
        days = {}
        for m in past[:300]:
            days.setdefault(m.date, []).append(m)
        ctx["history"] = [{"date": d, "meals": _by_meal(ms)} for d, ms in days.items()]
    else:
        mode = ctx["mode"] = "semana"
        ref = _parse(request.GET.get("semana"), today)
        monday = ref - timedelta(days=ref.weekday())
        ctx.update({"week": week_menu(school, monday), "monday": monday,
                    "prev": (monday - timedelta(days=7)).isoformat(),
                    "next": (monday + timedelta(days=7)).isoformat()})
    return render(request, "rotina/menu.html", ctx)


def menu_edit(request):
    if not can_manage_menu(request.user):
        raise PermissionDenied
    school = request.user.school
    day = _parse(request.GET.get("data") or request.POST.get("data"), timezone.localdate())
    existing = {m.meal: m for m in MealMenu.objects.filter(school=school, date=day)}
    forms = []
    for key, label in MealMenu.Meal.choices:
        inst = existing.get(key) or MealMenu(school=school, date=day, meal=key)
        forms.append((key, label, MealForm(request.POST or None, instance=inst, prefix=key)))
    if request.method == "POST" and all(f.is_valid() for _, _, f in forms):
        changed_meals = []
        with transaction.atomic():
            for key, label, f in forms:
                desc = (f.cleaned_data.get("description") or "").strip()
                inst = f.instance
                if not desc:
                    if inst.pk:
                        inst.delete()
                        changed_meals.append(f"{label} retirado")
                    continue
                was_new = inst.pk is None
                if not was_new and not f.has_changed():
                    continue
                obj = f.save(commit=False)
                obj.updated_by = request.user
                obj.save()
                if not was_new:
                    changed_meals.append(label)
            create_audit_log(user=request.user, action="update", request=request, target_type="MealMenu",
                             target_id=day.isoformat(), detail=f"Atualizou o cardápio de {day:%d/%m/%Y}")
            notified = 0
            if request.POST.get("notify") == "1" and changed_meals and day >= timezone.localdate():
                audience = User.objects.filter(
                    school=school, is_active=True, role__in=[Role.RESPONSAVEL.value, Role.ESTUDANTE.value]
                )
                stamp = timezone.now().strftime("%Y%m%d%H%M")
                notify_many(
                    school, audience, Notification.Kind.MENU,
                    f"Cardápio de {day:%d/%m} alterado",
                    body="Mudou: " + ", ".join(changed_meals) + ". Veja o cardápio atualizado.",
                    url=f"{reverse('rotina:menu')}?semana={day.isoformat()}",
                    dedupe_key=f"cardapio-{day.isoformat()}-{stamp}",
                )
                notified = audience.count()
        messages.success(request, "Cardápio salvo." + (f" {notified} pessoa(s) avisada(s)." if notified else ""))
        return redirect(f"{reverse('rotina:menu')}?semana={day.isoformat()}")
    return render(request, "rotina/menu_edit.html", {
        "day": day, "forms": forms, "has_existing": bool(existing),
        "is_future": day >= timezone.localdate(),
    })


@require_POST
def menu_copy_week(request):
    """Copia o cardápio da semana anterior para a semana escolhida (só os dias vazios)."""
    if not can_manage_menu(request.user):
        raise PermissionDenied
    monday = _parse(request.POST.get("semana"), timezone.localdate())
    monday -= timedelta(days=monday.weekday())
    copied = 0
    with transaction.atomic():
        for m in MealMenu.objects.filter(school=request.user.school,
                                         date__range=(monday - timedelta(days=7), monday - timedelta(days=3))):
            target = m.date + timedelta(days=7)
            if not MealMenu.objects.filter(school=m.school, date=target, meal=m.meal).exists():
                MealMenu.objects.create(
                    school=m.school, date=target, meal=m.meal, description=m.description,
                    ingredients=m.ingredients, allergens=m.allergens, validated_by=m.validated_by,
                    substitution=m.substitution, notes=m.notes, updated_by=request.user,
                )
                copied += 1
        create_audit_log(user=request.user, action="create", request=request, target_type="MealMenu",
                         target_id=monday.isoformat(), detail=f"Copiou {copied} refeição(ões) para a semana de {monday:%d/%m}")
    messages.success(request, f"{copied} refeição(ões) copiada(s) da semana anterior." if copied
                     else "Nada a copiar: a semana anterior está vazia ou esta já está preenchida.")
    return redirect(f"{reverse('rotina:menu')}?semana={monday.isoformat()}")


# --------------------------------------------------------------------------
# Quadro de horários


def _can_view_class_schedule(user, cg):
    if user.school_id != cg.school_id:
        return False
    if user.role in SCHEDULE_MANAGERS:
        return True
    if user.role == Role.PROFESSOR.value:
        from apps.academics.permissions import teaches

        return teaches(user, cg)
    from .services import _class_ids_for

    return cg in _class_ids_for(user)


def schedule_index(request):
    """Ponto de entrada "Horários": cada perfil cai no quadro que lhe cabe."""
    from .services import _class_ids_for

    user = request.user
    if user.role in (Role.ESTUDANTE.value, Role.RESPONSAVEL.value):
        classes = list(_class_ids_for(user))
        if len(classes) == 1:
            return schedule_class(request, classes[0].pk)
    elif user.role == Role.PROFESSOR.value:
        return schedule_teacher(request)
    else:
        classes = list(ClassGroup.objects.filter(school=user.school).select_related("school_year").order_by("name"))
    return render(request, "rotina/schedule_index.html", {"classes": classes})


def _grid(slots, weekdays=range(5)):
    times = sorted({(s.start_time, s.end_time) for s in slots})
    rows = []
    for t in times:
        cells = []
        for d in weekdays:
            cells.append([s for s in slots if s.weekday == d and (s.start_time, s.end_time) == t])
        rows.append({"start": t[0], "end": t[1], "cells": cells})
    return rows


def schedule_class(request, class_id):
    cg = get_object_or_404(ClassGroup, pk=class_id)
    if not _can_view_class_schedule(request.user, cg):
        raise PermissionDenied
    can_manage = request.user.role in SCHEDULE_MANAGERS
    form = None
    if can_manage:
        form = ScheduleSlotForm(request.POST or None, class_group=cg)
        if request.method == "POST" and form.is_valid():
            slot = form.save(commit=False)
            slot.school, slot.class_group = cg.school, cg
            slot.save()
            create_audit_log(user=request.user, action="create", request=request, target=slot,
                             detail=f"Incluiu no horário de {cg.name}: {slot}")
            messages.success(request, "Aula incluída no quadro de horários.")
            return redirect("rotina:schedule_class", class_id=cg.pk)
    slots = list(ClassSchedule.objects.filter(class_group=cg).select_related("subject", "teacher"))
    has_saturday = any(s.weekday == 5 for s in slots)
    days = list(range(6 if has_saturday else 5))
    return render(request, "rotina/schedule_class.html", {
        "cg": cg, "rows": _grid(slots, days), "days": [ClassSchedule.WEEKDAYS[d][1] for d in days],
        "form": form, "can_manage": can_manage, "slots": slots, "today_wd": timezone.localdate().weekday(),
    })


@require_POST
def schedule_delete(request, pk):
    slot = get_object_or_404(ClassSchedule, pk=pk, school=request.user.school)
    if request.user.role not in SCHEDULE_MANAGERS:
        raise PermissionDenied
    cg = slot.class_group
    create_audit_log(user=request.user, action="delete", request=request, target_type="ClassSchedule",
                     target_id=str(slot.pk), detail=f"Retirou do horário de {cg.name}: {slot}")
    slot.delete()
    messages.success(request, "Aula retirada do quadro.")
    return redirect("rotina:schedule_class", class_id=cg.pk)


def schedule_teacher(request):
    if request.user.role != Role.PROFESSOR.value:
        raise PermissionDenied
    from apps.academics.permissions import teacher_pairs

    pairs = teacher_pairs(request.user)
    slots = [
        s for s in ClassSchedule.objects.filter(school=request.user.school).select_related("subject", "class_group")
        if s.teacher_id == request.user.pk or (s.teacher_id is None and (s.class_group_id, s.subject_id) in pairs)
    ]
    return render(request, "rotina/schedule_teacher.html", {
        "rows": _grid(slots), "days": [d for _, d in ClassSchedule.WEEKDAYS[:5]],
        "today_wd": timezone.localdate().weekday(),
    })
