"""Controle de acesso dos painéis analíticos e relatórios.

Toda verificação é feita no servidor. Os painéis apenas reaproveitam as regras
de acesso já existentes nos módulos de origem (cadastro e pedagógico) para não
duplicar a matriz RBAC.
"""

from apps.academics.models import TeacherAssignment
from apps.core.models import Role
from apps.registry.access import ADMIN_RECORD_ROLES, can_view_student

# Perfis com visão agregada da escola (painel institucional).
INSTITUTIONAL_ROLES = (
    Role.ADMIN.value,
    Role.DIRECAO.value,
    Role.COORDENACAO.value,
)

# Perfis com painel administrativo.
SECRETARIA_ROLES = (Role.SECRETARIA.value, Role.ADMIN.value)


def can_view_student_dashboard(user, student):
    """Mesma regra do prontuário: responsável com vínculo aprovado, professor
    da turma, ou perfil administrativo da escola."""
    return can_view_student(user, student)


def can_view_class_dashboard(user, class_group):
    if not user.is_authenticated or user.school_id != class_group.school_id:
        return False
    if user.role in ADMIN_RECORD_ROLES:
        return True
    if user.role == Role.PROFESSOR.value:
        return TeacherAssignment.objects.filter(
            teacher=user, class_group=class_group
        ).exists()
    return False


def can_view_institutional_dashboard(user):
    return user.is_authenticated and user.role in INSTITUTIONAL_ROLES


def can_view_secretaria_panel(user):
    return user.is_authenticated and user.role in SECRETARIA_ROLES


def can_view_reports(user):
    """Todos os perfis autenticados têm acesso a algum relatório; o conjunto
    disponível é filtrado por papel dentro do registro de relatórios."""
    return user.is_authenticated and user.role in (
        Role.ADMIN.value,
        Role.DIRECAO.value,
        Role.COORDENACAO.value,
        Role.SECRETARIA.value,
        Role.PROFESSOR.value,
        Role.RESPONSAVEL.value,
    )
