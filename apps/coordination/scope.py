"""Alcance do coordenador pedagógico: quais turmas ele acompanha.

``class_scope(user)`` devolve ``None`` quando não há restrição (perfil que
não é coordenação, ou designação "escola toda") e, para o coordenador
restrito, o conjunto de turmas que ele alcança, que pode ser vazio.
Todas as regras de acesso da coordenação passam por aqui.
"""

from django.db.models import Q
from django.utils import timezone

from apps.core.models import Role


def active_designations(user, today=None):
    from .models import CoordinatorAssignment

    today = today or timezone.localdate()
    return CoordinatorAssignment.objects.filter(
        coordinator=user, school_id=user.school_id, starts_on__lte=today,
    ).filter(Q(ends_on__isnull=True) | Q(ends_on__gte=today))


def class_scope(user):
    if not getattr(user, "is_authenticated", False) or user.role != Role.COORDENACAO.value:
        return None
    if hasattr(user, "_coord_scope"):
        return user._coord_scope
    from apps.academics.models import TeacherAssignment

    designations = list(active_designations(user).prefetch_related("class_groups", "subjects", "teachers"))
    if any(d.all_school for d in designations):
        scope = None
    else:
        classes, teachers, subjects = set(), set(), set()
        for d in designations:
            classes |= {c.pk for c in d.class_groups.all()}
            teachers |= {t.pk for t in d.teachers.all()}
            subjects |= {s.pk for s in d.subjects.all()}
        if teachers or subjects:
            classes |= set(
                TeacherAssignment.objects.filter(school_id=user.school_id)
                .filter(Q(teacher_id__in=teachers) | Q(subject_id__in=subjects))
                .values_list("class_group_id", flat=True)
            )
        scope = classes
    user._coord_scope = scope
    return scope


def teacher_scope(user):
    """Professores que o coordenador acompanha (None = todos)."""
    classes = class_scope(user)
    if classes is None:
        return None
    from apps.academics.models import TeacherAssignment

    ids = set(TeacherAssignment.objects.filter(class_group_id__in=classes).values_list("teacher_id", flat=True))
    for d in active_designations(user).prefetch_related("teachers"):
        ids |= {t.pk for t in d.teachers.all()}
    return ids


def reaches_class(user, class_group):
    scope = class_scope(user)
    return scope is None or getattr(class_group, "pk", class_group) in scope


def reaches_student(user, student):
    """O coordenador alcança o estudante (matrícula ativa numa turma do alcance)?"""
    scope = class_scope(user)
    if scope is None:
        return True
    from apps.registry.models import Enrollment

    return Enrollment.objects.filter(student=student, status="ativo", class_group_id__in=scope).exists()


def student_ids(user):
    scope = class_scope(user)
    if scope is None:
        return None
    from apps.registry.models import Enrollment

    return set(Enrollment.objects.filter(class_group_id__in=scope, status="ativo").values_list("student_id", flat=True))
