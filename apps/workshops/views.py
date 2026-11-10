"""Telas das oficinas. As regras de quem pode o quê estão em ``services``."""

import csv
import datetime

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from apps.academics.models import ClassGroup
from apps.analytics.views import _csv_safe
from apps.core.models import Role, create_audit_log
from apps.core.params import as_id
from apps.registry.access import guardian_of

from . import services as sv
from .models import Signup, Workshop

DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class WorkshopForm(forms.ModelForm):
    class Meta:
        model = Workshop
        fields = ["title", "description", "schedule", "place", "starts_on", "ends_on", "capacity", "signup_until",
                  "class_groups"]
        widgets = {"starts_on": DATE, "ends_on": DATE, "signup_until": DATE,
                   "description": forms.Textarea(attrs={"rows": 4}), "class_groups": forms.CheckboxSelectMultiple}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        classes = sv.reachable_classes(user)
        if self.instance.pk:
            classes = ClassGroup.objects.filter(pk__in=classes) | self.instance.class_groups.all()
        self.fields["class_groups"].queryset = classes.distinct().order_by("name")
        self.restricted = user.role not in sv.MANAGE_ALL and user.role != Role.COORDENACAO.value
        if self.restricted:  # professor: escolhe entre as próprias turmas (não pode abrir para a escola toda)
            self.fields["class_groups"].required = True
            self.fields["class_groups"].help_text = "As famílias dessas turmas podem inscrever os filhos."

    def clean(self):
        data = super().clean()
        start, end, until, cap = (data.get(k) for k in ("starts_on", "ends_on", "signup_until", "capacity"))
        if start and end and end < start:
            self.add_error("ends_on", "O fim vem depois do começo.")
        if until and end and until > end:
            self.add_error("signup_until", "As inscrições terminam até o último dia da oficina.")
        if cap is not None and not 1 <= cap <= 500:
            self.add_error("capacity", "Entre 1 e 500 vagas.")
        if cap and self.instance.pk:
            taken = self.instance.signups.filter(status=Signup.Status.CONFIRMED).count()
            if cap < taken:
                self.add_error("capacity", f"Já há {taken} inscritos confirmados. Para reduzir, cancele inscrições "
                                           "antes (as famílias são avisadas).")
        return data


def index(request):
    user = request.user
    today = timezone.localdate()
    if user.role == Role.RESPONSAVEL.value and user.school_id:
        rows = []
        for w, kids in sv.family_workshops(user, today):
            mine = {s.student_id: s for s in w.signups.filter(student__in=kids)}
            rows.append({"w": w, "kids": [{"s": k, "signup": mine.get(k.pk)} for k in kids],
                         "open": w.accepts(today)})
        return render(request, "workshops/index.html", {"family": True, "rows": rows})
    if not sv.can_create(user):
        raise PermissionDenied
    qs = Workshop.objects.filter(school=user.school, ends_on__gte=today - datetime.timedelta(days=60))
    rows = [{"w": w, "c": sv.counts(w), "manage": sv.can_manage(user, w)}
            for w in qs.select_related("organizer")]
    return render(request, "workshops/index.html", {"family": False, "rows": rows, "today": today})


def workshop_form(request, pk=None):
    user = request.user
    if not sv.can_create(user):
        raise PermissionDenied
    w = get_object_or_404(Workshop, pk=pk, school=user.school) if pk else None
    if w and not sv.can_manage(user, w):
        raise PermissionDenied
    form = WorkshopForm(request.POST or None, instance=w, user=user)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if not w:
            obj.school, obj.organizer = user.school, user
        obj.save()
        form.save_m2m()
        create_audit_log(user=user, action="update" if w else "create", request=request, target=obj,
                         detail=f"{'Alterou' if w else 'Criou'} a oficina “{obj.title}” ({obj.capacity} vagas)")
        called = sv.promote(obj) if w else []
        messages.success(request, "Oficina salva." + (f" {len(called)} estudante(s) saíram da lista de espera."
                                                      if called else "") +
                         ("" if obj.published_at else " Confira e publique para as famílias se inscreverem."))
        return redirect("workshops:detail", pk=obj.pk)
    return render(request, "workshops/form.html", {"form": form, "w": w})


def detail(request, pk):
    user = request.user
    w = get_object_or_404(Workshop.objects.select_related("organizer"), pk=pk, school=user.school) \
        if user.school_id else None
    if not w:
        raise Http404
    today = timezone.localdate()
    if user.role == Role.RESPONSAVEL.value:
        kids = sv.eligible_children(user, w)
        if not kids or not w.published_at:
            raise Http404
        mine = {s.student_id: s for s in w.signups.filter(student__in=kids)}
        return render(request, "workshops/detail.html", {
            "w": w, "family": True, "open": w.accepts(today), "c": sv.counts(w),
            "kids": [{"s": k, "signup": mine.get(k.pk), "pos": sv.waiting_position(mine[k.pk]) if k.pk in mine
                      else None} for k in kids]})
    if not sv.can_create(user):
        raise PermissionDenied
    manage = sv.can_manage(user, w)
    signups = list(w.signups.select_related("student", "signed_by")) if manage else []
    from apps.library.services import class_names

    classes = class_names([s.student for s in signups]) if signups else {}
    for s in signups:
        s.cls = classes.get(s.student_id, "")
    return render(request, "workshops/detail.html", {
        "w": w, "family": False, "manage": manage, "c": sv.counts(w), "open": w.accepts(today),
        "confirmed": [s for s in signups if s.status == Signup.Status.CONFIRMED],
        "waiting": [s for s in signups if s.status == Signup.Status.WAITING],
        "canceled": [s for s in signups if s.status == Signup.Status.CANCELED],
        "allowed": sv.eligible_classes(w).order_by("name"), "all_classes": not w.class_groups.exists()})


