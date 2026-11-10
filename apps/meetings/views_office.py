"""Horários de atendimento: alguém da equipe abre horários (plantão de dúvidas, reunião de pais e mestres) e as
famílias das turmas escolhidas marcam um. Cada horário marcado vira uma reunião (``Meeting``) com quem atende e os
responsáveis do estudante, com o aviso, o lembrete na véspera e o registro que as reuniões já têm.

Regras, todas conferidas aqui no servidor:

- abrem horários: direção, coordenação, secretaria e professor; as turmas são só as do alcance de cada um (o
  professor, as suas; a coordenação restrita, as da designação);
- mantêm (editar, fechar, liberar um horário): quem atende e a direção;
- marcam: responsáveis com vínculo aprovado de um estudante com matrícula ativa numa das turmas, um horário por
  estudante em cada atendimento, até o horário começar. A família nunca vê o nome de quem marcou os outros horários.
"""

import datetime

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.academics.models import ClassGroup
from apps.core.models import Role, create_audit_log
from apps.registry.models import Enrollment, GuardianLink

from . import services
from .access import STAFF_ROLES
from .models import Meeting, OfficeHours, OfficeSlot

MAX_SLOTS = 48
DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
TIME = forms.TimeInput(attrs={"type": "time"}, format="%H:%M")


def reachable_classes(user):
    """Turmas do ano letivo atual no alcance de quem abre os horários."""
    qs = ClassGroup.objects.filter(school=user.school)
    current = qs.filter(school_year__is_current=True)
    if current.exists():
        qs = current
    if user.role == Role.PROFESSOR.value:
        from apps.academics.permissions import teacher_class_ids

        qs = qs.filter(pk__in=teacher_class_ids(user))
    elif user.role == Role.COORDENACAO.value:
        from apps.coordination.scope import class_scope

        scope = class_scope(user)
        if scope is not None:
            qs = qs.filter(pk__in=scope)
    return qs.order_by("name")


class OfficeHoursForm(forms.ModelForm):
    TIMING = ("day", "start", "end", "slot_minutes")

    class Meta:
        model = OfficeHours
        fields = ["title", "day", "start", "end", "slot_minutes", "location", "notes", "class_groups"]
        widgets = {"day": DATE, "start": TIME, "end": TIME, "notes": forms.Textarea(attrs={"rows": 3}),
                   "class_groups": forms.CheckboxSelectMultiple}

    def __init__(self, *args, user=None, locked=False, **kwargs):
        super().__init__(*args, **kwargs)
        classes = reachable_classes(user)
        if self.instance.pk:  # turmas já escolhidas continuam (mesmo se o alcance mudou)
            classes = ClassGroup.objects.filter(pk__in=classes) | self.instance.class_groups.all()
        self.fields["class_groups"].queryset = classes.distinct().order_by("name")
        self.locked = locked
        if locked:
            for name in self.TIMING:
                self.fields[name].disabled = True
                self.fields[name].help_text = "Já há horários marcados: para mudar o dia ou a hora, libere-os antes."

    def clean(self):
        data = super().clean()
        if self.locked:
            return data
        day, start, end, step = (data.get(k) for k in self.TIMING)
        today = timezone.localdate()
        if day and day < today:
            self.add_error("day", "Escolha hoje ou um dia futuro.")
        if day and day > today + datetime.timedelta(days=120):
            self.add_error("day", "No máximo quatro meses à frente.")
        if start and end and step:
            if end <= start:
                self.add_error("end", "O fim vem depois do início.")
            else:
                n = len(_times(start, end, step))
                if n == 0:
                    self.add_error("end", "Não cabe nenhuma conversa nesse intervalo.")
                elif n > MAX_SLOTS:
                    self.add_error("end", f"São {n} horários: no máximo {MAX_SLOTS}. Divida em dois dias.")
        return data


