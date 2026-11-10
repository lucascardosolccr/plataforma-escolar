"""Telas da confirmação de rematrícula. As regras de quem pode o quê estão em ``services``."""

import csv

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from apps.analytics.views import _csv_safe
from apps.core.models import create_audit_log
from apps.core.params import as_id
from apps.registry.models import Student

from . import services as sv
from .forms import AnswerForm, CampaignForm
from .models import Answer, Campaign

FILTERS = [("", "Todos"), ("continua", "Vão continuar"), ("sai", "Não vão continuar"), ("pendente", "Sem resposta"),
           ("cadastro", "Cadastro a atualizar")]


def _campaign(user, pk):
    if not sv.can_view(user):
        raise PermissionDenied
    return get_object_or_404(Campaign, pk=pk, school=user.school)


def index(request):
    user = request.user
    today = timezone.localdate()
    if sv.can_view(user):
        campaigns = list(Campaign.objects.filter(school=user.school).select_related("target_year"))
        rows = [{"c": c, "state": c.state(today), "stats": sv.stats(c)} for c in campaigns]
        return render(request, "reenroll/index.html", {"staff": True, "rows": rows, "manage": sv.can_manage(user),
                                                       "data_pending": sv.pending_data_updates(user.school)})
    if not user.school_id or user.role != "responsavel":
        raise PermissionDenied
    from apps.reenroll.models import Answer as A

    past = (A.objects.filter(student__in=sv.guardian_children(user)).select_related("campaign", "student")
            .order_by("-answered_at")[:20])
    return render(request, "reenroll/index.html", {
        "staff": False, "open": sv.family_rows(user, today),
        "past": [{"a": a, "code": sv.receipt_code(a)} for a in past]})


def campaign_form(request, pk=None):
    user = request.user
    if not sv.can_manage(user):
        raise PermissionDenied
    campaign = get_object_or_404(Campaign, pk=pk, school=user.school) if pk else None
    form = CampaignForm(request.POST or None, instance=campaign, school=user.school)
    if request.method == "POST" and form.is_valid():
        c = form.save(commit=False)
        if not campaign:
            c.school, c.created_by = user.school, user
        c.save()
        form.save_m2m()
        create_audit_log(user=user, action="update" if campaign else "create", request=request, target=c,
                         detail=f"{'Editou' if campaign else 'Abriu'} a campanha “{c.title}” (prazo {c.deadline:%d/%m/%Y})")
        if c.is_open(timezone.localdate()) and not c.announced_at:
            n = sv.announce(c)
            messages.success(request, f"Campanha aberta. {n} família{'s' if n != 1 else ''} avisada{'s' if n != 1 else ''}.")
        else:
            messages.success(request, "Campanha salva." + ("" if c.announced_at else
                                                           " As famílias são avisadas no dia do início."))
        return redirect("reenroll:detail", pk=c.pk)
    return render(request, "reenroll/campaign_form.html", {"form": form, "campaign": campaign})


def detail(request, pk):
    user = request.user
    c = _campaign(user, pk)
    today = timezone.localdate()
    enrollments = list(sv.scope_enrollments(c))
    answers = {a.student_id: a for a in c.answers.select_related("answered_by")}
    classes = sorted({e.class_group for e in enrollments}, key=lambda cg: cg.name)
    turma = as_id(request.GET.get("turma"))
    show = request.GET.get("ver", "")
    rows = []
    for e in enrollments:
        a = answers.get(e.student_id)
        if turma and e.class_group_id != turma:
            continue
        if (show == "pendente" and a) or (show in ("continua", "sai") and (not a or a.decision != show)) or (
                show == "cadastro" and not (a and a.data_changes and not a.data_done)):
            continue
        rows.append({"e": e, "a": a, "intact": sv.intact(a) if a else True})
    return render(request, "reenroll/detail.html", {
        "c": c, "state": c.state(today), "stats": sv.stats(c), "rows": rows, "classes": classes, "turma": turma,
        "show": show, "filters": FILTERS, "manage": sv.can_manage(user), "is_open": c.is_open(today),
        "reasons": _reasons(c)})


def _reasons(c):
    counts = {}
    for a in c.answers.filter(decision=Answer.Decision.LEAVE):
        counts[a.get_reason_display() or "Sem motivo"] = counts.get(a.get_reason_display() or "Sem motivo", 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])


def _answer_page(request, c, student, in_person):
    current = Answer.objects.filter(campaign=c, student=student).first()
    initial = {}
    if current:
        initial = {"decision": current.decision, "reason": current.reason, "reason_text": current.reason_text,
                   "data_changes": current.data_changes, "data_ok": not current.data_changes,
                   "accept": current.accepted_terms}
    form = AnswerForm(request.POST or None, initial=initial, terms=bool(c.terms), in_person=in_person)
    if request.method == "POST" and form.is_valid():
        a = sv.record(request, c, student, form.cleaned_data, in_person=in_person)
        if in_person:
            messages.success(request, f"Resposta de {student.first_name} registrada: "
                                      f"{a.get_decision_display().lower()}. Comprovante {sv.receipt_code(a)}.")
            return redirect("reenroll:detail", pk=c.pk)
        return redirect(f"{request.path}?estudante={student.pk}")  # a página mostra a resposta e o comprovante
    profile = getattr(request.user, "guardian_profile", None) if not in_person else None
    return render(request, "reenroll/answer.html", {
        "c": c, "student": student, "form": form, "current": current, "in_person": in_person, "profile": profile,
        "code": sv.receipt_code(current) if current else "", "cls": sv.scope_enrollments(c).filter(
            student=student).first()})


