from apps.core.models import Role


def can_manage_academics(user):
    """Turmas, disciplinas, anos letivos e atribuições são geridos por
    secretaria, coordenação e administração."""
    return user.is_authenticated and user.role in (
        Role.SECRETARIA.value,
        Role.COORDENACAO.value,
        Role.ADMIN.value,
    )


def can_view_academics(user):
    return can_manage_academics(user) or (
        user.is_authenticated and user.role == Role.DIRECAO.value
    )