class BookingForm(forms.Form):
    student = forms.TypedChoiceField(label="Estudante", coerce=int)
    slot = forms.TypedChoiceField(label="Horário", coerce=int, widget=forms.RadioSelect)
    topic = forms.CharField(label="O que você quer conversar (opcional)", max_length=200, required=False,
                            help_text="Ajuda quem atende a se preparar. Ex.: notas de Matemática; adaptação.")

    def __init__(self, *args, kids=(), slots=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["student"].choices = [(s.pk, s.full_name) for s in kids]
        self.fields["slot"].choices = [(s.pk, f"{timezone.localtime(s.starts_at):%H:%M}") for s in slots]
        if len(kids) == 1:
            self.fields["student"].initial = kids[0].pk
            self.fields["student"].widget = forms.HiddenInput()


def _times(start, end, minutes):
    out, t = [], datetime.datetime.combine(datetime.date(2000, 1, 1), start)
    stop = datetime.datetime.combine(datetime.date(2000, 1, 1), end)
    while t + datetime.timedelta(minutes=minutes) <= stop and len(out) <= MAX_SLOTS:
        out.append(t.time())
        t += datetime.timedelta(minutes=minutes)
    return out


def build_slots(hours):
    """(Re)cria os horários livres a partir do intervalo. Só é chamado sem horário marcado."""
    hours.slots.filter(student__isnull=True).delete()
    OfficeSlot.objects.bulk_create([
        OfficeSlot(hours=hours, starts_at=timezone.make_aware(datetime.datetime.combine(hours.day, t)))
        for t in _times(hours.start, hours.end, hours.slot_minutes)])


def can_host(user):
    return user.is_authenticated and user.school_id and user.role in STAFF_ROLES


def can_manage(user, hours):
    return can_host(user) and hours.school_id == user.school_id and (
        hours.host_id == user.pk or user.role == Role.DIRECAO.value)


def _children(user):
    return [ln.student for ln in GuardianLink.objects.filter(guardian=user, status="aprovado", student__status="ativo")
            .select_related("student").order_by("student__first_name")]


def eligible_children(user, hours):
    """Filhos com matrícula ativa numa das turmas do atendimento."""
    kids = _children(user)
    ids = set(Enrollment.objects.filter(student__in=kids, status="ativo", class_group__in=hours.class_groups.all())
              .values_list("student_id", flat=True))
    return [s for s in kids if s.pk in ids]


def _family_hours(user, today):
    kids = _children(user)
    classes = Enrollment.objects.filter(student__in=kids, status="ativo").values_list("class_group_id", flat=True)
    return OfficeHours.objects.filter(school=user.school, day__gte=today, closed=False,
                                      class_groups__in=classes).distinct().select_related("host")


def announce(hours):
    """Avisa as famílias das turmas (um aviso por responsável, mesmo com dois filhos)."""
    from apps.communication.family_events import notify_family

    if hours.announced_at or hours.closed:
        return 0
    students = {e.student for e in Enrollment.objects.filter(
        class_group__in=hours.class_groups.all(), status="ativo", student__status="ativo").select_related(
        "student", "student__school")}
    who = hours.host.get_full_name() or hours.host.username
    total = 0
    for s in students:
        total += notify_family(
            s, "horarios_atendimento", f"Horários para conversar com {who}",
            body=f"{hours.title}: {hours.day:%d/%m} das {hours.start:%H:%M} às {hours.end:%H:%M}. Escolha um horário.",
            url=reverse("office:detail", args=[hours.pk]), include_student=False, dedupe_key=f"plantao:{hours.pk}")
    OfficeHours.objects.filter(pk=hours.pk).update(announced_at=timezone.now())
    return total


def office_list(request):
    user = request.user
    today = timezone.localdate()
    if user.role == Role.RESPONSAVEL.value and user.school_id:
        kids = _children(user)
        booked = (OfficeSlot.objects.filter(student__in=kids, starts_at__gte=timezone.now(), hours__school=user.school)
                  .select_related("hours", "hours__host", "student", "meeting"))
        rows = []
        for h in _family_hours(user, today):
            free = h.slots.filter(student__isnull=True, starts_at__gt=timezone.now()).count()
            rows.append({"h": h, "free": free})
        return render(request, "meetings/office_list.html", {"family": True, "rows": rows, "booked": booked})
    if not can_host(user):
        raise PermissionDenied
    qs = OfficeHours.objects.filter(school=user.school, day__gte=today - datetime.timedelta(days=30))
    if user.role != Role.DIRECAO.value:
        qs = qs.filter(host=user)
    rows = [{"h": h, "total": h.slots.count(), "taken": h.slots.filter(student__isnull=False).count()}
            for h in qs.select_related("host").prefetch_related("class_groups")]
    return render(request, "meetings/office_list.html", {"family": False, "rows": rows, "today": today})


def office_form(request, pk=None):
    user = request.user
    if not can_host(user):
        raise PermissionDenied
    hours = get_object_or_404(OfficeHours, pk=pk, school=user.school) if pk else None
    if hours and not can_manage(user, hours):
        raise PermissionDenied
    locked = bool(hours and hours.slots.filter(student__isnull=False).exists())
    form = OfficeHoursForm(request.POST or None, instance=hours, user=user, locked=locked)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            h = form.save(commit=False)
            if not hours:
                h.school, h.host = user.school, user
            h.save()
            form.save_m2m()
            if not locked:
                build_slots(h)
            create_audit_log(user=user, action="update" if hours else "create", request=request, target=h,
                             detail=f"{'Alterou' if hours else 'Abriu'} os horários de atendimento “{h.title}” "
                                    f"({h.day:%d/%m/%Y}, {h.start:%H:%M}–{h.end:%H:%M})")
        n = announce(h)
        messages.success(request, "Horários salvos." + (f" {n} responsáve{'is' if n != 1 else 'l'} avisado"
                                                         f"{'s' if n != 1 else ''}." if n else ""))
        return redirect("office:detail", pk=h.pk)
    return render(request, "meetings/office_form.html", {"form": form, "hours": hours, "locked": locked})


def office_detail(request, pk):
    user = request.user
    hours = get_object_or_404(OfficeHours.objects.select_related("host"), pk=pk, school=user.school) \
        if user.school_id else None
    if not hours:
        raise Http404
    now = timezone.now()
    if user.role == Role.RESPONSAVEL.value:
        kids = eligible_children(user, hours)
        if not kids:
            raise Http404
        mine = list(hours.slots.filter(student__in=kids).select_related("student"))
        free = [s for s in hours.slots.filter(student__isnull=True, starts_at__gt=now)]
        waiting = [s for s in kids if s.pk not in {m.student_id for m in mine}]
        form = BookingForm(kids=waiting, slots=free) if waiting and free and not hours.closed else None
        return render(request, "meetings/office_detail.html", {
            "hours": hours, "family": True, "mine": mine, "form": form, "free": len(free), "now": now})
    if not can_manage(user, hours):
        raise PermissionDenied
    slots = list(hours.slots.select_related("student", "booked_by", "meeting"))
    return render(request, "meetings/office_detail.html", {
        "hours": hours, "family": False, "slots": slots, "now": now,
        "taken": sum(1 for s in slots if not s.free), "classes": hours.class_groups.order_by("name")})


@require_POST
def office_book(request, pk):
    user = request.user
    if user.role != Role.RESPONSAVEL.value or not user.school_id:
        raise PermissionDenied
    hours = get_object_or_404(OfficeHours.objects.select_related("host"), pk=pk, school=user.school)
    kids = eligible_children(user, hours)
    if not kids:
        raise Http404
    back = redirect("office:detail", pk=hours.pk)
    if hours.closed:
        messages.error(request, "Estes horários foram fechados para novas marcações.")
        return back
    form = BookingForm(request.POST, kids=kids, slots=hours.slots.filter(student__isnull=True))
    if not form.is_valid():
        messages.error(request, "Escolha o estudante e um horário livre.")
        return back
    student = next(s for s in kids if s.pk == form.cleaned_data["student"])
    now = timezone.now()
    try:
        with transaction.atomic():
            taken = OfficeSlot.objects.filter(pk=form.cleaned_data["slot"], hours=hours, student__isnull=True,
                                              starts_at__gt=now).update(
                student=student, booked_by=user, booked_at=now, topic=form.cleaned_data["topic"].strip())
            if not taken:
                messages.error(request, "Esse horário acabou de ser marcado por outra família. Escolha outro.")
                return back
            slot = OfficeSlot.objects.select_related("hours").get(pk=form.cleaned_data["slot"])
            meeting = _make_meeting(slot, student)
            slot.meeting = meeting
            slot.save(update_fields=["meeting"])
    except IntegrityError:
        messages.error(request, f"{student.first_name} já tem um horário marcado neste atendimento.")
        return back
    create_audit_log(user=user, action="create", request=request, target=meeting,
                     detail=f"Marcou o horário das {timezone.localtime(slot.starts_at):%H:%M} em “{hours.title}” "
                            f"para {student}")
    services.notify_invited(meeting, user)
    messages.success(request, f"Marcado: {timezone.localtime(slot.starts_at):%d/%m às %H:%M}. Você recebe um lembrete "
                              "na véspera.")
    return back


def _make_meeting(slot, student):
    hours = slot.hours
    enrollment = Enrollment.objects.filter(student=student, status="ativo",
                                           class_group__in=hours.class_groups.all()).first()
    meeting = Meeting.objects.create(
        school=hours.school, kind=Meeting.Kind.FAMILY, title=f"{hours.title}: {student.first_name}", student=student,
        class_group=enrollment.class_group if enrollment else None, scheduled_at=slot.starts_at,
        duration_minutes=hours.slot_minutes, location=hours.location, agenda=slot.topic, created_by=hours.host)
    guardians = GuardianLink.objects.filter(student=student, status="aprovado", guardian__is_active=True) \
        .values_list("guardian_id", flat=True)
    meeting.participants.set({hours.host_id, *guardians})
    return meeting


def free_slot(slot):
    """Devolve o horário à lista de livres (a reunião, se houver, já foi cancelada por quem chamou)."""
    OfficeSlot.objects.filter(pk=slot.pk).update(student=None, booked_by=None, booked_at=None, topic="", meeting=None)


@require_POST
def office_release(request, slot_pk):
    """A família desmarca (até o horário) ou quem atende libera o horário. A reunião é cancelada com aviso."""
    from apps.registry.access import guardian_of

    user = request.user
    slot = get_object_or_404(OfficeSlot.objects.select_related("hours", "student", "meeting"), pk=slot_pk,
                             hours__school=user.school) if user.school_id else None
    if not slot or slot.free:
        raise Http404
    family = user.role == Role.RESPONSAVEL.value
    if not ((family and guardian_of(user, slot.student)) or can_manage(user, slot.hours)):
        raise PermissionDenied
    if family and slot.starts_at <= timezone.now():
        messages.error(request, "O horário já começou. Para desmarcar, fale com a escola.")
        return redirect("office:detail", pk=slot.hours_id)
    reason = "Desmarcado pela família." if family else (
        (request.POST.get("motivo") or "").strip()[:200] or "Quem atende precisou liberar o horário.")
    with transaction.atomic():
        m = slot.meeting
        if m and m.status == Meeting.Status.SCHEDULED:
            m.status, m.cancel_reason = Meeting.Status.CANCELED, reason
            m.save(update_fields=["status", "cancel_reason", "updated_at"])
            services.notify_canceled(m, user)
        free_slot(slot)
    create_audit_log(user=user, action="update", request=request, target=slot.hours,
                     detail=f"{'Desmarcou' if family else 'Liberou'} o horário das "
                            f"{timezone.localtime(slot.starts_at):%H:%M} de {slot.student} em “{slot.hours.title}”")
    messages.success(request, "Horário desmarcado." if family else "Horário liberado. A família foi avisada.")
    return redirect("office:detail", pk=slot.hours_id)


@require_POST
def office_toggle(request, pk):
    user = request.user
    hours = get_object_or_404(OfficeHours, pk=pk, school=user.school) if user.school_id else None
    if not hours or not can_manage(user, hours):
        raise PermissionDenied
    hours.closed = not hours.closed
    hours.save(update_fields=["closed"])
    create_audit_log(user=user, action="update", request=request, target=hours,
                     detail=f"{'Fechou' if hours.closed else 'Reabriu'} os horários “{hours.title}”")
    if not hours.closed:
        announce(hours)
    messages.success(request, "Fechado para novas marcações. Os horários marcados continuam." if hours.closed
                     else "Reaberto para marcações.")
    return redirect("office:detail", pk=hours.pk)


@require_POST
def office_delete(request, pk):
    user = request.user
    hours = get_object_or_404(OfficeHours, pk=pk, school=user.school) if user.school_id else None
    if not hours or not can_manage(user, hours):
        raise PermissionDenied
    if hours.slots.filter(student__isnull=False).exists():
        messages.error(request, "Há horários marcados: libere-os (as famílias são avisadas) ou feche as marcações.")
        return redirect("office:detail", pk=hours.pk)
    create_audit_log(user=user, action="delete", request=request, target=hours,
                     detail=f"Apagou os horários de atendimento “{hours.title}” ({hours.day:%d/%m/%Y})")
    hours.delete()
    messages.success(request, "Horários apagados.")
    return redirect("office:list")
