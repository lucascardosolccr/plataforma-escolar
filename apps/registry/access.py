from django.core.exceptions import PermissionDenied

from apps.academics.models import TeacherAssignment
from apps.core.models import Role

from .models import Enrollment, GuardianLink


ADMIN_RECORD_ROLES = [
    Role.ADMIN.value,
    Role.DIRECAO.value,
    Role.COORDENACAO.value,
    Role.SECRETARIA.value,
]


def can_manage_registry(user):
    """Secretaria, coordenação, direção e administrador gerenciam cadastro."""
    return user.is_authenticated and user.role in ADMIN_RECORD_ROLES


def can_manage_guardian_links(user):
    """Somente secretaria e administrador validam vínculos."""
    return user.is_authenticated and user.role in (
        Role.SECRETARIA.value,
        Role.ADMIN.value,
    )


def guardian_of(user, student):
    """Responsável com vínculo aprovado com o estudante."""
    if not user.is_authenticated or user.role != Role.RESPONSAVEL.value:
        return False
    return GuardianLink.objects.filter(
        guardian=user, student=student, status="aprovado"
    ).exists()


def teacher_of_student(user, student):
    """Professor que leciona em uma turma com matrícula ativa do estudante."""
    if not user.is_authenticated or user.role != Role.PROFESSOR.value:
        return False
    class_ids = list(
        Enrollment.objects.filter(student=student, status="ativo").values_list(
            "class_group_id", flat=True
        )
    )
    if not class_ids:
        return False
    return TeacherAssignment.objects.filter(
        teacher=user, class_group_id__in=class_ids, school=student.school
    ).exists()


def can_view_student(user, student):
    if not user.is_authenticated:
        return False
    if user.role in ADMIN_RECORD_ROLES:
        return user.school_id == student.school_id
    if guardian_of(user, student):
        return True
    if user.role == Role.PROFESSOR.value:
        return teacher_of_student(user, student)
    return False


def can_view_birth_date(user):
    """Dados de identificação sensíveis não são mostrados a professores."""
    return user.is_authenticated and user.role != Role.PROFESSOR.value


def can_view_student_notes(user):
    """Observações da secretaria apenas para perfis administrativos."""
    return user.is_authenticated and user.role in ADMIN_RECORD_ROLES


def require_student_access(user, student):
    if not can_view_student(user, student):
        raise PermissionDenied
    return True