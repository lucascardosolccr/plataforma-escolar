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


def student_of(user):
    """Estudante cuja conta de acesso é este usuário, ou None."""
    if not user.is_authenticated or user.role != Role.ESTUDANTE.value:
        return None
    return getattr(user, "student_record", None)


def is_own_record(user, student):
    """O usuário é o próprio estudante da ficha?"""
    own = student_of(user)
    return own is not None and own.pk == student.pk


def students_visible_to(user):
    """Estudantes que este usuário pode abrir, ou None se não pode ver nenhum.

    Regra única usada pela lista de estudantes e pela busca global: o
    responsável vê os filhos com vínculo aprovado; o professor, quem tem
    matrícula ativa numa turma em que leciona; a equipe de cadastro, a escola.
    """
    from .models import Student

    if not user.is_authenticated:
        return None
    if user.role == Role.RESPONSAVEL.value:
        ids = GuardianLink.objects.filter(guardian=user, status="aprovado").values_list(
            "student_id", flat=True
        )
        return Student.objects.filter(pk__in=ids)
    if user.role == Role.PROFESSOR.value:
        return Student.objects.filter(
            school=user.school,
            enrollments__status="ativo",
            enrollments__class_group__teacher_assignments__teacher=user,
        ).distinct()
    if can_manage_registry(user):
        return Student.objects.filter(school=user.school)
    return None


def can_view_student(user, student):
    if not user.is_authenticated:
        return False
    if user.role in ADMIN_RECORD_ROLES:
        return user.school_id == student.school_id
    if guardian_of(user, student):
        return True
    if user.role == Role.PROFESSOR.value:
        return teacher_of_student(user, student)
    # O estudante vê a própria ficha, e só ela.
    return is_own_record(user, student)


def can_view_birth_date(user):
    """Dados de identificação sensíveis não são mostrados a professores."""
    return user.is_authenticated and user.role != Role.PROFESSOR.value


def can_view_student_notes(user):
    """Observações da secretaria apenas para perfis administrativos.

    O estudante não vê as anotações feitas sobre ele pela secretaria.
    """
    return user.is_authenticated and user.role in ADMIN_RECORD_ROLES


def can_create_student_account(user, student):
    """Só a secretaria e a administração criam o acesso do estudante.

    A coordenação e a direção acompanham, mas a criação de conta é um ato
    administrativo com efeito sobre dados de menor: fica com quem cuida da
    matrícula.
    """
    if not user.is_authenticated:
        return False
    if user.role not in (Role.SECRETARIA.value, Role.ADMIN.value):
        return False
    return user.school_id == student.school_id


def require_student_access(user, student):
    if not can_view_student(user, student):
        raise PermissionDenied
    return True