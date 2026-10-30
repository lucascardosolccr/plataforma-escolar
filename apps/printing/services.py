"""Regras do fluxo de impressão: quem faz cada passo e quem é avisado."""

from django.db import transaction
from django.urls import reverse

from apps.communication.models import Notification
from apps.communication.services import notify, notify_many
from apps.core.models import Role, User, create_audit_log

from .models import PrintEvent, PrintRequest

S = PrintRequest.Status

# ação: (de quais estados, para qual, quem pode, exige justificativa, rótulo do botão)
TRANSITIONS = {
    "submit": ({S.DRAFT, S.CORRECTION}, S.SENT, "owner", False, "Enviar para a coordenação"),
    "cancel": ({S.DRAFT, S.SENT, S.REVIEW, S.CORRECTION, S.APPROVED}, S.CANCELED, "owner", False, "Cancelar pedido"),
    "review": ({S.SENT}, S.REVIEW, "reviewer", False, "Iniciar análise"),
    "approve": ({S.SENT, S.REVIEW}, S.APPROVED, "reviewer", False, "Aprovar para impressão"),
    "correction": ({S.SENT, S.REVIEW}, S.CORRECTION, "reviewer", True, "Pedir correção"),
    "reject": ({S.SENT, S.REVIEW}, S.REJECTED, "reviewer", True, "Recusar"),
    "start": ({S.APPROVED}, S.PRINTING, "printer", False, "Iniciar impressão"),
    "printed": ({S.PRINTING}, S.PRINTED, "printer", False, "Marcar como impressa"),
    "ready": ({S.PRINTED}, S.READY, "printer", False, "Disponível para retirada"),
    "deliver": ({S.PRINTED, S.READY}, S.DELIVERED, "printer", False, "Marcar como entregue"),
}
OPEN_FOR_REVIEW = (S.SENT, S.REVIEW)
PRINT_QUEUE = (S.APPROVED, S.PRINTING, S.PRINTED, S.READY)


def is_owner(user, req):
    return user.role == Role.PROFESSOR.value and req.requested_by_id == user.pk


def is_reviewer(user, req):
    """Coordenação que acompanha a turma (ou a direção)."""
    if user.school_id != req.school_id:
        return False
    if user.role == Role.DIRECAO.value:
        return True
    if user.role == Role.COORDENACAO.value:
        from apps.coordination.scope import reaches_class

        return reaches_class(user, req.activity.class_group)
    return False


def is_printer(user, req):
    return user.school_id == req.school_id and user.role in (Role.SECRETARIA.value, Role.ADMIN.value)


def can_view(user, req):
    return is_owner(user, req) or is_reviewer(user, req) or is_printer(user, req)


def allowed_actions(user, req):
    checks = {"owner": is_owner, "reviewer": is_reviewer, "printer": is_printer}
    return [
        (key, label, needs_note) for key, (sources, _to, who, needs_note, label) in TRANSITIONS.items()
        if req.status in sources and checks[who](user, req)
    ]


def reviewers_for(req):
    """Coordenadores cujo alcance inclui a turma; sem nenhum, a direção."""
    from apps.coordination.scope import reaches_class

    found = []
    for u in User.objects.filter(school=req.school, role=Role.COORDENACAO.value, is_active=True):
        if reaches_class(u, req.activity.class_group):
            found.append(u)
    if not found:
        found = list(User.objects.filter(school=req.school, role=Role.DIRECAO.value, is_active=True))
    return found


def _summary(req):
    teacher = (req.requested_by.get_full_name() or req.requested_by.username) if req.requested_by else "—"
    return (f"Professor: {teacher}. Disciplina: {req.activity.subject}. Turma: {req.activity.class_group.name}. "
            f"Aplicação: {req.application_date:%d/%m/%Y}. Impressão desejada: {req.desired_date:%d/%m/%Y}. "
            f"Cópias: {req.copies}.")


def apply_action(req, action, user, note="", request=None):
    sources, target, who, needs_note, _label = TRANSITIONS[action]
    if req.status not in sources:
        raise ValueError("Esta ação não vale para a situação atual do pedido.")
    if needs_note and not note.strip():
        raise ValueError("Escreva a justificativa da decisão.")
    url = reverse("printing:detail", args=[req.pk])
    with transaction.atomic():
        previous = req.status
        req.status = target
        if action == "submit":
            req.submissions += 1
        if who == "reviewer":
            req.decision_note = note.strip()
        req.save()
        PrintEvent.objects.create(request=req, from_status=previous, to_status=target, note=note.strip(), actor=user)
        create_audit_log(user=user, action="update", request=request, target=req,
                         detail=f"Impressão “{req.activity.title}”: {S(previous).label} → {S(target).label}")
        title = f"{req.activity.title}: {S(target).label}"
        if action == "submit":
            notify_many(req.school, reviewers_for(req), Notification.Kind.PRINT,
                        f"Pedido de impressão: {req.activity.title}", body=_summary(req), url=url,
                        dedupe_key=f"impressao-{req.pk}-envio-{req.submissions}")
        elif action == "approve":
            printers = User.objects.filter(school=req.school, role=Role.SECRETARIA.value, is_active=True)
            notify_many(req.school, printers, Notification.Kind.PRINT, f"Impressão aprovada: {req.activity.title}",
                        body=_summary(req), url=url, dedupe_key=f"impressao-{req.pk}-aprovada-{req.submissions}")
        if req.requested_by and req.requested_by_id != user.pk and action != "submit":
            notify(req.school, req.requested_by, Notification.Kind.PRINT, title,
                   body=note.strip() or _summary(req), url=url,
                   dedupe_key=f"impressao-{req.pk}-{target}-{req.submissions}")
    return req


def suggested_copies(activity):
    from apps.registry.models import Enrollment

    return Enrollment.objects.filter(class_group=activity.class_group, status="ativo").count()