def _managed(user, pk):
    w = get_object_or_404(Workshop, pk=pk, school=user.school) if user.school_id else None
    if not w or not sv.can_manage(user, w):
        raise PermissionDenied
    return w


@require_POST
def publish(request, pk):
    user = request.user
    w = _managed(user, pk)
    if not w.published_at:
        w.published_at = timezone.now()
        w.save(update_fields=["published_at"])
        n = sv.announce(w)
        create_audit_log(user=user, action="update", request=request, target=w,
                         detail=f"Publicou a oficina “{w.title}” ({n} aviso(s))")
        messages.success(request, f"Publicada. {n} responsáve{'is' if n != 1 else 'l'} avisado{'s' if n != 1 else ''}.")
    return redirect("workshops:detail", pk=w.pk)


@require_POST
def toggle(request, pk):
    user = request.user
    w = _managed(user, pk)
    w.closed = not w.closed
    w.save(update_fields=["closed"])
    create_audit_log(user=user, action="update", request=request, target=w,
                     detail=f"{'Encerrou' if w.closed else 'Reabriu'} as inscrições da oficina “{w.title}”")
    messages.success(request, "Inscrições encerradas. Quem está inscrito continua." if w.closed else
                     "Inscrições reabertas.")
    return redirect("workshops:detail", pk=w.pk)


@require_POST
def sign_up(request, pk):
    user = request.user
    if user.role != Role.RESPONSAVEL.value or not user.school_id:
        raise PermissionDenied
    w = get_object_or_404(Workshop, pk=pk, school=user.school, published_at__isnull=False)
    kids = sv.eligible_children(user, w)
    student = next((k for k in kids if k.pk == as_id(request.POST.get("estudante"))), None)
    if not student:
        raise Http404
    if not w.accepts(timezone.localdate()):
        messages.error(request, "As inscrições desta oficina estão encerradas.")
        return redirect("workshops:detail", pk=w.pk)
    s = sv.sign_up(w, student, user)
    create_audit_log(user=user, action="create", request=request, target=w,
                     detail=f"Inscreveu {student} na oficina “{w.title}”: {s.get_status_display().lower()}")
    if s.status == Signup.Status.CONFIRMED:
        messages.success(request, f"{student.first_name} está inscrito(a).")
    else:
        messages.info(request, f"As vagas estão preenchidas: {student.first_name} entrou na lista de espera "
                               f"({sv.waiting_position(s)}º). Você recebe um aviso se abrir vaga.")
    return redirect("workshops:detail", pk=w.pk)


@require_POST
def cancel(request, signup_pk):
    user = request.user
    s = get_object_or_404(Signup.objects.select_related("workshop", "student"), pk=signup_pk,
                          workshop__school=user.school) if user.school_id else None
    if not s:
        raise Http404
    family = user.role == Role.RESPONSAVEL.value
    if not ((family and guardian_of(user, s.student)) or sv.can_manage(user, s.workshop)):
        raise PermissionDenied
    if s.status == Signup.Status.CANCELED:
        return redirect("workshops:detail", pk=s.workshop_id)
    note = "" if family else (request.POST.get("motivo") or "").strip()
    called = sv.cancel(s, user, note)
    create_audit_log(user=user, action="update", request=request, target=s.workshop,
                     detail=f"Cancelou a inscrição de {s.student} na oficina “{s.workshop.title}”"
                            + (f"; chamou {', '.join(str(c.student) for c in called)} da espera" if called else ""))
    if not family:
        sv._tell(s, f"Inscrição cancelada: {s.student.first_name} em {s.workshop.title}",
                 f"A escola cancelou a inscrição.{' Motivo: ' + note if note else ''}", "cancelada")
    messages.success(request, "Inscrição cancelada." + (f" {called[0].student.first_name} saiu da lista de espera."
                                                       if called and not family else ""))
    return redirect("workshops:detail", pk=s.workshop_id)


def export_csv(request, pk):
    user = request.user
    w = _managed(user, pk)
    signups = list(w.signups.exclude(status=Signup.Status.CANCELED).select_related("student", "signed_by"))
    from apps.library.services import class_names

    classes = class_names([s.student for s in signups])
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{slugify(w.title)}-inscritos.csv"'
    resp.write("﻿")
    out = csv.writer(resp, delimiter=";")
    out.writerow(["Situação", "Estudante", "Turma", "Inscrito em", "Por"])
    for s in signups:
        out.writerow([_csv_safe(x) for x in (
            s.get_status_display(), s.student.full_name, classes.get(s.student_id, ""),
            timezone.localtime(s.queued_at).strftime("%d/%m/%Y %H:%M"),
            s.signed_by.get_full_name() if s.signed_by else "")])
    create_audit_log(user=user, action="export", request=request, target=w,
                     detail=f"Exportou os inscritos da oficina “{w.title}”")
    return resp
