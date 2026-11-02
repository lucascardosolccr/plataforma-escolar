"""Avisos das reuniões, pela central de notificações da própria plataforma.

O texto do aviso nunca leva a pauta nem anotações: só assunto, data e local.
O resto fica na tela, atrás da verificação de acesso.
"""

from datetime import timedelta

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.communication.models import Notification
from apps.communication.services import notify


def _when(meeting):
    local = timezone.localtime(meeting.scheduled_at)
    where = f", {meeting.location}" if meeting.location else ""
    return f"{local:%d/%m/%Y} às {local:%H:%M}{where}"


def _send(meeting, title, body, dedupe, exclude=None, priority="normal"):
    url = reverse("meetings:detail", args=[meeting.pk])
    sent = 0
    for user in meeting.participants.filter(is_active=True):
        if exclude is not None and user.pk == exclude.pk:
            continue
        if notify(meeting.school, user, Notification.Kind.MEETING, title, body=body, url=url,
                  student=meeting.student, dedupe_key=f"{dedupe}-{user.pk}", priority=priority,
                  due_on=timezone.localtime(meeting.scheduled_at).date()):
            sent += 1
    return sent


def notify_invited(meeting, actor):
    """Convite. A chave inclui a data: remarcar avisa de novo, repetir não."""
    stamp = timezone.localtime(meeting.scheduled_at).strftime("%Y%m%d%H%M")
    return _send(meeting, f"Reunião marcada: {meeting.title}", _when(meeting),
                 f"reuniao-{meeting.pk}-{stamp}", exclude=actor)


def notify_rescheduled(meeting, actor):
    stamp = timezone.localtime(meeting.scheduled_at).strftime("%Y%m%d%H%M")
    return _send(meeting, f"Reunião remarcada: {meeting.title}", f"Nova data: {_when(meeting)}",
                 f"reuniao-{meeting.pk}-{stamp}", exclude=actor, priority="importante")


def notify_canceled(meeting, actor):
    return _send(meeting, f"Reunião cancelada: {meeting.title}",
                 f"Estava marcada para {_when(meeting)}. Motivo: {meeting.cancel_reason}",
                 f"reuniao-{meeting.pk}-cancelada", exclude=actor, priority="importante")


def notify_follow_up(follow_up, actor):
    user = follow_up.responsible
    if user is None or user.pk == actor.pk:
        return None
    prazo = f" Prazo: {follow_up.due_date:%d/%m/%Y}." if follow_up.due_date else ""
    meeting = follow_up.meeting
    return notify(meeting.school, user, Notification.Kind.MEETING,
                  f"Encaminhamento para você: {follow_up.description[:80]}",
                  body=f"Da reunião “{meeting.title}”.{prazo}",
                  url=reverse("meetings:detail", args=[meeting.pk]),
                  dedupe_key=f"encaminhamento-{follow_up.pk}", due_on=follow_up.due_date)


def meeting_reminders(today=None):
    """Lembrete na véspera, uma vez por data marcada (``reminded_for``).

    Chamado pelo processamento diário de lembretes (``communication.reminders.run_daily``).
    """
    from .models import Meeting

    today = today or timezone.localdate()
    tomorrow = today + timedelta(days=1)
    total = 0
    now = timezone.now()
    due = Meeting.objects.filter(
        status=Meeting.Status.SCHEDULED, scheduled_at__gte=now, scheduled_at__lte=now + timedelta(days=2),
    ).select_related("school", "student")
    for meeting in due:
        if timezone.localtime(meeting.scheduled_at).date() != tomorrow:
            continue
        if meeting.reminded_for == meeting.scheduled_at:
            continue
        with transaction.atomic():
            claimed = Meeting.objects.filter(pk=meeting.pk).exclude(
                reminded_for=meeting.scheduled_at).update(reminded_for=meeting.scheduled_at)
            if not claimed:
                continue
            stamp = timezone.localtime(meeting.scheduled_at).strftime("%Y%m%d%H%M")
            total += _send(meeting, f"Lembrete: reunião amanhã — {meeting.title}", _when(meeting),
                           f"reuniao-{meeting.pk}-lembrete-{stamp}")
    return total
