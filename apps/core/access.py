from django.contrib.auth.mixins import AccessMixin
from django.core.exceptions import PermissionDenied

from .models import Role, STAFF_ROLES


def user_has_role(user, roles):
    if not user or not user.is_authenticated:
        return False
    if not roles:
        return True
    return user.role in roles


def role_required(*roles):
    """Decorador para vistas baseadas em função.

    Uso: @role_required(Role.SECRETARIA, Role.ADMIN)
    Redireciona usuários anônimos para o login e nega acesso (403)
    a usuários autenticados sem o perfil exigido.
    """

    def decorator(view_func):
        def _wrapped(request, *args, **kwargs):
            if not user_has_role(request.user, roles):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


class RoleRequiredMixin(AccessMixin):
    """Mixin para vistas baseadas em classe."""

    roles = ()

    def dispatch(self, request, *args, **kwargs):
        if not user_has_role(request.user, self.roles):
            return self.handle_no_permission()
        return super().dispatch(request, *args, **kwargs)


class StaffRoleRequiredMixin(RoleRequiredMixin):
    """Restringe a profissionais (qualquer papel exceto responsável)."""

    roles = tuple(r.value for r in STAFF_ROLES)


def same_school(user_a, user_b):
    """Valida isolamento entre escolas no servidor."""
    if not user_a.is_authenticated or not user_b.is_authenticated:
        return False
    if user_a.school_id is None or user_b.school_id is None:
        return False
    return user_a.school_id == user_b.school_id