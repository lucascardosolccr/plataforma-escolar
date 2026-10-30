"""Regra única de "o que este professor leciona".

Um professor alcança um par turma + disciplina quando tem:
- atribuição dentro do período de atuação (``starts_on``/``ends_on``); ou
- permissão adicional ativa e dentro do prazo (``TeacherPermission``).

Permissão do tipo "consulta" dá acesso de leitura; só atribuição ou
permissão de "edição" deixam lançar notas, publicar atividades etc.

Todas as views e regras de acesso do professor passam por aqui, para que
"esconder do menu" e "recusar no servidor" nunca divirjam.
"""

from django.db.models import Q
from django.utils import timezone

from .models import TeacherAssignment, TeacherPermission


def active_assignments(user, today=None):
    """Atribuições do professor dentro do período de atuação."""
    today = today or timezone.localdate()
    return TeacherAssignment.objects.filter(teacher=user, school_id=user.school_id).filter(
        Q(starts_on__isnull=True) | Q(starts_on__lte=today),
        Q(ends_on__isnull=True) | Q(ends_on__gte=today),
    )


def teacher_pairs(user, edit=False, today=None):
    """Conjunto de (turma_id, disciplina_id) que o professor alcança."""
    if not getattr(user, "is_authenticated", False) or user.role != "professor":
        return set()
    cache_key = "_teacher_pairs_edit" if edit else "_teacher_pairs_view"
    if today is None and hasattr(user, cache_key):
        return getattr(user, cache_key)
    day = today or timezone.localdate()
    pairs = set(active_assignments(user, day).values_list("class_group_id", "subject_id"))
    perms = TeacherPermission.objects.filter(
        teacher=user, school_id=user.school_id, status=TeacherPermission.Status.ACTIVE, starts_on__lte=day,
    ).filter(Q(ends_on__isnull=True) | Q(ends_on__gte=day))
    if edit:
        perms = perms.filter(kind=TeacherPermission.Kind.EDIT)
    pairs |= set(perms.values_list("class_group_id", "subject_id"))
    if today is None:
        setattr(user, cache_key, pairs)  # uma consulta por requisição
    return pairs


def teacher_class_ids(user, edit=False):
    return {c for c, _ in teacher_pairs(user, edit)}


def teacher_subject_ids(user, class_ids=None, edit=False):
    return {s for c, s in teacher_pairs(user, edit) if class_ids is None or c in class_ids}


def teaches(user, class_group, subject=None, edit=False):
    """O professor alcança a turma (e, se dada, a disciplina nela)?"""
    cg = getattr(class_group, "pk", class_group)
    pairs = teacher_pairs(user, edit)
    if subject is None:
        return any(c == cg for c, _ in pairs)
    return (cg, getattr(subject, "pk", subject)) in pairs


def pairs_q(user, edit=False, class_field="class_group_id", subject_field="subject_id"):
    """Filtro ORM equivalente a ``teacher_pairs`` (nada passa sem par)."""
    q = Q(pk__in=[])
    for c, s in teacher_pairs(user, edit):
        q |= Q(**{class_field: c, subject_field: s})
    return q
