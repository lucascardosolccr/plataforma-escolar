"""Telas dos documentos da matrícula. As regras de quem pode o quê estão em ``services``."""

import csv
import datetime

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.academics.models import ClassGroup
from apps.analytics.views import _csv_safe
from apps.core.models import Role, create_audit_log
from apps.core.params import as_id, digits, name_q
from apps.registry.models import Student

from . import services as sv
from .models import RequiredDocument, StudentDocument


class DocumentForm(forms.ModelForm):
    class Meta:
        model = RequiredDocument
        fields = ["name", "hint", "mandatory", "position", "active"]


def _classes(school):
    return ClassGroup.objects.filter(school=school, school_year__is_current=True).order_by("name")


def index(request):
    user = request.user
    if user.role == Role.RESPONSAVEL.value and user.school_id:
        kids = sv.children(user)
        if not sv.in_use(user.school):
            return render(request, "paperwork/family.html", {"rows": [], "unused": True})
        docs = sv.documents(user.school)
        recs = sv.records([s.pk for s in kids])
        rows = [{"s": s, "items": [{"d": d, "r": recs.get((s.pk, d.pk))} for d in docs]} for s in kids]
        return render(request, "paperwork/family.html", {"rows": rows})
    if not sv.can_manage(user):
        raise PermissionDenied
    docs = sv.documents(user.school)
    classes = list(_classes(user.school))
    turma = next((c for c in classes if c.pk == as_id(request.GET.get("turma"))), None)
    ctx = {"docs": docs, "classes": classes, "turma": turma}
    if turma:
        enrollments = list(sv.current_enrollments(user.school, turma))
        recs = sv.records([e.student_id for e in enrollments])
        lack = sv.missing([e.student_id for e in enrollments], docs, recs)
        ctx["rows"] = [{"s": e.student, "missing": len(lack.get(e.student_id, [])),
                        "cells": [{"d": d, "r": recs.get((e.student_id, d.pk))} for d in docs]} for e in enrollments]
    else:
        all_enr = list(sv.current_enrollments(user.school))
        lack = sv.missing(list({e.student_id for e in all_enr}), docs)
        summary = {}
        for e in all_enr:
            row = summary.setdefault(e.class_group_id, {"total": 0, "pending": 0})
            row["total"] += 1
            row["pending"] += e.student_id in lack
        ctx["summary"] = [{"c": c, **summary.get(c.pk, {"total": 0, "pending": 0})} for c in classes]
        ctx["pending_total"] = len(lack)
    q = (request.GET.get("q") or "").strip()[:60]
    if q:
        qs = Student.objects.filter(school=user.school, status="ativo")
        ctx["found"] = list((qs.filter(code=q) if digits(q) else qs.filter(name_q(q)))
                            .order_by("first_name", "last_name")[:15])
    ctx["q"] = q
    return render(request, "paperwork/index.html", ctx)


@require_POST
def save_class(request, class_id):
    """Grava a turma inteira de uma vez: marcado = entregue hoje; desmarcado = volta a faltar.
    Dispensas não mudam por aqui (só na página do estudante, com o motivo)."""
    user = request.user
    if not sv.can_manage(user):
        raise PermissionDenied
    turma = get_object_or_404(ClassGroup, pk=class_id, school=user.school)
    docs = sv.documents(user.school)
    enrollments = list(sv.current_enrollments(user.school, turma))
    recs = sv.records([e.student_id for e in enrollments])
    today = timezone.localdate()
    added = removed = 0
    for e in enrollments:
        for d in docs:
            r = recs.get((e.student_id, d.pk))
            checked = request.POST.get(f"d_{e.student_id}_{d.pk}") == "on"
            if checked and r is None:
                StudentDocument.objects.create(student=e.student, document=d, on=today, registered_by=user)
                added += 1
            elif not checked and r is not None and r.status == StudentDocument.Status.DELIVERED:
                r.delete()
                removed += 1
    if added or removed:
        create_audit_log(user=user, action="update", request=request, target=turma,
                         detail=f"Documentos da matrícula da turma {turma.name}: {added} entregue(s), "
                                f"{removed} desmarcado(s)")
    messages.success(request, f"Salvo: {added} documento{'s' if added != 1 else ''} entregue"
                              f"{'s' if added != 1 else ''}" + (f", {removed} desmarcado{'s' if removed != 1 else ''}"
                                                               if removed else "") + ".")
    return redirect(f"{_index_url()}?turma={turma.pk}")


