from django.core.exceptions import PermissionDenied

from apps.academics.models import TeacherAssignment
from apps.core.models import Role
from apps.registry.models import Enrollment


def _teacher_of(user, class_group, subject=None):
    if not user.is_authenticated or user.role != Role.PROFESSOR.value:
        return False
    qs = TeacherAssignment.objects.filter(
        teacher=user, class_group=class_group, school=class_group.school
    )
    if subject is not None:
        qs = qs.filter(subject=subject)
    return qs.exists()


def can_manage_evaluations(user, class_group, subject):
    """Cria/edita/lança notas apenas o professor com atribuição na turma/disciplina."""
    return _teacher_of(user, class_group, subject)


def can_view_evaluations(user):
    """Perfis que acompanham avaliações e notas, sem editar."""
    if not user.is_authenticated:
        return False
    return user.role in (
        Role.PROFESSOR.value,
        Role.COORDENACAO.value,
        Role.DIRECAO.value,
        Role.SECRETARIA.value,
        Role.ADMIN.value,
        Role.RESPONSAVEL.value,
    )


def can_manage_activities(user, class_group=None, subject=None):
    """Publica/edita/cancela atividade de casa.

    Só o professor com atribuição no PAR turma+disciplina. Validar os dois
    juntos importa: um professor de Matemática na turma A e de Português na
    turma B não pode publicar Português para a turma A.
    """
    if class_group is None:
        return user.is_authenticated and user.role == Role.PROFESSOR.value
    return _teacher_of(user, class_group, subject)


def can_view_activity(user, activity):
    """Quem pode abrir uma atividade específica.

    Coordenação, direção, secretaria e administração acompanham as atividades
    da própria escola. O professor vê as turmas em que leciona. O responsável
    vê apenas o que já foi publicado para a turma de um filho vinculado —
    rascunho e atividade agendada nunca chegam à família.
    """
    if not user.is_authenticated or user.school_id != activity.school_id:
        return False
    if user.role in (
        Role.COORDENACAO.value,
        Role.DIRECAO.value,
        Role.SECRETARIA.value,
        Role.ADMIN.value,
    ):
        return True
    if user.role == Role.PROFESSOR.value:
        return _teacher_of(user, activity.class_group)
    if user.role == Role.RESPONSAVEL.value:
        if not activity.is_visible_to_family:
            return False
        return _guardian_class_ids(user, activity.class_group_id)
    return False


def _guardian_class_ids(user, class_group_id):
    """Responsável tem filho vinculado e matriculado nesta turma?

    Considera qualquer matrícula, não apenas a ativa: um estudante transferido
    não perde o histórico de atividades que já lhe foram atribuídas.
    """
    from apps.registry.models import GuardianLink

    child_ids = GuardianLink.objects.filter(
        guardian=user, status="aprovado"
    ).values_list("student_id", flat=True)
    return Enrollment.objects.filter(
        student_id__in=child_ids, class_group_id=class_group_id
    ).exists()


def can_register_attendance(user, class_group):
    return _teacher_of(user, class_group)


def can_view_attendance(user):
    return can_view_evaluations(user)


def can_manage_occurrences(user, student=None):
    """Cria/atualiza ocorrência: professor (alunos da própria turma),
    coordenação e direção. A administração apenas visualiza."""
    if not user.is_authenticated:
        return False
    if user.role in (Role.COORDENACAO.value, Role.DIRECAO.value):
        return True
    if user.role == Role.PROFESSOR.value:
        return _teacher_of_student(user, student) if student else True
    return False


def can_view_occurrences(user, student=None):
    if not user.is_authenticated:
        return False
    if user.role in (
        Role.COORDENACAO.value,
        Role.DIRECAO.value,
        Role.ADMIN.value,
        Role.SECRETARIA.value,
    ):
        return True
    if user.role == Role.PROFESSOR.value:
        return _teacher_of_student(user, student) if student else True
    if user.role == Role.RESPONSAVEL.value:
        return _guardian_of(user, student) if student else False
    return False


def can_manage_observations(user, student=None):
    if not user.is_authenticated:
        return False
    if user.role == Role.COORDENACAO.value:
        return True
    if user.role == Role.PROFESSOR.value:
        return _teacher_of_student(user, student) if student else True
    return False


def can_view_observations(user, student=None):
    if not user.is_authenticated:
        return False
    if user.role in (Role.COORDENACAO.value, Role.DIRECAO.value):
        return True
    if user.role == Role.PROFESSOR.value:
        return _teacher_of_student(user, student) if student else True
    if user.role == Role.RESPONSAVEL.value:
        return _guardian_of(user, student) if student else False
    return False


def can_manage_plans(user):
    return user.is_authenticated and user.role == Role.COORDENACAO.value


def can_view_plans(user, student=None):
    if not user.is_authenticated:
        return False
    if user.role in (
        Role.COORDENACAO.value,
        Role.DIRECAO.value,
        Role.ADMIN.value,
        Role.PROFESSOR.value,
    ):
        if user.role == Role.PROFESSOR.value and student:
            return _teacher_of_student(user, student)
        return True
    if user.role == Role.RESPONSAVEL.value:
        return _guardian_of(user, student) if student else False
    return False


def can_manage_justifications(user):
    """Secretaria analisa/aprova/recusa; administração apenas visualiza."""
    return user.is_authenticated and user.role == Role.SECRETARIA.value


def can_view_justifications(user, student=None):
    if not user.is_authenticated:
        return False
    if user.role in (
        Role.SECRETARIA.value,
        Role.COORDENACAO.value,
        Role.DIRECAO.value,
        Role.ADMIN.value,
    ):
        return True
    if user.role == Role.PROFESSOR.value:
        return _teacher_of_student(user, student) if student else True
    if user.role == Role.RESPONSAVEL.value:
        return _guardian_of(user, student) if student else False
    return False


def can_edit_school_config(user):
    return user.is_authenticated and user.role in (Role.SECRETARIA.value, Role.ADMIN.value)


def _guardian_of(user, student):
    from apps.registry.models import GuardianLink

    if not user.is_authenticated or user.role != Role.RESPONSAVEL.value:
        return False
    return GuardianLink.objects.filter(
        guardian=user, student=student, status="aprovado"
    ).exists()


def _teacher_of_student(user, student):
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


def require(view_ok):
    """Conveniência: acaso da negação usa PermissionDenied (HTTP 403)."""
    if not view_ok:
        raise PermissionDenied
    return True