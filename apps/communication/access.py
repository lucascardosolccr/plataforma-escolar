"""Permissões da área de comunicação — verificadas no servidor em cada rota.

Regras gerais (matriz RBAC do Prompt 1, seções 5–8 e 10):
- Responsável conversa apenas com profissionais e enxerga apenas comunicados
  e solicitações relacionados aos filhos com vínculo aprovado.
- Professor envia comunicados apenas para turmas/estudantes das suas
  atribuições e conversa apenas com responsáveis dos seus estudantes.
- Secretaria envia comunicados a famílias e atende solicitações/justificativas.
- Coordenação e direção gerenciam comunicados institucionais.
"""

from django.core.exceptions import PermissionDenied

from apps.academics.models import TeacherAssignment
from apps.core.models import Role, STAFF_ROLES, User
from apps.registry.models import Enrollment, GuardianLink

from .models import Announcement

MANAGE_STAFF = (
    Role.DIRECAO.value,
    Role.COORDENACAO.value,
    Role.SECRETARIA.value,
    Role.ADMIN.value,
)


def require(ok):
    if not ok:
        raise PermissionDenied
    return True


def _guardian_of(user, student):
    if not user.is_authenticated or user.role != Role.RESPONSAVEL.value:
        return False
    return GuardianLink.objects.filter(
        guardian=user, student=student, status="aprovado"
    ).exists()


def _guardian_child_ids(user):
    return list(
        GuardianLink.objects.filter(guardian=user, status="aprovado").values_list(
            "student_id", flat=True
        )
    )


def _guardian_class_ids(user):
    child_ids = _guardian_child_ids(user)
    return list(
        Enrollment.objects.filter(student_id__in=child_ids, status="ativo").values_list(
            "class_group_id", flat=True
        )
    )


def _teacher_class_ids(user):
    return list(
        TeacherAssignment.objects.filter(teacher=user, school=user.school).values_list(
            "class_group_id", flat=True
        )
    )


def _teacher_student_ids(user):
    class_ids = _teacher_class_ids(user)
    return list(
        Enrollment.objects.filter(class_group_id__in=class_ids, status="ativo").values_list(
            "student_id", flat=True
        )
    )


def _teacher_of_student(user, student):
    if not user.is_authenticated or user.role != Role.PROFESSOR.value:
        return False
    return student.pk in _teacher_student_ids(user)


# ---------- Notificações ----------

def can_view_notifications(user):
    return user.is_authenticated


# ---------- Mensagens ----------

def can_start_thread(user):
    """Responsáveis e profissionais (da escola) podem abrir conversas."""
    if not user.is_authenticated or user.school_id is None:
        return False
    return user.is_staff_role or user.role == Role.RESPONSAVEL.value


def is_professional(user):
    return user.is_authenticated and user.is_staff_role


def can_message_professional(user):
    """O responsável fala com qualquer profissional da escola."""
    return user.is_authenticated and user.role == Role.RESPONSAVEL.value


def professional_recipients(user):
    """Profissionais da escola com quem um usuário pode conversar."""
    if user.role != Role.RESPONSAVEL.value:
        return User.objects.none()
    staff_roles = [r.value for r in STAFF_ROLES]
    return User.objects.filter(
        school=user.school, role__in=staff_roles, is_active=True
    ).order_by("username")


def guardian_recipients(user, student=None):
    """Responsáveis com quem um profissional pode conversar."""
    if student is not None:
        qs = GuardianLink.objects.filter(student=student, status="aprovado")
    else:
        class_ids = _teacher_class_ids(user)
        student_ids = _teacher_student_ids(user)
        if user.role in MANAGE_STAFF:
            qs = GuardianLink.objects.filter(school=user.school, status="aprovado")
        else:
            qs = GuardianLink.objects.filter(student_id__in=student_ids, status="aprovado")
    return User.objects.filter(
        pk__in=qs.values("guardian_id"), is_active=True
    ).order_by("username")