def student_page(request, student_id):
    user = request.user
    if not sv.can_manage(user):
        raise PermissionDenied
    student = get_object_or_404(Student, pk=student_id, school=user.school)
    docs = sv.documents(user.school)
    if request.method == "POST":
        doc = next((d for d in docs if d.pk == as_id(request.POST.get("documento"))), None)
        action = request.POST.get("acao")
        note = (request.POST.get("obs") or "").strip()[:200]
        if doc is None or action not in ("entregar", "dispensar", "desfazer"):
            messages.error(request, "Escolha o documento.")
            return redirect("paperwork:student", student_id=student.pk)
        if action == "dispensar" and not note:
            messages.error(request, f"Para dispensar “{doc.name}”, diga o motivo.")
            return redirect("paperwork:student", student_id=student.pk)
        if action == "desfazer":
            StudentDocument.objects.filter(student=student, document=doc).delete()
            detail = f"Desfez o registro de “{doc.name}” de {student}"
        else:
            on = _date(request.POST.get("em"))
            StudentDocument.objects.update_or_create(student=student, document=doc, defaults={
                "status": StudentDocument.Status.DELIVERED if action == "entregar" else StudentDocument.Status.WAIVED,
                "on": on, "note": note, "registered_by": user})
            detail = f"{'Recebeu' if action == 'entregar' else 'Dispensou'} “{doc.name}” de {student}" + (
                f": {note}" if note else "")
        create_audit_log(user=user, action="update", request=request, target=student, detail=detail)
        messages.success(request, "Registrado.")
        return redirect("paperwork:student", student_id=student.pk)
    recs = sv.records([student.pk])
    return render(request, "paperwork/student.html", {
        "student": student, "today": timezone.localdate(),
        "items": [{"d": d, "r": recs.get((student.pk, d.pk))} for d in docs]})


def _date(raw):
    try:
        day = datetime.date.fromisoformat((raw or "")[:10])
    except ValueError:
        return timezone.localdate()
    today = timezone.localdate()
    return day if datetime.date(2000, 1, 1) <= day <= today else today


def settings_page(request, pk=None):
    user = request.user
    if not sv.can_manage(user):
        raise PermissionDenied
    sv.documents(user.school)
    doc = get_object_or_404(RequiredDocument, pk=pk, school=user.school) if pk else None
    form = DocumentForm(request.POST or None, instance=doc,
                        initial=None if doc else {"position": RequiredDocument.objects.filter(
                            school=user.school).count(), "mandatory": True, "active": True})
    if request.method == "POST" and form.is_valid():
        d = form.save(commit=False)
        d.school = user.school
        d.save()
        create_audit_log(user=user, action="update" if doc else "create", request=request, target=d,
                         detail=f"{'Alterou' if doc else 'Incluiu'} o documento da matrícula “{d.name}”")
        messages.success(request, "Lista de documentos atualizada.")
        return redirect("paperwork:settings")
    return render(request, "paperwork/settings.html", {
        "form": form, "doc": doc, "docs": RequiredDocument.objects.filter(school=user.school)})


@require_POST
def remind(request):
    user = request.user
    if not sv.can_manage(user):
        raise PermissionDenied
    turma = _classes(user.school).filter(pk=as_id(request.POST.get("turma"))).first()
    n = sv.remind(user.school, list(sv.current_enrollments(user.school, turma)))
    create_audit_log(user=user, action="update", request=request, target=turma,
                     detail=f"Lembrou as famílias dos documentos da matrícula ({turma.name if turma else 'todas as turmas'})"
                            f": {n} aviso(s)")
    messages.success(request, f"{n} aviso{'s' if n != 1 else ''} enviado{'s' if n != 1 else ''}." if n else
                     "Ninguém para avisar (ou as famílias já foram avisadas hoje).")
    return redirect(f"{_index_url()}?turma={turma.pk}" if turma else _index_url())


def _index_url():
    from django.urls import reverse

    return reverse("paperwork:index")


def export_csv(request):
    user = request.user
    if not sv.can_manage(user):
        raise PermissionDenied
    docs = sv.documents(user.school)
    enrollments = list(sv.current_enrollments(user.school))
    lack = sv.missing([e.student_id for e in enrollments], docs)
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="documentos-pendentes-{timezone.localdate():%Y%m%d}.csv"'
    resp.write("﻿")
    w = csv.writer(resp, delimiter=";")
    w.writerow(["Turma", "Estudante", "Código", "Falta entregar"])
    for e in sorted(enrollments, key=lambda e: (e.class_group.name, e.student.full_name)):
        if e.student_id in lack:
            w.writerow([_csv_safe(x) for x in (e.class_group.name, e.student.full_name, e.student.code or "",
                                               "; ".join(d.name for d in lack[e.student_id]))])
    create_audit_log(user=user, action="export", request=request, target=None,
                     detail="Exportou os documentos da matrícula pendentes")
    return resp
