"""Quem vê, quem marca e quem mantém cada reunião. Tudo conferido no servidor.

- Marcam reunião: direção, coordenação, secretaria e professor. Com
  estudante, só um estudante que a pessoa já pode abrir (``students_visible_to``):
  o professor, quem é das turmas dele; a coordenação restrita, quem está na
  designação.
- Veem a reunião: os participantes e quem a marcou; a direção, todas; a
  coordenação, as do seu alcance. O responsável só enquanto o vínculo com o
  estudante da reunião estiver aprovado.
- Mantêm (editar, registrar, cancelar, encaminhar): quem marcou, a direção e
  a coordenação do alcance.
- Anotações da equipe e encaminhamentos internos: nunca para a família.
"""

from django.db.models import Q

from apps.core.models import Role

from .models import Meeting

STAFF_ROLES = (Role.DIRECAO.value, Role.COORDENACAO.value, Role.SECRETARIA.value, Role.PROFESSOR.value)
FAMILY_ROLES = (Role.RESPONSAVEL.value, Role.ESTUDANTE.value)


def can_create(user):
    return user.is_authenticated and user.role in STAFF_ROLES


def can_link_student(user, student):
    from apps.registry.access import students_visible_to

    qs = students_visible_to(user)
    return qs is not None and qs.filter(pk=student.pk).exists()


def _approved_children(user):
    from apps.registry.models import GuardianLink

    return GuardianLink.objects.filter(guardian=user, status="aprovado").values_list("student_id", flat=True)


def meetings_visible_to(user):
    """Reuniões que esta pessoa pode abrir (regra única: lista, detalhe e calendário)."""
    if not user.is_authenticated:
        return Meeting.objects.none()
    qs = Meeting.objects.filter(school=user.school)
    mine = Q(participants=user) | Q(created_by=user)
    if user.role == Role.DIRECAO.value:
        return qs
    if user.role == Role.COORDENACAO.value:
        from apps.coordination.scope import class_scope, student_ids

        scope = class_scope(user)
        if scope is None:
            return qs
        return qs.filter(mine | Q(student_id__in=student_ids(user)) | Q(class_group_id__in=scope)).distinct()
    if user.role in STAFF_ROLES:
        return qs.filter(mine).distinct()
    if user.role == Role.RESPONSAVEL.value:
        return qs.filter(participants=user).filter(
            Q(student__isnull=True) | Q(student_id__in=_approved_children(user))
        ).distinct()
    return Meeting.objects.none()


def can_view(user, meeting):
    return meetings_visible_to(user).filter(pk=meeting.pk).exists()


def can_manage(user, meeting):
    if not user.is_authenticated or user.school_id != meeting.school_id or user.role not in STAFF_ROLES:
        return False
    if meeting.created_by_id == user.pk or user.role == Role.DIRECAO.value:
        return True
    if user.role == Role.COORDENACAO.value:
        from apps.coordination.scope import reaches_class, reaches_student

        if meeting.student_id:
            return reaches_student(user, meeting.student)
        if meeting.class_group_id:
            return reaches_class(user, meeting.class_group)
        # Reunião sem estudante nem turma: só a coordenação da escola toda.
        return _whole_school(user)
    return False


def _whole_school(user):
    from apps.coordination.scope import class_scope

    return class_scope(user) is None


def can_view_confidential(user, meeting):
    return user.role in STAFF_ROLES and can_view(user, meeting)


def can_update_follow_up(user, follow_up):
    if follow_up.responsible_id == user.pk and user.role in STAFF_ROLES:
        return True
    return can_manage(user, follow_up.meeting)
