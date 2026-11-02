"""Quem vê e quem mantém os conteúdos da prova. Tudo conferido no servidor.

- Mantém: o professor com atribuição de edição no par turma+disciplina.
- Acompanha (só lê): coordenação no alcance da designação; direção.
- Família: estudante (conta própria) e responsável com vínculo aprovado, só
  do que está publicado e dentro do período de visibilidade, e só para turmas
  em que o estudante esteve no período da prova (mesma regra das atividades).
- Secretaria e administração: não precisam e não veem (minimização, §14).
"""

from django.db.models import Q

from apps.academics.permissions import teacher_pairs, teaches
from apps.core.models import Role
from apps.pedagogy import access as ped

from .models import ExamGuide

FAMILY = (Role.RESPONSAVEL.value, Role.ESTUDANTE.value)


def can_create(user):
    return user.is_authenticated and user.role == Role.PROFESSOR.value and bool(teacher_pairs(user, edit=True))


def can_manage(user, guide):
    return (user.is_authenticated and user.school_id == guide.school_id
            and user.role == Role.PROFESSOR.value
            and teaches(user, guide.class_group, guide.subject, edit=True))


def family_students(user, guide):
    """Ids dos estudantes pelos quais o usuário responde e que a prova alcança."""
    if not guide.is_visible_to_family:
        return []
    return ped.family_students_reached(user, guide)


def staff_queryset(user):
    qs = ExamGuide.objects.filter(school=user.school)
    if user.role == Role.PROFESSOR.value:
        pairs = teacher_pairs(user)
        q = Q(pk__in=[])
        for cg, subj in pairs:
            q |= Q(class_group_id=cg, subject_id=subj)
        return qs.filter(q)
    if user.role == Role.COORDENACAO.value:
        from apps.coordination.scope import class_scope

        scope = class_scope(user)
        return qs if scope is None else qs.filter(class_group_id__in=scope)
    if user.role == Role.DIRECAO.value:
        return qs
    return ExamGuide.objects.none()


def family_queryset(user):
    """Conteúdos visíveis à família (antes do filtro fino por período de matrícula)."""
    enrollments = ped.family_enrollments(user)
    return ExamGuide.objects.filter(ExamGuide.family_visible_q(), school=user.school,
                                    class_group_id__in={e.class_group_id for e in enrollments})


def can_view(user, guide):
    if not user.is_authenticated or user.school_id != guide.school_id:
        return False
    if user.role in FAMILY:
        return bool(family_students(user, guide))
    return staff_queryset(user).filter(pk=guide.pk).exists()


def is_family(user):
    return user.role in FAMILY
