from django.core.exceptions import PermissionDenied
from django.db.models import Q

from apps.academics.permissions import teacher_class_ids, teaches
from apps.coordination.scope import reaches_class, reaches_student
from apps.core.models import Role
from apps.registry.models import Enrollment


def _teacher_of(user, class_group, subject=None, edit=False):
    """Professor que alcança a turma (e a disciplina, se dada). Regra única em
    ``academics.permissions``: atribuição no período de atuação ou permissão
    adicional ativa. ``edit`` exige atribuição ou permissão de lançamento."""
    if not user.is_authenticated or user.role != Role.PROFESSOR.value:
        return False
    if class_group.school_id != user.school_id:
        return False
    return teaches(user, class_group, subject, edit=edit)


def can_manage_evaluations(user, class_group, subject):
    """Cria/edita/lança notas apenas o professor com atribuição na turma/disciplina."""
    return _teacher_of(user, class_group, subject, edit=True)


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


def enrollments_by_student(student_ids, class_group_id=None):
    """{estudante: [matrículas]} numa consulta, para checar o alcance em lote."""
    qs = Enrollment.objects.filter(student_id__in=list(student_ids))
    if class_group_id is not None:
        qs = qs.filter(class_group_id=class_group_id)
    out = {}
    for enr in qs.only("student_id", "class_group_id", "started_on", "ended_on"):
        out.setdefault(enr.student_id, []).append(enr)
    return out


def reaches(enrollments, item):
    """A publicação para a turma (atividade ou trabalho) alcança o estudante?

    Alcança quando alguma matrícula dele naquela turma cobre a publicação: o
    histórico sobrevive à transferência, mas o que a turma antiga recebe
    depois da saída não chega a quem saiu (ver ``Enrollment.covers``).
    """
    return any(
        enr.class_group_id == item.class_group_id
        and enr.covers(item.published_date, item.deadline)
        for enr in enrollments
    )


def enrollment_window_q(enrollments, date_field):
    """Filtro equivalente a ``reaches`` para itens com uma data só (avaliações).

    Cada matrícula contribui com "esta turma, entre a entrada e a saída". Sem
    matrícula, o filtro não deixa passar nada.
    """
    q = Q(pk__in=[])
    for enr in enrollments:
        parte = Q(class_group_id=enr.class_group_id)
        if enr.started_on:
            parte &= Q(**{f"{date_field}__gte": enr.started_on})
        if enr.ended_on:
            parte &= Q(**{f"{date_field}__lte": enr.ended_on})
        q |= parte
    return q


def reach_q(enrollments):
    """Filtro equivalente a ``reaches`` para atividades e trabalhos."""
    q = Q(pk__in=[])
    for enr in enrollments:
        parte = Q(class_group_id=enr.class_group_id)
        if enr.ended_on:
            parte &= Q(published_date__lte=enr.ended_on)
        if enr.started_on:
            parte &= Q(deadline__isnull=True) | Q(deadline__gte=enr.started_on)
        q |= parte
    return q


def family_enrollments(user):
    """Matrículas (todas, inclusive encerradas) dos estudantes deste usuário."""
    if user.role == Role.RESPONSAVEL.value:
        student_ids = _approved_child_ids(user)
    elif user.role == Role.ESTUDANTE.value:
        own = own_student(user)
        student_ids = [own.pk] if own is not None else []
    else:
        return []
    return [e for enrs in enrollments_by_student(student_ids).values() for e in enrs]


def _approved_child_ids(user):
    from apps.registry.models import GuardianLink

    return list(
        GuardianLink.objects.filter(guardian=user, status="aprovado").values_list(
            "student_id", flat=True
        )
    )


def _family_reaches(user, item):
    """Algum estudante pelo qual este usuário responde é alcançado pelo item?"""
    if user.role == Role.RESPONSAVEL.value:
        student_ids = _approved_child_ids(user)
    elif user.role == Role.ESTUDANTE.value:
        own = own_student(user)
        student_ids = [own.pk] if own is not None else []
    else:
        return False
    por_aluno = enrollments_by_student(student_ids, item.class_group_id)
    return any(reaches(enrs, item) for enrs in por_aluno.values())


def can_manage_activities(user, class_group=None, subject=None):
    """Publica/edita/cancela atividade de casa.

    Só o professor com atribuição no PAR turma+disciplina. Validar os dois
    juntos importa: um professor de Matemática na turma A e de Português na
    turma B não pode publicar Português para a turma A.
    """
    if class_group is None:
        return user.is_authenticated and user.role == Role.PROFESSOR.value
    return _teacher_of(user, class_group, subject, edit=True)


def can_view_activity(user, activity):
    """Quem pode abrir uma atividade específica.

    Coordenação, direção, secretaria e administração acompanham as atividades
    da própria escola. O professor vê as turmas em que leciona. O responsável
    vê apenas o que já foi publicado para a turma de um filho vinculado —
    rascunho e atividade agendada nunca chegam à família.
    """
    if not user.is_authenticated or user.school_id != activity.school_id:
        return False
    if user.role == Role.COORDENACAO.value:
        return reaches_class(user, activity.class_group)
    if user.role in (
        Role.DIRECAO.value,
        Role.SECRETARIA.value,
        Role.ADMIN.value,
    ):
        return True
    if user.role == Role.PROFESSOR.value:
        return _teacher_of(user, activity.class_group, activity.subject)
    if user.role in (Role.RESPONSAVEL.value, Role.ESTUDANTE.value):
        if not activity.is_visible_to_family:
            return False
        # Qualquer matrícula conta, não só a ativa: o transferido não perde o
        # que já lhe foi atribuído. Mas só dentro do período em que esteve na
        # turma.
        return _family_reaches(user, activity)
    return False


