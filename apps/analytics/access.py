"""Controle de acesso dos painéis analíticos e relatórios.

Toda verificação é feita no servidor. Os painéis apenas reaproveitam as regras
de acesso já existentes nos módulos de origem (cadastro e pedagógico) para não
duplicar a matriz RBAC.
"""

from apps.academics.permissions import teacher_pairs, teaches
from apps.coordination.scope import class_scope, reaches_class
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
    if user.role == Role.COORDENACAO.value:
        return reaches_class(user, class_group)
    if user.role in ADMIN_RECORD_ROLES:
        return True
    if user.role == Role.PROFESSOR.value:
        return teaches(user, class_group)
    return False


def can_view_institutional_dashboard(user):
    """Visão agregada da escola. Coordenação só com designação "escola toda":
    a restrita usa o painel da coordenação, com as turmas dela."""
    if not (user.is_authenticated and user.role in INSTITUTIONAL_ROLES):
        return False
    return user.role != Role.COORDENACAO.value or class_scope(user) is None


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


def can_view_data_quality(user):
    """Qualidade dos dados: quem administra registros da escola."""
    return user.is_authenticated and user.role in ADMIN_RECORD_ROLES


def subject_classes_for(user, subject):
    """Turmas em que este usuário pode analisar a disciplina, ou None.

    A gestão vê todas as turmas da escola que têm a disciplina (por atribuição
    ou avaliação); o professor, só as turmas em que a leciona.
    """
    from django.db.models import Q

    from apps.academics.models import ClassGroup

    if not user.is_authenticated or user.school_id != subject.school_id:
        return None
    if user.role in ADMIN_RECORD_ROLES:
        qs = (
            ClassGroup.objects.filter(school=user.school)
            .filter(Q(teacher_assignments__subject=subject) | Q(evaluation__subject=subject))
            .distinct().select_related("school_year").order_by("name")
        )
        scope = class_scope(user)
        return qs if scope is None else qs.filter(pk__in=scope)
    if user.role == Role.PROFESSOR.value:
        qs = ClassGroup.objects.filter(
            pk__in={c for c, s in teacher_pairs(user) if s == subject.pk}
        ).select_related("school_year").order_by("name")
        return qs if qs.exists() else None
    return None


def can_view_teacher_dashboard(user):
    """Painel do professor: só o próprio professor (não é avaliação docente)."""
    return user.is_authenticated and user.role == Role.PROFESSOR.value
