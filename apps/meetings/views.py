from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.core.models import Role, create_audit_log
from apps.core.pagination import paginate
from apps.core.params import id_param
from apps.registry.models import GuardianLink

from . import access, services
from .forms import FollowUpForm, MeetingCancelForm, MeetingForm, MeetingRecordForm
from .models import Meeting, MeetingFollowUp


def _log(request, action, target, detail):
    create_audit_log(user=request.user, action=action, request=request, target=target, detail=detail)


def _require(condition):
    if not condition:
        raise PermissionDenied


def _get(request, pk):
    meeting = get_object_or_404(
        Meeting.objects.select_related("student", "class_group", "created_by"), pk=pk,
        school=request.user.school)
    _require(access.can_view(request.user, meeting))
    return meeting


def _set_participants(meeting, form, actor):
    """Participantes = quem marcou + equipe escolhida + (se pedido) os
    responsáveis com vínculo aprovado do estudante."""
    users = {actor.pk, *(u.pk for u in form.cleaned_data.get("staff") or [])}
    if form.cleaned_data.get("invite_guardians") and meeting.student_id:
        users |= set(GuardianLink.objects.filter(
            student_id=meeting.student_id, status="aprovado", guardian__is_active=True
        ).values_list("guardian_id", flat=True))
    meeting.participants.set(users)


def meeting_list(request):
    user = request.user
    _require(user.role in access.STAFF_ROLES or user.role == Role.RESPONSAVEL.value)
    qs = access.meetings_visible_to(user).select_related("student", "class_group", "created_by")
    now = timezone.now()
    when = request.GET.get("quando", "proximas")
    if when == "anteriores":
        qs = qs.filter(Q(scheduled_at__lt=now) | ~Q(status=Meeting.Status.SCHEDULED)).order_by("-scheduled_at")
    else:
        when = "proximas"
        qs = qs.filter(scheduled_at__gte=now, status=Meeting.Status.SCHEDULED).order_by("scheduled_at")
    student_id = id_param(request, "estudante")
    if student_id:
        qs = qs.filter(student_id=student_id)
    page = paginate(request, qs)
    my_follow_ups = []
    if user.role in access.STAFF_ROLES:
        my_follow_ups = list(
            MeetingFollowUp.objects.filter(responsible=user, status=MeetingFollowUp.Status.PENDING,
                                           meeting__school=user.school)
            .select_related("meeting").order_by("due_date", "pk")[:20])
    return render(request, "meetings/list.html", {
        "meetings": page, "page": page, "when": when, "student_id": student_id,
        "can_create": access.can_create(user), "my_follow_ups": my_follow_ups,
        "is_family": user.role == Role.RESPONSAVEL.value,
    })


def meeting_create(request):
    user = request.user
    _require(access.can_create(user))
    form = MeetingForm(request.POST or None, user=user)
    student_id = id_param(request, "estudante")
    if request.method != "POST" and student_id and form.fields["student"].queryset.filter(pk=student_id).exists():
        form.initial.update({"student": int(student_id), "invite_guardians": True})
    if request.method == "POST" and form.is_valid():
        student = form.cleaned_data.get("student")
        _require(student is None or access.can_link_student(user, student))
        with transaction.atomic():
            meeting = form.save(commit=False)
            meeting.school = user.school
            meeting.created_by = user
            meeting.save()
            _set_participants(meeting, form, user)
            _log(request, "create", meeting, f"Marcou a reunião {meeting.title}")
            services.notify_invited(meeting, user)
        messages.success(request, "Reunião marcada. Os participantes foram avisados na plataforma.")
        return redirect("meetings:detail", pk=meeting.pk)
    return render(request, "meetings/form.html", {"form": form, "obj": None})


def meeting_edit(request, pk):
    user = request.user
    meeting = _get(request, pk)
    _require(access.can_manage(user, meeting))
    if meeting.status != Meeting.Status.SCHEDULED:
        messages.warning(request, "Só reunião agendada pode ser alterada. O registro de uma reunião realizada "
                                  "ou cancelada fica como está.")
        return redirect("meetings:detail", pk=meeting.pk)
    old_when = meeting.scheduled_at
    form = MeetingForm(request.POST or None, instance=meeting, user=user)
    if request.method == "POST" and form.is_valid():
        student = form.cleaned_data.get("student")
        _require(student is None or student.pk == meeting.student_id or access.can_link_student(user, student))
        with transaction.atomic():
            meeting = form.save()
            before = set(meeting.participants.values_list("pk", flat=True))
            _set_participants(meeting, form, meeting.created_by or user)
            _log(request, "update", meeting, f"Alterou a reunião {meeting.title}: "
                 + ", ".join(form.fields[f].label.lower() for f in form.changed_data))
            if meeting.scheduled_at != old_when:
                services.notify_rescheduled(meeting, user)
            else:
                # Quem entrou agora recebe o convite; quem já estava, não de novo.
                novos = set(meeting.participants.values_list("pk", flat=True)) - before
                if novos:
                    services.notify_invited(meeting, user)
        messages.success(request, "Reunião atualizada.")
        return redirect("meetings:detail", pk=meeting.pk)
    return render(request, "meetings/form.html", {"form": form, "obj": meeting})


