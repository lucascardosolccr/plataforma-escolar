"""Senha temporária gerada pela escola.

A plataforma não envia e-mail (requisito de custo zero), então não existe
recuperação por link. Quem esquece a senha pede à secretaria ou à
administração, que gera uma senha temporária e a entrega pessoalmente.
"""

import secrets
import string

from django.core.exceptions import PermissionDenied

from .models import Role

# Sem caracteres ambíguos (O/0, l/1/I): a senha é lida em voz alta ou copiada
# à mão de um papel, e um erro de leitura vira um atendimento a mais.
_ALFABETO = (
    "".join(c for c in string.ascii_uppercase if c not in "OIL")
    + "".join(c for c in string.ascii_lowercase if c not in "ol")
    + "23456789"
)

TEMP_PASSWORD_LENGTH = 12


def generate_temp_password(length=TEMP_PASSWORD_LENGTH):
    """Senha temporária aleatória, com `secrets` (não `random`)."""
    return "".join(secrets.choice(_ALFABETO) for _ in range(length))


def can_reset_password(actor, target):
    """Quem pode redefinir a senha de quem.

    A administração redefine qualquer conta da própria escola. A secretaria
    redefine apenas contas de responsável — é o atendimento que ela faz no
    dia a dia — e não contas de direção, coordenação ou professor. Ninguém
    redefine a própria senha por aqui: para isso existe a troca de senha.
    """
    if not actor.is_authenticated or not getattr(target, "pk", None):
        return False
    if actor.pk == target.pk:
        return False
    if actor.school_id is None or actor.school_id != target.school_id:
        return False
    if actor.role == Role.ADMIN.value:
        return True
    if actor.role == Role.SECRETARIA.value:
        return target.role == Role.RESPONSAVEL.value
    return False


def reset_password(actor, target):
    """Aplica uma senha temporária e obriga a troca no próximo acesso."""
    if not can_reset_password(actor, target):
        raise PermissionDenied
    senha = generate_temp_password()
    target.set_password(senha)
    target.must_change_password = True
    target.save(update_fields=["password", "must_change_password"])
    return senha
