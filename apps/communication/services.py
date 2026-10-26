"""Geração de notificações internas a partir de eventos da plataforma.

Todas as notificações são persistentes e 100% internas (sem serviços pagos),
conforme a seção 10 do Prompt 1.
"""

from django.urls import reverse

from .models import Announcement, Notification


def notify(school, user, kind, title, body="", url=""):
    return Notification.objects.create(
        school=school, user=user, kind=kind, title=title, body=body, url=url
    )


def notify_many(school, users, kind, title, body="", url=""):
    if not users:
        return
    Notification.objects.bulk_create(
        Notification(
            school=school, user=u, kind=kind, title=title, body=body, url=url
        )
        for u in users
    )


def notify_evaluation_published(evaluation, request=None):
    """Notifica responsáveis dos estudantes da turma quando as notas saem."""
    from django.contrib.auth import get_user_model

    from apps.registry.models import Enrollment, GuardianLink

    student_ids = list(
        Enrollment.objects.filter(
            class_group=evaluation.class_group, status="ativo"
        ).values_list("student_id", flat=True)
    )
    guardian_ids = list(
        GuardianLink.objects.filter(
            student_id__in=student_ids, status="aprovado"
        ).values_list("guardian_id", flat=True)
    )
    if not guardian_ids:
        return
    User = get_user_model()
    guardians = User.objects.filter(pk__in=guardian_ids, is_active=True)
    notify_many(
        evaluation.school,
        guardians,
        Notification.Kind.EVALUATION,
        f"Notas publicadas: {evaluation.title}",
        body=(
            f"A avaliação de {evaluation.subject} da turma {evaluation.class_group} "
            "já está disponível para a família."
        ),
        url=reverse("pedagogy:evaluation_list"),
    )


def notify_activity_created(activity):
    """Avisa famílias sobre atividade/prazo (alertas de prazos)."""
    from django.contrib.auth import get_user_model

    from apps.registry.models import Enrollment, GuardianLink

    student_ids = list(
        Enrollment.objects.filter(
            class_group=activity.class_group, status="ativo"
        ).values_list("student_id", flat=True)
    )
    guardian_ids = list(
        GuardianLink.objects.filter(
            student_id__in=student_ids, status="aprovado"
        ).values_list("guardian_id", flat=True)
    )
    if not guardian_ids:
        return
    User = get_user_model()
    guardians = User.objects.filter(pk__in=guardian_ids, is_active=True)
    notify_many(
        activity.school,
        guardians,
        Notification.Kind.ACTIVITY,
        f"Atividade publicada: {activity.title}",
        body=(
            f"Atividade de {activity.subject} da turma {activity.class_group}."
            + (f" Prazo: {activity.deadline:%d/%m/%Y}." if activity.deadline else "")
        ),
        url=reverse("pedagogy:activity_list"),
    )


def notify_justification_resolved(justification, decision_label):
    requester = justification.submitted_by
    if not requester:
        return
    notify(
        justification.school,
        requester,
        Notification.Kind.JUSTIFICATION,
        f"Justificativa {decision_label}",
        body=f"A justificativa de falta de {justification.student} foi "
             f"{decision_label} pela secretaria.",
        url=reverse("pedagogy:justification_list"),
    )


def notify_thread_message(thread, message):
    """Notifica o participante que não enviou a mensagem."""
    other = next(
        (
            p for p in thread.participants.all()
            if p.pk != message.sender_id and p.is_active
        ),
        None,
    )
    if other is None:
        return
    notify(
        thread.school,
        other,
        Notification.Kind.MESSAGE,
        f"Nova mensagem: {thread.title}",
        body=f"{message.sender.get_full_name() or message.sender.username}: "
             f"{message.body[:120]}",
        url=reverse("communication:thread_detail", args=[thread.pk]),
    )


def notify_announcement_created(announcement):
    """Notifica toda a audiência-alvo de um comunicado (família/equipe/todos)."""
    from django.contrib.auth import get_user_model

    from apps.core.models import STAFF_ROLES
    from apps.registry.models import Enrollment, GuardianLink

    User = get_user_model()
    staff_roles = [r.value for r in STAFF_ROLES]
    recipients = User.objects.filter(school=announcement.school, is_active=True)
    if announcement.audience == Announcement.Audience.FAMILIA:
        recipients = recipients.exclude(role__in=staff_roles)
        if announcement.scope == Announcement.Scope.TURMA and announcement.class_group_id:
            student_ids = list(
                Enrollment.objects.filter(
                    class_group_id=announcement.class_group_id, status="ativo"
                ).values_list("student_id", flat=True)
            )
            guardian_ids = list(
                GuardianLink.objects.filter(
                    student_id__in=student_ids, status="aprovado"
                ).values_list("guardian_id", flat=True)
            )
            recipients = recipients.filter(pk__in=guardian_ids)
        elif announcement.scope == Announcement.Scope.INDIVIDUAL and announcement.student_id:
            guardian_ids = list(
                GuardianLink.objects.filter(
                    student_id=announcement.student_id, status="aprovado"
                ).values_list("guardian_id", flat=True)
            )
            recipients = recipients.filter(pk__in=guardian_ids)
    elif announcement.audience == Announcement.Audience.EQUIPE:
        recipients = recipients.filter(role__in=staff_roles)
    notify_many(
        announcement.school,
        recipients,
        Notification.Kind.ANNOUNCEMENT,
        f"Comunicado: {announcement.title}",
        body=announcement.body[:200],
        url=reverse("communication:announcement_list"),
    )


def notify_request_created(req):
    """Avisa a secretaria sobre nova solicitação da família."""
    from django.contrib.auth import get_user_model

    from apps.core.models import Role

    User = get_user_model()
    sec = User.objects.filter(
        school=req.school, role=Role.SECRETARIA.value, is_active=True
    )
    notify_many(
        req.school,
        sec,
        Notification.Kind.REQUEST,
        f"Nova solicitação: {req.title}",
        body=f"{req.requester.get_full_name() or req.requester.username}: "
             f"{req.description[:120]}",
        url=reverse("communication:request_list"),
    )


def notify_request_resolved(req):
    """Avisa o solicitante sobre a resposta da equipe."""
    if not req.requester.is_active:
        return
    notify(
        req.school,
        req.requester,
        Notification.Kind.REQUEST,
        f"Solicitação atualizada: {req.title}",
        body=f"Situação: {req.get_status_display()}."
             + (f" Resposta: {req.response[:120]}" if req.response else ""),
        url=reverse("communication:request_detail", args=[req.pk]),
    )


def notify_attendance_limit(student, class_group, percent):
    """Aviso de faltas: quando um estudante alcança o limite configurado."""
    from django.contrib.auth import get_user_model

    from apps.core.models import Role

    User = get_user_model()
    url = reverse("pedagogy:attendance_list") + f"?estudante={student.pk}"
    already = Notification.objects.filter(
        school=student.school,
        kind=Notification.Kind.ATTENDANCE,
        is_read=False,
        url=url,
    ).exists()
    if already:
        return
    staff = User.objects.filter(
        school=student.school, role=Role.SECRETARIA.value, is_active=True
    )
    notify_many(
        student.school,
        staff,
        Notification.Kind.ATTENDANCE,
        f"Alerta de faltas: {student.full_name}",
        body=(
            f"{student.full_name} ({class_group}) alcançou {percent}% de faltas. "
            "Confira a frequência e, se necessário, comunique a família."
        ),
        url=url,
    )