def meeting_detail(request, pk):
    user = request.user
    meeting = _get(request, pk)
    staff_view = access.can_view_confidential(user, meeting)
    can_manage = access.can_manage(user, meeting)
    follow_ups = meeting.follow_ups.select_related("responsible", "done_by")
    if not staff_view:
        follow_ups = follow_ups.filter(staff_only=False)
    follow_ups = list(follow_ups)
    for fu in follow_ups:
        fu.can_update = staff_view and fu.status == MeetingFollowUp.Status.PENDING \
            and access.can_update_follow_up(user, fu)
    participants = list(meeting.participants.order_by("first_name", "last_name"))
    return render(request, "meetings/detail.html", {
        "meeting": meeting,
        "participants": participants,
        "staff_view": staff_view,
        "can_manage": can_manage,
        "follow_ups": follow_ups,
        "record_form": MeetingRecordForm(instance=meeting)
        if can_manage and meeting.status != Meeting.Status.CANCELED and meeting.is_past else None,
        "follow_up_form": FollowUpForm(school=user.school) if can_manage and meeting.status != Meeting.Status.CANCELED else None,
    })


def meeting_record(request, pk):
    """Registra o que foi conversado; a reunião passa a "realizada"."""
    if request.method != "POST":
        raise PermissionDenied
    user = request.user
    meeting = _get(request, pk)
    _require(access.can_manage(user, meeting) and meeting.status != Meeting.Status.CANCELED)
    if not meeting.is_past:
        # Antes do horário, "realizada" seria falso; para mudar a pauta, use Alterar.
        messages.warning(request, "A reunião ainda não aconteceu. O registro fica disponível depois do horário marcado.")
        return redirect("meetings:detail", pk=meeting.pk)
    form = MeetingRecordForm(request.POST, instance=meeting)
    if form.is_valid():
        with transaction.atomic():
            meeting = form.save(commit=False)
            meeting.status = Meeting.Status.DONE
            meeting.save()
            _log(request, "update", meeting, f"Registrou a reunião {meeting.title}")
        messages.success(request, "Registro salvo. A reunião consta como realizada.")
    else:
        messages.error(request, "Escreva o registro da reunião antes de salvar.")
    return redirect("meetings:detail", pk=meeting.pk)


def meeting_cancel(request, pk):
    user = request.user
    meeting = _get(request, pk)
    _require(access.can_manage(user, meeting))
    if meeting.status != Meeting.Status.SCHEDULED:
        messages.warning(request, "Esta reunião não está agendada.")
        return redirect("meetings:detail", pk=meeting.pk)
    form = MeetingCancelForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            meeting.status = Meeting.Status.CANCELED
            meeting.cancel_reason = form.cleaned_data["reason"]
            meeting.save(update_fields=["status", "cancel_reason", "updated_at"])
            _log(request, "update", meeting, f"Cancelou a reunião {meeting.title}: {meeting.cancel_reason}")
            services.notify_canceled(meeting, user)
        messages.success(request, "Reunião cancelada. Os participantes foram avisados.")
        return redirect("meetings:detail", pk=meeting.pk)
    return render(request, "meetings/cancel.html", {"form": form, "meeting": meeting})


def follow_up_add(request, pk):
    if request.method != "POST":
        raise PermissionDenied
    user = request.user
    meeting = _get(request, pk)
    _require(access.can_manage(user, meeting) and meeting.status != Meeting.Status.CANCELED)
    form = FollowUpForm(request.POST, school=user.school)
    if form.is_valid():
        with transaction.atomic():
            fu = form.save(commit=False)
            fu.meeting = meeting
            fu.save()
            if fu.responsible_id:
                # Quem cuida do encaminhamento precisa ver a reunião: entra
                # como participante, à vista na lista, em vez de um acesso oculto.
                meeting.participants.add(fu.responsible)
            _log(request, "create", fu, f"Encaminhamento na reunião {meeting.title}: {fu.description}")
            services.notify_follow_up(fu, user)
        messages.success(request, "Encaminhamento registrado.")
    else:
        messages.error(request, "Descreva o encaminhamento.")
    return redirect("meetings:detail", pk=meeting.pk)


def follow_up_update(request, pk, follow_up_id):
    if request.method != "POST":
        raise PermissionDenied
    user = request.user
    meeting = _get(request, pk)
    fu = get_object_or_404(MeetingFollowUp, pk=follow_up_id, meeting=meeting)
    _require(access.can_update_follow_up(user, fu))
    new_status = request.POST.get("status")
    if fu.status != MeetingFollowUp.Status.PENDING or new_status not in (
            MeetingFollowUp.Status.DONE, MeetingFollowUp.Status.CANCELED):
        messages.warning(request, "Este encaminhamento já foi encerrado.")
        return redirect("meetings:detail", pk=meeting.pk)
    with transaction.atomic():
        fu.status = new_status
        fu.done_note = (request.POST.get("done_note") or "").strip()[:300]
        fu.done_at = timezone.now()
        fu.done_by = user
        fu.save()
        _log(request, "update", fu, f"Encaminhamento {fu.get_status_display().lower()}: {fu.description}")
    messages.success(request, "Encaminhamento atualizado.")
    return redirect("meetings:detail", pk=meeting.pk)

