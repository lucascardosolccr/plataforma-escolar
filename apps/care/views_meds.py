"""Remédio na escola: a família pede, a secretaria confere a receita e autoriza, a equipe registra cada dose e a
família recebe um aviso a cada uma (inclusive quando não foi dado).

Quem vê e quem faz está em ``access`` (``can_view_medication``, ``can_give_medication``, ``can_review_medication``).
O professor não vê: como os remédios da ficha de saúde, é assunto da família com a secretaria.
"""

import datetime
import re

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.models import Role, User, create_audit_log
from apps.registry.models import Student

from . import access
from .models import HealthRecord, MedicationDose, MedicationRequest

#: Horários aceitos: o dia escolar, inclusive o integral.
FIRST, LAST = datetime.time(6, 0), datetime.time(19, 0)
#: Depois de quantos minutos um horário sem registro aparece como atrasado.
LATE_AFTER = 30
#: Quem registrou uma dose pode desfazer nesse prazo (clicou no estudante errado).
UNDO_MINUTES = 10

_TIME = re.compile(r"^(\d{1,2})(?:\s*(?:h|:)\s*(\d{2})?)?\s*(?:h)?$", re.IGNORECASE)


def parse_times(text):
    """"10h, 14:30 e 9" -> ["09:00", "10:00", "14:30"]. Erro de validação para o que não for horário."""
    parts = [p.strip() for p in re.split(r"[,;/]|\se\s", text or "") if p.strip()]
    found = set()
    for p in parts:
        m = _TIME.match(p)
        if not m:
            raise forms.ValidationError(f"“{p}” não é um horário. Escreva como 10:00 ou 10h30.")
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        if h > 23 or mi > 59:
            raise forms.ValidationError(f"“{p}” não é um horário.")
        t = datetime.time(h, mi)
        if not FIRST <= t <= LAST:
            raise forms.ValidationError(f"{t:%H:%M} está fora do horário da escola ({FIRST:%H:%M} às {LAST:%H:%M}). "
                                        "Os outros horários ficam com a família.")
        found.add(f"{t:%H:%M}")
    if not found:
        raise forms.ValidationError("Informe pelo menos um horário.")
    if len(found) > 6:
        raise forms.ValidationError("No máximo 6 horários por dia.")
    return sorted(found)


class MedicationForm(forms.ModelForm):
    authorize = forms.BooleanField(
        label="Autorizo a escola a dar este remédio ao meu filho, na dose e nos horários acima, conforme a receita. "
              "Vou entregar na secretaria a receita (original ou cópia) e o remédio na embalagem, com o nome dele.",
        required=True)

    class Meta:
        model = MedicationRequest
        fields = ["medicine", "dose", "times", "start_date", "end_date", "reason", "instructions", "prescriber",
                  "prescription_date"]
        widgets = {f: forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
                   for f in ("start_date", "end_date", "prescription_date")}

    def clean_times(self):
        return ", ".join(parse_times(self.cleaned_data.get("times")))

    def clean(self):
        data = super().clean()
        today = timezone.localdate()
        start, end, rx = data.get("start_date"), data.get("end_date"), data.get("prescription_date")
        if start and start < today:
            self.add_error("start_date", "Não pode ser antes de hoje.")
        if start and start > today + datetime.timedelta(days=60):
            self.add_error("start_date", "Peça no máximo 60 dias antes.")
        if start and end and end < start:
            self.add_error("end_date", "O último dia vem depois do primeiro.")
        if start and end and (end - start).days > 366:
            self.add_error("end_date", "No máximo um ano. Depois, faça um pedido novo com a receita atualizada.")
        if rx and rx > today:
            self.add_error("prescription_date", "A receita não pode ter data futura.")
        if rx and rx < today - datetime.timedelta(days=366):
            self.add_error("prescription_date", "Receita com mais de um ano: peça uma atualizada ao médico.")
        return data


class ReviewForm(forms.Form):
    decision = forms.ChoiceField(label="Decisão", choices=[("aprovar", "Autorizar"), ("recusar", "Não autorizar")],
                                 widget=forms.RadioSelect)
    checked = forms.BooleanField(label="Conferi a receita e o remédio entregues pela família (nome, dose e horários "
                                       "batem com o pedido).", required=False)
    note = forms.CharField(label="Observação para a família", max_length=300, required=False,
                           help_text="Obrigatória para não autorizar. Ex.: a receita não chegou; a dose não confere.")

    def clean(self):
        data = super().clean()
        if data.get("decision") == "aprovar" and not data.get("checked"):
            self.add_error("checked", "Só autorize depois de conferir a receita e o remédio.")
        if data.get("decision") == "recusar" and not (data.get("note") or "").strip():
            self.add_error("note", "Diga à família o motivo.")
        return data


