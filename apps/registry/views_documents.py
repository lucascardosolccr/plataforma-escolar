"""Declarações da secretaria: matrícula e frequência, com número e código de verificação.

Antes, a secretaria redigia cada declaração num editor de texto e copiava os dados à mão. Aqui o texto
sai dos registros da plataforma, e as regras evitam declarar o que não está registrado:

- declaração de matrícula só com matrícula ativa;
- declaração de frequência só com chamada registrada no período, e diz quantos registros considerou;
- o texto emitido fica guardado como saiu (reimprimir mostra o mesmo texto) e cada emissão tem número
  sequencial por ano e um código de verificação;
- emitem a secretaria, a direção e a administração; tudo vai para a auditoria;
- se a declaração atende a uma solicitação da família, a solicitação é respondida e a família é avisada.

A plataforma não inventa dados da escola: o cabeçalho e quem assina vêm de ``DocumentSettings`` e,
vazios, aparecem como lacuna para preencher à mão.
"""

import secrets
from datetime import date

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.core.fmt import pct
from apps.core.models import Role, create_audit_log
from apps.core.pagination import paginate

from .models import DocumentSettings, Enrollment, IssuedDocument, Student

ISSUERS = (Role.SECRETARIA.value, Role.DIRECAO.value, Role.ADMIN.value)
MONTHS = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
          "novembro", "dezembro")
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
DATE = forms.DateInput(format=r"%Y-%m-%d", attrs={"type": "date"})


def can_issue(user):
    return user.is_authenticated and user.role in ISSUERS


def _require(user):
    if not can_issue(user):
        raise PermissionDenied


def long_date(d):
    return f"{d.day} de {MONTHS[d.month - 1]} de {d.year}"


def _br(d):
    return d.strftime("%d/%m/%Y")


def _born(student):
    return f", nascido(a) em {_br(student.birth_date)}," if student.birth_date else ","


def active_enrollment(student):
    return (Enrollment.objects.filter(student=student, status="ativo")
            .select_related("class_group", "school_year").order_by("-school_year__name").first())


def enrollment_text(student):
    e = active_enrollment(student)
    if e is None:
        return None, "Este estudante não tem matrícula ativa: a declaração de matrícula não pode ser emitida."
    cg = e.class_group
    serie = f" ({cg.grade})" if cg.grade else ""
    return (f"Declaramos, para os devidos fins, que {student.full_name}{_born(student)} está regularmente "
            f"matriculado(a) nesta instituição de ensino no ano letivo de {e.school_year.name}, na turma "
            f"{cg.name}{serie}, turno {cg.get_turn_display().lower()}."), None


def attendance_text(student, start, end):
    from apps.analytics.bi import attendance_summary
    from apps.pedagogy.models import AttendanceRecord

    records = list(AttendanceRecord.objects.filter(student=student, date__gte=start, date__lte=end)
                   .order_by("date").values_list("date", "status"))
    if not records:
        return None, "Não há chamada registrada para este estudante no período: a frequência não pode ser declarada."
    s = attendance_summary(records, None)
    faltas = f"{s['absent']} falta{'s' if s['absent'] != 1 else ''}"
    return (f"Declaramos, para os devidos fins, que {student.full_name}{_born(student)} esteve presente em "
            f"{pct(s['percent'])} dos {s['total']} registros de chamada desta instituição no período de "
            f"{_br(start)} a {_br(end)} ({faltas}; atrasos contam como presença)."), None


class DocumentForm(forms.Form):
    kind = forms.ChoiceField(label="Tipo", choices=IssuedDocument.Kind.choices)
    purpose = forms.CharField(label="Finalidade (opcional)", max_length=120, required=False,
                              help_text="Ex.: comprovação junto a programa social, trabalho do responsável, transporte.")
    start = forms.DateField(label="Frequência desde", required=False, widget=DATE,
                            help_text="Só para a declaração de frequência.")
    end = forms.DateField(label="Frequência até", required=False, widget=DATE)

    def clean(self):
        c = super().clean()
        if c.get("kind") == IssuedDocument.Kind.ATTENDANCE:
            if not c.get("start") or not c.get("end"):
                raise forms.ValidationError("Informe o período da frequência.")
            if c["start"] > c["end"]:
                raise forms.ValidationError("A data inicial é depois da final.")
            if c["end"] > timezone.localdate():
                self.add_error("end", "Não dá para declarar frequência de dias que ainda não passaram.")
        return c


