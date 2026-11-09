"""Quem vê e quem altera a ficha de saúde e a lista de retirada.

- **Ficha completa** (alergias, condições, remédios, plano de crise, contatos, plano de saúde): responsável com
  vínculo aprovado, secretaria, direção, administração e coordenação (só as turmas da designação).
- **Alertas de sala** (alergias, restrição alimentar, condições e plano de crise, sem contatos nem remédios):
  professor de uma turma do estudante.
- **Alteram a ficha:** o responsável e a secretaria/direção/administração (a partir da ficha em papel).
- **Lista de retirada:** o responsável mantém; secretaria, direção e administração também (pedido da família).
- **Registram a retirada:** quem opera a portaria (secretaria, direção, administração e coordenação).

O estudante não vê a ficha: quem informa e acompanha é a família.
"""

from apps.core.models import Role
from apps.registry.access import guardian_of, teacher_of_student

OFFICE = (Role.SECRETARIA.value, Role.DIRECAO.value, Role.ADMIN.value)
TEAM = OFFICE + (Role.COORDENACAO.value,)


def _same_school(user, student):
    return user.is_authenticated and student.school_id == user.school_id


def _team_reaches(user, student):
    if not _same_school(user, student) or user.role not in TEAM:
        return False
    if user.role == Role.COORDENACAO.value:
        from apps.coordination.scope import reaches_student

        return reaches_student(user, student)
    return True


def health_level(user, student):
    """"full", "alerts" ou None."""
    if guardian_of(user, student) or _team_reaches(user, student):
        return "full"
    if teacher_of_student(user, student):
        return "alerts"
    return None


def can_edit_health(user, student):
    return guardian_of(user, student) or (_same_school(user, student) and user.role in OFFICE)


def can_manage_pickups(user, student):
    return guardian_of(user, student) or (_same_school(user, student) and user.role in OFFICE)


def can_register_pickup(user, student):
    return _team_reaches(user, student)


def can_see_pickups(user, student):
    return guardian_of(user, student) or _team_reaches(user, student)


def can_view_class_alerts(user, class_group):
    if not user.is_authenticated or class_group.school_id != user.school_id:
        return False
    if user.role == Role.PROFESSOR.value:
        from apps.academics.permissions import teacher_class_ids

        return class_group.pk in teacher_class_ids(user)
    if user.role == Role.COORDENACAO.value:
        from apps.coordination.scope import class_scope

        scope = class_scope(user)
        return scope is None or class_group.pk in scope
    return user.role in OFFICE


def can_view_food_list(user):
    """Restrições alimentares e alergias por turma (cozinha, cardápio): a equipe que cuida do cardápio e a
    coordenação (só as turmas da designação)."""
    return user.is_authenticated and user.role in TEAM
