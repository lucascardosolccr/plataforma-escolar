"""Ponte entre o painel da coordenação e a fila de impressão."""


def pending_print_requests(user):
    """Pedidos de impressão aguardando análise, no alcance da coordenação."""
    from apps.coordination.scope import class_scope
    from apps.printing.models import PrintRequest
    from apps.printing.services import OPEN_FOR_REVIEW

    qs = PrintRequest.objects.filter(school=user.school, status__in=OPEN_FOR_REVIEW).select_related(
        "activity", "activity__class_group")
    scope = class_scope(user)
    if scope is not None:
        qs = qs.filter(activity__class_group_id__in=scope)
    return list(qs.order_by("desired_date"))
