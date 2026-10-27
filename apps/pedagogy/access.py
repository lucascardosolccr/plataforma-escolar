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
    """Perfis que acompanham avaliações e notas, sem editar.

    Inclui o estudante, que vê as próprias notas publicadas. Não inclui
    ocorrências nem observações pedagógicas — essas têm regra própria e
    permanecem fora do alcance dele.
    """
    if not user.is_authenticated:
        return False
    return user.role in (
        Role.PROFESSOR.value,
        Role.COORDENACAO.value,
        Role.DIRECAO.value,
        Role.SECRETARIA.value,
        Role.ADMIN.value,
        Role.RESPONSAVEL.value,
        Role.ESTUDANTE.value,
    )


def own_student(user):
    """Estudante por trás de uma conta de estudante, ou None."""
    from apps.registry.access import student_of

    return student_of(user)


def _student_class_ids(user):
    """Turmas em que o estudante tem (ou teve) matrícula.

    Inclui matrícula encerrada para o histórico não desaparecer quando ele
    muda de turma — a mesma regra usada para a família.
    """
    student = own_student(user)
    if student is None:
        return []
    return list(
        Enrollment.objects.filter(student=student).values_list(
            "class_group_id", flat=True
        )
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
    if user.role == Role.ESTUDANTE.value:
        if not activity.is_visible_to_family:
            return False
        return activity.class_group_id in _student_class_ids(user)
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


def can_manage_group_works(user, class_group=None, subject=None):
    """Cria/edita/publica trabalho em grupo e organiza os grupos.

    Mesma regra das atividades: só o professor com atribuição no PAR
    turma+disciplina.
    """
    if class_group is None:
        return user.is_authenticated and user.role == Role.PROFESSOR.value
    return _teacher_of(user, class_group, subject)


def can_view_group_work(user, work):
    """Quem pode abrir um trabalho em grupo.

    O responsável e o estudante só alcançam o que foi publicado e cuja data
    já chegou, e apenas quando há vínculo com a turma — rascunho e trabalho
    agendado não chegam à família nem por identificador na URL.
    """
    if not user.is_authenticated or user.school_id != work.school_id:
        return False
    if user.role in (
        Role.COORDENACAO.value,
        Role.DIRECAO.value,
        Role.SECRETARIA.value,
        Role.ADMIN.value,
    ):
        return True
    if user.role == Role.PROFESSOR.value:
        return _teacher_of(user, work.class_group)
    if not work.is_visible_to_family:
        return False
    if user.role == Role.RESPONSAVEL.value:
        return _guardian_class_ids(user, work.class_group_id)
    if user.role == Role.ESTUDANTE.value:
        return work.class_group_id in _student_class_ids(user)
    return False


def group_work_students_for(user, work):
    """Estudantes do ponto de vista de quem está olhando.

    Devolve os estudantes pelos quais este usuário vê o trabalho: os filhos
    vinculados matriculados na turma, ou ele mesmo. Vazio para a equipe, que
    vê o trabalho inteiro e não "pelo" aluno nenhum.
    """
    from apps.registry.models import Enrollment, GuardianLink, Student

    if user.role == Role.RESPONSAVEL.value:
        child_ids = GuardianLink.objects.filter(
            guardian=user, status="aprovado"
        ).values_list("student_id", flat=True)
        matriculados = Enrollment.objects.filter(
            student_id__in=child_ids, class_group=work.class_group
        ).values_list("student_id", flat=True)
        return list(
            Student.objects.filter(pk__in=matriculados).order_by(
                "first_name", "last_name"
            )
        )
    if user.role == Role.ESTUDANTE.value:
        own = own_student(user)
        return [own] if own is not None else []
    return []


def visible_groups_for(user, work):
    """Quais grupos deste trabalho o usuário pode ver a composição.

    A equipe e o professor da turma veem todos os grupos. O responsável e o
    estudante veem apenas o grupo de que participam — saber quem são os
    colegas do próprio grupo é necessário para organizar o trabalho; a
    composição dos OUTROS grupos não é.
    """
    todos = work.groups.all()
    if user.role in (
        Role.COORDENACAO.value,
        Role.DIRECAO.value,
        Role.SECRETARIA.value,
        Role.ADMIN.value,
    ):
        return todos
    if user.role == Role.PROFESSOR.value and _teacher_of(user, work.class_group):
        return todos
    alvos = [s.pk for s in group_work_students_for(user, work)]
    if not alvos:
        return todos.none()
    return todos.filter(
        members__student_id__in=alvos, members__removed_at__isnull=True
    ).distinct()


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