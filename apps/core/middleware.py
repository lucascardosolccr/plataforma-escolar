"""Obriga a troca de senha temporária antes de usar a plataforma.

Sem isto, uma senha gerada pela secretaria e entregue em papel continuaria
valendo indefinidamente — e quem a viu no caminho continuaria com acesso.
"""

import logging
import time

from django.shortcuts import redirect
from django.urls import reverse

logger = logging.getLogger(__name__)


class ForcePasswordChangeMiddleware:
    """Redireciona para a troca de senha enquanto a conta estiver marcada.

    As exceções abaixo são obrigatórias: sem elas o usuário não consegue nem
    trocar a senha nem sair, e fica preso num ciclo de redirecionamento.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and getattr(user, "must_change_password", False)
        ):
            permitidas = {
                reverse("password_change"),
                reverse("password_change_done"),
                reverse("logout"),
            }
            if request.path not in permitidas and not request.path.startswith(
                ("/static/", "/admin/")
            ):
                return redirect("password_change")
        return self.get_response(request)


class ScheduledPublicationMiddleware:
    """Entrega os avisos de atividades e trabalhos agendados quando a data chega.

    A plataforma roda sem agendador (sem cron, sem fila, sem serviço externo).
    Em vez disso, a primeira requisição autenticada depois do intervalo confere
    se há publicação agendada vencida e avisa as famílias. O custo é uma
    consulta curta a cada ``INTERVAL`` segundos por processo, não por página.
    Uma falha aqui nunca derruba a página: o aviso fica para a próxima vez.
    """

    INTERVAL = 300
    _last_run = None

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        agora = time.monotonic()
        ultima = ScheduledPublicationMiddleware._last_run
        if (
            user is not None
            and user.is_authenticated
            and (ultima is None or agora - ultima >= self.INTERVAL)
        ):
            ScheduledPublicationMiddleware._last_run = agora
            from apps.communication.services import deliver_due_publications

            try:
                deliver_due_publications()
            except Exception:  # o aviso não pode quebrar a navegação
                logger.exception("Falha ao entregar avisos de publicações agendadas")
        return self.get_response(request)