def _student(user, student_id):
    if not user.school_id:
        raise PermissionDenied
    return get_object_or_404(Student, pk=student_id, school=user.school)


def _request(user, pk):
    req = get_object_or_404(MedicationRequest.objects.select_related("student", "requested_by", "reviewed_by"),
                            pk=pk, school=user.school) if user.school_id else None
    if not req or not access.can_view_medication(user, req.student):
        raise PermissionDenied
    return req


def _office_users(school):
    return User.objects.filter(school=school, is_active=True, role__in=access.OFFICE)


def _tell_family(req, key_suffix, title, body, high=False):
    from apps.communication.family_events import notify_family
    from apps.communication.models import Notification

    return notify_family(req.student, "medicamento", title, body=body,
                         url=reverse("care:medication", args=[req.pk]), include_student=False,
                         dedupe_key=f"medicamento:{req.pk}:{key_suffix}",
                         priority=Notification.Priority.HIGH if high else Notification.Priority.NORMAL)


def medication_list(request):
    user = request.user
    if not user.school_id:
        raise PermissionDenied
    qs = MedicationRequest.objects.filter(school=user.school).select_related("student")
    if user.role == Role.RESPONSAVEL.value:
        from .views import _children

        kids = _children(user)
        return render(request, "care/medications.html", {
            "family": True, "kids": kids, "requests": qs.filter(student__in=kids)[:50]})
    if user.role not in access.TEAM:
        raise PermissionDenied
    if user.role == Role.COORDENACAO.value:
        from .views_incidents import _reachable_students

        qs = qs.filter(student__in=_reachable_students(user))
    today = timezone.localdate()
    return render(request, "care/medications.html", {
        "family": False, "pending": qs.filter(status=MedicationRequest.Status.PENDING),
        "active": qs.filter(status=MedicationRequest.Status.APPROVED, end_date__gte=today).order_by("student__first_name"),
        "late": len([r for r in schedule(user, today) if r["late"]]),
        "can_review": user.role in access.OFFICE})


def medication_create(request, student_id):
    from apps.registry.access import guardian_of

    user = request.user
    student = _student(user, student_id)
    if not guardian_of(user, student):
        raise PermissionDenied
    form = MedicationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        req = form.save(commit=False)
        req.school, req.student, req.requested_by = user.school, student, user
        req.save()
        create_audit_log(user=user, action="create", request=request, target=req,
                         detail=f"Pediu que a escola dê {req.medicine} a {student} às {req.times} "
                                f"({req.start_date:%d/%m/%Y} a {req.end_date:%d/%m/%Y}), com autorização")
        from apps.communication.models import Notification
        from apps.communication.services import notify_many

        notify_many(user.school, _office_users(user.school), Notification.Kind.HEALTH,
                    f"Pedido de remédio na escola: {student.first_name}",
                    body=f"{req.medicine}, {req.dose}, às {req.times}, a partir de {req.start_date:%d/%m}. Confira a "
                         "receita e o remédio antes de autorizar.",
                    url=reverse("care:medication", args=[req.pk]), student=student, dedupe_key=f"medpedido:{req.pk}")
        messages.success(request, "Pedido enviado. Entregue a receita e o remédio na secretaria: a escola só dá "
                                  "depois de conferir, e você recebe um aviso quando for autorizado.")
        return redirect("care:medication", pk=req.pk)
    record = HealthRecord.objects.filter(student=student).first()
    return render(request, "care/medication_form.html", {"form": form, "student": student, "record": record})


def medication_detail(request, pk):
    user = request.user
    req = _request(user, pk)
    family = user.role == Role.RESPONSAVEL.value
    if not family:
        create_audit_log(user=user, action="view", request=request, target=req,
                         detail=f"Consultou o pedido de remédio de {req.student}")
    review = None
    if req.status == MedicationRequest.Status.PENDING and access.can_review_medication(user, req.student):
        review = ReviewForm()
    return render(request, "care/medication_detail.html", {
        "req": req, "family": family, "review": review,
        "doses": req.doses.select_related("given_by")[:120],
        "record": HealthRecord.objects.filter(student=req.student).first() if not family else None,
        "can_end": req.status in (MedicationRequest.Status.PENDING, MedicationRequest.Status.APPROVED) and (
            family or access.can_review_medication(user, req.student))})


