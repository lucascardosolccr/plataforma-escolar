"""Obriga a troca de senha temporária antes de usar a plataforma.

Sem isto, uma senha gerada pela secretaria e entregue em papel continuaria
valendo indefinidamente — e quem a viu no caminho continuaria com acesso.
"""

from django.shortcuts import redirect
from django.urls import reverse


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