def answer(request, pk):
    """A família responde por um filho (``?estudante=``), enquanto a campanha estiver aberta."""
    user = request.user
    c = get_object_or_404(Campaign, pk=pk, school=user.school) if user.school_id else None
    if not c or user.role != "responsavel":
        raise PermissionDenied
    kids = sv.guardian_children(user)
    sid = as_id(request.GET.get("estudante") or request.POST.get("estudante"))
    student = next((s for s in kids if s.pk == sid), None)
    if not student or not sv.in_scope(c, student):
        raise Http404
    if not c.is_open(timezone.localdate()):
        messages.info(request, "O prazo desta campanha terminou. Para mudar a resposta, fale com a secretaria.")
        return redirect("reenroll:index")
    return _answer_page(request, c, student, in_person=False)


def answer_in_person(request, pk, student_id):
    """A secretaria registra a resposta de quem veio ao balcão (ou não tem conta). Vale também depois do prazo."""
    user = request.user
    if not sv.can_manage(user):
        raise PermissionDenied
    c = get_object_or_404(Campaign, pk=pk, school=user.school)
    student = get_object_or_404(Student, pk=student_id, school=user.school)
    if not sv.in_scope(c, student):
        raise Http404
    return _answer_page(request, c, student, in_person=True)


@require_POST
def remind_now(request, pk):
    user = request.user
    if not sv.can_manage(user):
        raise PermissionDenied
    c = get_object_or_404(Campaign, pk=pk, school=user.school)
    if not c.is_open(timezone.localdate()):
        messages.error(request, "A campanha não está aberta.")
        return redirect("reenroll:detail", pk=c.pk)
    n = sv.remind(c)
    create_audit_log(user=user, action="update", request=request, target=c,
                     detail=f"Lembrou {n} família(s) sem resposta na campanha “{c.title}”")
    messages.success(request, f"Lembrete enviado a {n} família{'s' if n != 1 else ''}." if n else
                     "Ninguém para lembrar hoje (ou o lembrete de hoje já foi enviado).")
    return redirect("reenroll:detail", pk=c.pk)


@require_POST
def toggle_closed(request, pk):
    user = request.user
    if not sv.can_manage(user):
        raise PermissionDenied
    c = get_object_or_404(Campaign, pk=pk, school=user.school)
    c.closed = not c.closed
    c.save(update_fields=["closed"])
    create_audit_log(user=user, action="update", request=request, target=c,
                     detail=f"{'Encerrou' if c.closed else 'Reabriu'} a campanha “{c.title}”")
    messages.success(request, "Campanha encerrada: as famílias não respondem mais pela plataforma." if c.closed else
                     "Campanha reaberta até o prazo.")
    return redirect("reenroll:detail", pk=c.pk)


@require_POST
def data_done(request, pk):
    user = request.user
    if not sv.can_manage(user):
        raise PermissionDenied
    a = get_object_or_404(Answer, pk=pk, campaign__school=user.school)
    a.data_done, a.data_done_by = True, user
    a.save(update_fields=["data_done", "data_done_by"])  # fora do selo: é anotação da secretaria
    create_audit_log(user=user, action="update", request=request, target=a,
                     detail=f"Atualizou o cadastro de {a.student} conforme a rematrícula")
    messages.success(request, f"Cadastro de {a.student.first_name} marcado como atualizado.")
    return redirect(f"{a.campaign.get_absolute_url()}?ver=cadastro")


def export_csv(request, pk):
    user = request.user
    if not sv.can_manage(user):
        raise PermissionDenied
    c = get_object_or_404(Campaign, pk=pk, school=user.school)
    answers = {a.student_id: a for a in c.answers.all()}
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{slugify(c.title)}-{timezone.localdate():%Y%m%d}.csv"'
    resp.write("﻿")
    w = csv.writer(resp, delimiter=";")
    w.writerow(["Turma", "Estudante", "Código", "Resposta", "Motivo", "Comentário", "Mudanças no cadastro",
                "Cadastro atualizado", "Respondido por", "No balcão", "Data", "Comprovante"])
    for e in sv.scope_enrollments(c):
        a = answers.get(e.student_id)
        w.writerow([_csv_safe(x) for x in (
            e.class_group.name, e.student.full_name, e.student.code or "",
            a.get_decision_display() if a else "Sem resposta", a.get_reason_display() if a else "",
            a.reason_text if a else "", a.data_changes if a else "", ("sim" if a.data_done else "não") if a else "",
            a.answered_by_name if a else "", ("sim" if a.in_person else "não") if a else "",
            timezone.localtime(a.answered_at).strftime("%d/%m/%Y %H:%M") if a else "",
            sv.receipt_code(a) if a else "")])
    create_audit_log(user=user, action="export", request=request, target=c,
                     detail=f"Exportou as respostas da campanha “{c.title}”")
    return resp