@require_POST
def medication_review(request, pk):
    user = request.user
    req = _request(user, pk)
    if not access.can_review_medication(user, req.student):
        raise PermissionDenied
    if req.status != MedicationRequest.Status.PENDING:
        messages.info(request, "Este pedido já foi analisado.")
        return redirect("care:medication", pk=req.pk)
    form = ReviewForm(request.POST)
    if not form.is_valid():
        return render(request, "care/medication_detail.html", {
            "req": req, "family": False, "review": form, "doses": [],
            "record": HealthRecord.objects.filter(student=req.student).first(), "can_end": True})
    approve = form.cleaned_data["decision"] == "aprovar"
    req.status = MedicationRequest.Status.APPROVED if approve else MedicationRequest.Status.REFUSED
    req.reviewed_by, req.reviewed_at = user, timezone.now()
    req.review_note = form.cleaned_data["note"].strip()
    req.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note"])
    create_audit_log(user=user, action="update", request=request, target=req,
                     detail=f"{'Autorizou' if approve else 'Não autorizou'} {req.medicine} para {req.student}"
                            + (" (receita conferida)" if approve else f": {req.review_note}"))
    first = req.student.first_name
    if approve:
        _tell_family(req, "autorizado", f"Remédio autorizado na escola: {first}",
                     f"{req.medicine}, {req.dose}, às {req.times}, de {req.start_date:%d/%m} a {req.end_date:%d/%m}. "
                     "Você recebe um aviso a cada dose." + (f" {req.review_note}" if req.review_note else ""))
    else:
        _tell_family(req, "recusado", f"Remédio não autorizado: {first}",
                     f"{req.medicine}. Motivo: {req.review_note}", high=True)
    messages.success(request, "Pedido autorizado: aparece em Remédios de hoje." if approve else
                     "Pedido não autorizado. A família foi avisada com o motivo.")
    return redirect("care:medication", pk=req.pk)


@require_POST
def medication_end(request, pk):
    user = request.user
    req = _request(user, pk)
    family = user.role == Role.RESPONSAVEL.value
    if not (family or access.can_review_medication(user, req.student)):
        raise PermissionDenied
    if req.status in (MedicationRequest.Status.PENDING, MedicationRequest.Status.APPROVED):
        req.status, req.ended_by, req.ended_at = MedicationRequest.Status.ENDED, user, timezone.now()
        req.save(update_fields=["status", "ended_by", "ended_at"])
        create_audit_log(user=user, action="update", request=request, target=req,
                         detail=f"Encerrou o remédio {req.medicine} de {req.student}")
        if family:
            from apps.communication.models import Notification
            from apps.communication.services import notify_many

            notify_many(user.school, _office_users(user.school), Notification.Kind.HEALTH,
                        f"A família encerrou o remédio de {req.student.first_name}",
                        body=f"{req.medicine}: não dar mais. Devolva o que sobrou à família.",
                        url=reverse("care:medication", args=[req.pk]), student=req.student,
                        dedupe_key=f"medfim:{req.pk}")
        else:
            _tell_family(req, "encerrado", f"Remédio encerrado na escola: {req.student.first_name}",
                         f"{req.medicine}: a escola não vai mais dar. Busque o que sobrou na secretaria.")
        messages.success(request, "Encerrado: a escola não dá mais este remédio.")
    return redirect("care:medication", pk=req.pk)


def schedule(user, day):
    """Os horários de remédio do dia que esta pessoa alcança, com a dose registrada (ou atrasada)."""
    qs = MedicationRequest.objects.filter(school=user.school, status=MedicationRequest.Status.APPROVED,
                                          start_date__lte=day, end_date__gte=day,
                                          student__status="ativo").select_related("student")
    if user.role == Role.COORDENACAO.value:
        from .views_incidents import _reachable_students

        qs = qs.filter(student__in=_reachable_students(user))
    reqs = list(qs)
    doses = {(d.request_id, d.slot): d for d in
             MedicationDose.objects.filter(request__in=reqs, day=day).select_related("given_by")}
    now = timezone.localtime()
    school_day = day.weekday() < 5
    rows = []
    for r in reqs:
        for slot in r.time_list():
            d = doses.get((r.pk, slot))
            due = timezone.make_aware(datetime.datetime.combine(day, datetime.time.fromisoformat(slot)))
            rows.append({"req": r, "slot": slot, "dose": d,
                         "late": not d and school_day and day == now.date()
                         and now > due + datetime.timedelta(minutes=LATE_AFTER),
                         "undo": d and d.given_by_id == user.pk
                         and timezone.now() - d.given_at < datetime.timedelta(minutes=UNDO_MINUTES)})
    rows.sort(key=lambda x: (x["slot"], x["req"].student.first_name, x["req"].student.last_name))
    return rows