def _new_code():
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def _issue(user, student, kind, body, purpose, start, end, req):
    year = timezone.localdate().year
    for _ in range(5):  # corrida entre duas emissões simultâneas: tenta o próximo número
        try:
            with transaction.atomic():
                last = (IssuedDocument.objects.filter(school=user.school, year=year)
                        .aggregate(m=Max("sequence"))["m"] or 0)
                return IssuedDocument.objects.create(
                    school=user.school, student=student, kind=kind, year=year, sequence=last + 1, code=_new_code(),
                    purpose=purpose, period_start=start, period_end=end, body=body, issued_by=user, request=req)
        except IntegrityError:
            continue
    raise IntegrityError("Não foi possível numerar a declaração.")


def document_new(request, student_id):
    user = request.user
    _require(user)
    student = get_object_or_404(Student, pk=student_id, school=user.school)
    req = None
    if request.GET.get("solicitacao", "").isdigit() or request.POST.get("solicitacao", "").isdigit():
        from apps.communication.models import ServiceRequest

        rid = int(request.GET.get("solicitacao") or request.POST.get("solicitacao"))
        req = ServiceRequest.objects.filter(pk=rid, school=user.school, student=student).first()
    today = timezone.localdate()
    year_start = date(today.year, 1, 1)
    form = DocumentForm(request.POST or None, initial={"start": year_start, "end": today})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        if d["kind"] == IssuedDocument.Kind.ENROLLMENT:
            body, error = enrollment_text(student)
            start = end = None
        else:
            start, end = d["start"], d["end"]
            body, error = attendance_text(student, start, end)
        if error:
            form.add_error(None, error)
        else:
            purpose = d["purpose"].strip()
            if purpose:
                body += f" Esta declaração destina-se a {purpose[0].lower() + purpose[1:]}."
            doc = _issue(user, student, d["kind"], body, purpose, start, end, req)
            create_audit_log(user=user, action="create", request=request, target=doc,
                             detail=f"Emitiu {doc} para {student.full_name}")
            if req is not None:
                from apps.communication.services import notify_request_resolved

                req.status = req.Status.RESPONDED
                req.response = (f"{doc.get_kind_display()} nº {doc.number} emitida em {_br(today)}. "
                                "Retire na secretaria.")
                req.responded_by, req.responded_at = user, timezone.now()
                req.save()
                notify_request_resolved(req)
            messages.success(request, f"{doc} emitida. Imprima e assine.")
            return redirect("document_print", pk=doc.pk)
    else:
        kind = request.GET.get("tipo")
        if kind in IssuedDocument.Kind.values:
            form.initial["kind"] = kind
    return render(request, "registry/document_form.html", {
        "student": student, "form": form, "req": req, "enrollment": active_enrollment(student),
        "settings_missing": not DocumentSettings.for_school(user.school).pk,
    })


def document_print(request, pk):
    user = request.user
    _require(user)
    doc = get_object_or_404(IssuedDocument.objects.select_related("student", "issued_by"), pk=pk, school=user.school)
    create_audit_log(user=user, action="view", request=request, target=doc, detail=f"Abriu {doc} para impressão")
    cfg = DocumentSettings.for_school(user.school)
    return render(request, "registry/document_print.html", {
        "doc": doc, "cfg": cfg, "header_lines": [ln for ln in cfg.header.splitlines() if ln.strip()],
        "when": long_date(timezone.localtime(doc.issued_at).date()),
    })


def document_list(request):
    user = request.user
    _require(user)
    qs = IssuedDocument.objects.filter(school=user.school).select_related("student", "issued_by")
    code = (request.GET.get("codigo") or "").strip().upper()
    found = None
    if code:
        found = qs.filter(code=code if "-" in code else f"{code[:4]}-{code[4:]}").first()
    student_id = request.GET.get("estudante", "")
    if student_id.isdigit():
        qs = qs.filter(student_id=int(student_id))
    return render(request, "registry/document_list.html", {
        "page": paginate(request, qs), "code": code, "found": found, "searched": bool(code),
    })


class DocumentSettingsForm(forms.ModelForm):
    class Meta:
        model = DocumentSettings
        fields = ["header", "city", "signer_name", "signer_role"]
        widgets = {"header": forms.Textarea(attrs={"rows": 4})}


def document_settings(request):
    user = request.user
    _require(user)
    cfg = DocumentSettings.for_school(user.school)
    form = DocumentSettingsForm(request.POST or None, instance=cfg)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.school = user.school
        obj.save()
        create_audit_log(user=user, action="update", request=request, target=obj,
                         detail="Atualizou os dados das declarações")
        messages.success(request, "Dados das declarações salvos.")
        return redirect("document_list")
    return render(request, "registry/document_settings.html", {"form": form})