def can_message_user(user, other):
    """Par válido: um responsável + um profissional, mesma escola, ambos ativos."""
    if not user.is_authenticated or not other.is_active:
        return False
    if user.school_id is None or other.school_id is None:
        return False
    if user.school_id != other.school_id:
        return False
    roles = {user.role, other.role}
    return Role.RESPONSAVEL.value in roles and roles & set(r.value for r in (
        Role.ADMIN, Role.DIRECAO, Role.COORDENACAO, Role.SECRETARIA, Role.PROFESSOR
    )) != set()


def can_view_thread(user, thread):
    return user.is_authenticated and user in thread.participants.all()


def own_thread_ids(user):
    return user.threads.values_list("pk", flat=True)


# ---------- Comunicados ----------

def can_create_announcement(user, scope, class_group=None, student=None):
    if not user.is_authenticated or user.school_id is None:
        return False
    if scope == Announcement.Scope.INSTITUCIONAL:
        return user.role in (Role.DIRECAO.value, Role.COORDENACAO.value, Role.ADMIN.value)
    if scope == Announcement.Scope.TURMA:
        if user.role in (Role.DIRECAO.value, Role.COORDENACAO.value, Role.SECRETARIA.value, Role.ADMIN.value):
            return True
        if user.role == Role.PROFESSOR.value and class_group is not None:
            return class_group.pk in _teacher_class_ids(user)
        return False
    if scope == Announcement.Scope.INDIVIDUAL:
        if user.role in (Role.DIRECAO.value, Role.COORDENACAO.value, Role.SECRETARIA.value, Role.ADMIN.value):
            return True
        if user.role == Role.PROFESSOR.value and student is not None:
            return _teacher_of_student(user, student)
        return False
    return False


def can_view_announcements(user):
    return user.is_authenticated and user.school_id is not None


def can_view_announcement(user, announcement):
    if not can_view_announcements(user):
        return False
    if announcement.school_id != user.school_id:
        return False
    if user.role == Role.RESPONSAVEL.value:
        if announcement.audience not in (Announcement.Audience.FAMILIA, Announcement.Audience.TODOS):
            return False
        if announcement.scope == Announcement.Scope.INSTITUCIONAL:
            return True
        if announcement.scope == Announcement.Scope.TURMA:
            return (
                announcement.class_group_id is not None
                and announcement.class_group_id in _guardian_class_ids(user)
            )
        if announcement.scope == Announcement.Scope.INDIVIDUAL:
            return (
                announcement.student_id is not None
                and announcement.student_id in _guardian_child_ids(user)
            )
        return False
    # Profissionais
    if user.role == Role.PROFESSOR.value:
        if announcement.audience in (Announcement.Audience.EQUIPE, Announcement.Audience.TODOS):
            return True
        if announcement.scope == Announcement.Scope.INSTITUCIONAL:
            return True
        if announcement.scope == Announcement.Scope.TURMA:
            return (
                announcement.class_group_id is not None
                and announcement.class_group_id in _teacher_class_ids(user)
            )
        if announcement.scope == Announcement.Scope.INDIVIDUAL:
            return (
                announcement.student_id is not None
                and announcement.student_id in _teacher_student_ids(user)
            )
        return False
    return True


# ---------- Solicitações ----------

def can_create_request(user):
    return user.is_authenticated and user.role == Role.RESPONSAVEL.value


def can_manage_requests(user):
    """Secretaria e gestão analisam/respondem solicitações."""
    return user.is_authenticated and user.role in MANAGE_STAFF


def can_view_requests(user):
    return user.is_authenticated and (
        user.role in MANAGE_STAFF
        or user.role == Role.RESPONSAVEL.value
        or user.role == Role.PROFESSOR.value
    )


def can_view_request(user, req):
    if not user.is_authenticated or req.school_id != user.school_id:
        return False
    if user.role in MANAGE_STAFF:
        return True
    if user.role == Role.PROFESSOR.value:
        return (
            req.student_id is not None and req.student_id in _teacher_student_ids(user)
        ) or req.requester_id == user.pk
    return req.requester_id == user.pk or (
        req.student_id is not None and req.student_id in _guardian_child_ids(user)
    )