def can_manage_group_works(user, class_group=None, subject=None):
    """Cria/edita/publica trabalho em grupo e organiza os grupos.

    Mesma regra das atividades: só o professor com atribuição no PAR
    turma+disciplina.
    """
    if class_group is None:
        return user.is_authenticated and user.role == Role.PROFESSOR.value
    return _teacher_of(user, class_group, subject, edit=True)


def can_view_group_work(user, work):
    """Quem pode abrir um trabalho em grupo.

    O responsável e o estudante só alcançam o que foi publicado e cuja data
    já chegou, e apenas quando há vínculo com a turma — rascunho e trabalho
    agendado não chegam à família nem por identificador na URL.
    """
    if not user.is_authenticated or user.school_id != work.school_id:
        return False
    if user.role == Role.COORDENACAO.value:
        return reaches_class(user, work.class_group)
    if user.role in (
        Role.DIRECAO.value,
        Role.SECRETARIA.value,
        Role.ADMIN.value,
    ):
        return True
    if user.role == Role.PROFESSOR.value:
        return _teacher_of(user, work.class_group, work.subject)
    if not work.is_visible_to_family:
        return False
    return _family_reaches(user, work)


def group_work_students_for(user, work):
    """Estudantes do ponto de vista de quem está olhando.

    Devolve os estudantes pelos quais este usuário vê o trabalho: os filhos
    vinculados matriculados na turma, ou ele mesmo. Vazio para a equipe, que
    vê o trabalho inteiro e não "pelo" aluno nenhum.
    """
    from apps.registry.models import Student

    if user.role == Role.RESPONSAVEL.value:
        por_aluno = enrollments_by_student(
            _approved_child_ids(user), work.class_group_id
        )
        alcancados = [sid for sid, enrs in por_aluno.items() if reaches(enrs, work)]
        return list(
            Student.objects.filter(pk__in=alcancados).order_by(
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
    if user.role == Role.PROFESSOR.value and _teacher_of(user, work.class_group, work.subject):
        return todos
    alvos = [s.pk for s in group_work_students_for(user, work)]
    if not alvos:
        return todos.none()
    return todos.filter(
        members__student_id__in=alvos, members__removed_at__isnull=True
    ).distinct()


def can_register_attendance(user, class_group):
    return _teacher_of(user, class_group, edit=True)


def can_view_attendance(user):
    return can_view_evaluations(user)


def can_manage_occurrences(user, student=None):
    """Cria/atualiza ocorrência: professor (alunos da própria turma),
    coordenação e direção. A administração apenas visualiza."""
    if not user.is_authenticated:
        return False
    if user.role in (Role.COORDENACAO.value, Role.DIRECAO.value):
        if user.role == Role.COORDENACAO.value and student is not None:
            return reaches_student(user, student)
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
        if user.role == Role.COORDENACAO.value and student is not None:
            return reaches_student(user, student)
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
        if user.role == Role.COORDENACAO.value and student is not None:
            return reaches_student(user, student)
        return True
    if user.role == Role.PROFESSOR.value:
        return _teacher_of_student(user, student) if student else True
    return False


def can_view_observations(user, student=None):
    if not user.is_authenticated:
        return False
    if user.role in (Role.COORDENACAO.value, Role.DIRECAO.value):
        if user.role == Role.COORDENACAO.value and student is not None:
            return reaches_student(user, student)
        return True
    if user.role == Role.PROFESSOR.value:
        return _teacher_of_student(user, student) if student else True
    if user.role == Role.RESPONSAVEL.value:
        return _guardian_of(user, student) if student else False
    return False


def teacher_observations_q(user, student):
    """Observações de um estudante que o professor pode ler: as que ele
    escreveu, as gerais (sem disciplina) e as das disciplinas que leciona nas
    turmas do estudante. Registros de outras disciplinas ficam com os
    respectivos professores e a coordenação."""
    from apps.academics.permissions import teacher_subject_ids

    class_ids = set(Enrollment.objects.filter(student=student).values_list("class_group_id", flat=True))
    return (Q(teacher=user) | Q(subject__isnull=True)
            | Q(subject_id__in=teacher_subject_ids(user, class_ids=class_ids)))


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
        if user.role == Role.COORDENACAO.value and student:
            return reaches_student(user, student)
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
        if user.role == Role.COORDENACAO.value and student is not None:
            return reaches_student(user, student)
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
    if not class_ids or student.school_id != user.school_id:
        return False
    return bool(set(class_ids) & teacher_class_ids(user))


def require(view_ok):
    """Conveniência: acaso da negação usa PermissionDenied (HTTP 403)."""
    if not view_ok:
        raise PermissionDenied
    return True