def medication_today(request):
    user = request.user
    if not user.school_id or user.role not in access.TEAM:
        raise PermissionDenied
    today = timezone.localdate()
    rows = schedule(user, today)
    records = {h.student_id: h for h in HealthRecord.objects.filter(
        student_id__in={r["req"].student_id for r in rows})}
    for r in rows:
        r["record"] = records.get(r["req"].student_id)
    return render(request, "care/medication_today.html", {
        "rows": rows, "today": today, "results": MedicationDose.Result.choices,
        "late": sum(1 for r in rows if r["late"]), "done": sum(1 for r in rows if r["dose"])})


@require_POST
def medication_dose(request, pk):
    user = request.user
    req = get_object_or_404(MedicationRequest.objects.select_related("student"), pk=pk, school=user.school) \
        if user.school_id else None
    if not req or not access.can_give_medication(user, req.student):
        raise PermissionDenied
    today = timezone.localdate()
    slot = (request.POST.get("slot") or "")[:5]
    result = request.POST.get("result") or ""
    note = (request.POST.get("note") or "").strip()[:200]
    back = redirect("care:medication_today")
    if not req.active_on(today) or slot not in req.time_list() or result not in MedicationDose.Result.values:
        messages.error(request, "Este horário não está autorizado para hoje.")
        return back
    if result == MedicationDose.Result.NOT_GIVEN and not note:
        messages.error(request, f"Diga na observação por que o remédio de {req.student.first_name} não foi dado.")
        return back
    try:
        with transaction.atomic():
            dose = MedicationDose.objects.create(request=req, day=today, slot=slot, result=result, note=note,
                                                 given_by=user)
    except IntegrityError:
        messages.info(request, f"O horário das {slot} de {req.student.first_name} já foi registrado.")
        return back
    create_audit_log(user=user, action="create", request=request, target=req,
                     detail=f"Registrou a dose das {slot} de {req.medicine} para {req.student}: "
                            f"{dose.get_result_display().lower()}")
    first = req.student.first_name
    at = timezone.localtime(dose.given_at)
    who = user.get_full_name() or user.username
    extra = f" Observação: {note}" if note else ""
    if result == MedicationDose.Result.GIVEN:
        _tell_family(req, f"dose:{dose.pk}", f"{first} tomou o remédio na escola",
                     f"{req.medicine}, {req.dose}, às {at:%H:%M} (horário das {slot}). Quem deu: {who}.{extra}")
    else:
        _tell_family(req, f"dose:{dose.pk}", f"{first} não tomou o remédio das {slot}",
                     f"{req.medicine}: {dose.get_result_display().lower()}.{extra} Registrado por {who} às "
                     f"{at:%H:%M}.", high=True)
    messages.success(request, f"{first}, {slot}: {dose.get_result_display().lower()}. A família foi avisada.")
    return back


@require_POST
def medication_dose_undo(request, pk):
    """Desfaz um registro feito por engano, só por quem registrou e logo depois. A família é avisada."""
    user = request.user
    dose = get_object_or_404(MedicationDose.objects.select_related("request__student"), pk=pk,
                             request__school=user.school) if user.school_id else None
    if not dose or dose.given_by_id != user.pk:
        raise PermissionDenied
    if timezone.now() - dose.given_at >= datetime.timedelta(minutes=UNDO_MINUTES):
        messages.error(request, f"Passaram {UNDO_MINUTES} minutos: o registro fica. Se estiver errado, explique à "
                                "família e à direção.")
        return redirect("care:medication_today")
    req = dose.request
    create_audit_log(user=user, action="delete", request=request, target=req,
                     detail=f"Desfez o registro da dose das {dose.slot} de {req.medicine} para {req.student} "
                            f"({dose.get_result_display().lower()}), feito por engano")
    _tell_family(req, f"desfeito:{dose.pk}", f"Correção: registro do remédio de {req.student.first_name}",
                 f"O registro das {dose.slot} ({dose.get_result_display().lower()}) foi feito por engano e foi "
                 "desfeito. A escola vai registrar o certo em seguida.")
    dose.delete()
    messages.success(request, "Registro desfeito. Registre o horário certo.")
    return redirect("care:medication_today")


def pending_requests(user):
    if user.role not in access.OFFICE or not user.school_id:
        return 0
    return MedicationRequest.objects.filter(school=user.school, status=MedicationRequest.Status.PENDING).count()


def late_doses(user):
    if user.role not in access.TEAM or not user.school_id:
        return 0
    return sum(1 for r in schedule(user, timezone.localdate()) if r["late"])
