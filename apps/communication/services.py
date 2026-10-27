"""Geração de notificações internas a partir de eventos da plataforma.

Todas as notificações são persistentes e 100% internas (sem serviços pagos),
conforme a seção 10 do Prompt 1.
"""

from django.urls import reverse
from django.utils import timezone

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


def _group_work_member_ids(work):
    from apps.pedagogy.models import WorkGroupMember

    return list(
        WorkGroupMember.objects.filter(
            group__group_work=work, removed_at__isnull=True
        ).values_list("student_id", flat=True).distinct()
    )


def _notify_class_families(item, title, url, detail="", student_ids=None):
    """Avisa responsáveis e estudantes com conta de uma publicação da turma.

    Uma notificação por (responsável, estudante) e com o nome do estudante no
    texto: quem tem mais de um filho precisa saber de quem é a tarefa. A
    unicidade por par também evita avisar duas vezes o mesmo responsável pelo
    mesmo filho quando existe mais de um vínculo registrado. O aviso nunca
    traz dado individual de colega (como a composição de um grupo): isso fica
    na tela, atrás da verificação de vínculo.

    ``student_ids`` restringe o público (os integrantes de um trabalho em
    grupo); sem ele, vale a turma inteira.
    """
    from apps.registry.models import Enrollment, GuardianLink, Student

    if student_ids is None:
        student_ids = list(
            Enrollment.objects.filter(
                class_group=item.class_group, status="ativo"
            ).values_list("student_id", flat=True)
        )
    if not student_ids:
        return
    links = (
        GuardianLink.objects.filter(
            student_id__in=student_ids, status="aprovado", guardian__is_active=True
        )
        .select_related("guardian", "student")
        .distinct()
    )
    contexto = f"{item.subject}, turma {item.class_group}.{detail}"
    seen = set()
    pending = []
    for link in links:
        key = (link.guardian_id, link.student_id)
        if key in seen:
            continue
        seen.add(key)
        pending.append(
            Notification(
                school=item.school,
                user=link.guardian,
                kind=Notification.Kind.ACTIVITY,
                title=title,
                body=f"{link.student} — {contexto}",
                url=url,
            )
        )
    # O próprio estudante, quando a escola criou acesso para ele.
    for student in Student.objects.filter(
        pk__in=student_ids, user__isnull=False, user__is_active=True
    ).select_related("user"):
        pending.append(
            Notification(
                school=item.school,
                user=student.user,
                kind=Notification.Kind.ACTIVITY,
                title=title,
                body=contexto,
                url=url,
            )
        )
    if pending:
        Notification.objects.bulk_create(pending)


def _prazo(item):
    return f" Entrega até {item.deadline:%d/%m/%Y}." if item.deadline else ""


def notify_activity_created(activity):
    """Avisa as famílias de uma atividade publicada para a turma."""
    _notify_class_families(
        activity,
        f"Nova atividade de casa: {activity.title}",
        reverse("pedagogy:activity_detail", args=[activity.pk]),
        _prazo(activity),
    )


def notify_group_work_published(work, member_ids=None):
    """Avisa as famílias dos integrantes de um trabalho em grupo publicado.

    Só quem está num grupo: para o estudante sem grupo, o aviso levaria a uma
    tela sem nada que lhe diga respeito.
    """
    _notify_class_families(
        work,
        f"Novo trabalho em grupo: {work.title}",
        reverse("pedagogy:group_work_detail", args=[work.pk]),
        _prazo(work),
        student_ids=member_ids if member_ids is not None else _group_work_member_ids(work),
    )


def announce_publication(item):
    """Avisa a família de uma atividade ou trabalho, uma única vez, na data certa.

    Publicação com data futura não avisa agora: o link responderia "acesso
    negado" até a data chegar. Ela é avisada depois, por
    ``deliver_due_publications``. A marcação de ``notified_at`` é feita com um
    UPDATE condicional antes de criar os avisos, então duas requisições ao
    mesmo tempo não avisam em dobro. Devolve True se avisou.
    """
    from apps.pedagogy.models import Activity

    if item.status != "publicada" or item.published_date > timezone.localdate():
        return False
    member_ids = None
    if not isinstance(item, Activity):
        # Trabalho em grupo sem composição ainda não diz nada a ninguém: o
        # aviso espera os grupos serem formados (a tela de grupos chama esta
        # função de novo ao salvar).
        member_ids = _group_work_member_ids(item)
        if not member_ids:
            return False
    agora = timezone.now()
    claimed = type(item).objects.filter(
        pk=item.pk, notified_at__isnull=True
    ).update(notified_at=agora)
    if not claimed:
        return False
    item.notified_at = agora
    if isinstance(item, Activity):
        notify_activity_created(item)
    else:
        notify_group_work_published(item, member_ids)
    return True


def notify_publication_canceled(item):
    """Avisa do cancelamento quem já tinha sido avisado da publicação.

    Sem isso a família continua fazendo uma tarefa que deixou de existir. Quem
    nunca recebeu o aviso original (rascunho, publicação agendada) não recebe
    o de cancelamento.
    """
    from apps.pedagogy.models import Activity

    if item.notified_at is None:
        return
    if isinstance(item, Activity):
        title = f"Atividade cancelada: {item.title}"
        url = reverse("pedagogy:activity_detail", args=[item.pk])
    else:
        title = f"Trabalho em grupo cancelado: {item.title}"
        url = reverse("pedagogy:group_work_detail", args=[item.pk])
    motivo = f" Motivo: {item.cancel_reason}" if item.cancel_reason else ""
    publico = None if isinstance(item, Activity) else _group_work_member_ids(item)
    _notify_class_families(item, title, url, motivo, student_ids=publico)


def deliver_due_publications(school=None):
    """Avisa as publicações agendadas cuja data já chegou.

    Não há agendador em segundo plano (custo zero, servidor simples): esta
    função é chamada pelo ``ScheduledPublicationMiddleware`` no máximo a cada
    poucos minutos. Devolve quantas publicações foram avisadas.
    """
    from apps.pedagogy.models import Activity, GroupWork

    total = 0
    for model in (Activity, GroupWork):
        due = model.objects.filter(
            status="publicada",
            notified_at__isnull=True,
            published_date__lte=timezone.localdate(),
        ).select_related("school", "subject", "class_group")
        if school is not None:
            due = due.filter(school=school)
        for item in due:
            total += announce_publication(item)
    return total


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
    """Notifica exatamente quem pode abrir o comunicado (ver
    ``access.announcement_recipients``)."""
    from .access import announcement_recipients

    recipients = list(announcement_recipients(announcement))
    notify_many(
        announcement.school,
        recipients,
        Notification.Kind.ANNOUNCEMENT,
        f"Comunicado: {announcement.title}",
        body=announcement.body[:200],
        url=reverse("communication:announcement_detail", args=[announcement.pk]),
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