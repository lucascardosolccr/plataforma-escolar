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
from django.db.models import Q

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
    from apps.academics.permissions import teacher_class_ids

    return list(teacher_class_ids(user))


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


def _own_student(user):
    from apps.registry.access import student_of

    return student_of(user)


def _scope_q(class_ids, student_ids):
    """Comunicados cuja abrangência alcança estas turmas/estes estudantes.

    ``student_ids=None`` deixa os individuais de fora.
    """
    q = Q(scope=Announcement.Scope.INSTITUCIONAL) | Q(
        scope=Announcement.Scope.TURMA, class_group_id__in=list(class_ids)
    )
    if student_ids is not None:
        q |= Q(scope=Announcement.Scope.INDIVIDUAL, student_id__in=list(student_ids))
    return q


FAMILY_AUDIENCE = (Announcement.Audience.FAMILIA, Announcement.Audience.TODOS)
STAFF_AUDIENCE = (Announcement.Audience.EQUIPE, Announcement.Audience.TODOS)


def announcement_q(user):
    """Filtro único de "quem vê qual comunicado": lista, detalhe, prontuário
    e notificações usam a mesma regra.

    - Gestão (direção, coordenação, secretaria, administração): todos da
      escola, pois administra os comunicados.
    - Professor: institucionais, os das próprias turmas e os individuais dos
      próprios estudantes — qualquer que seja o público. Ser "da equipe" não
      dá acesso a comunicado individual de estudante de outra turma.
    - Responsável: público família/todos, dos filhos com vínculo aprovado.
    - Estudante: público família/todos, institucionais e da própria turma.
      Os individuais são dirigidos aos responsáveis e não aparecem a ele.
    """
    if not can_view_announcements(user):
        return Q(pk__in=[])
    if user.role in MANAGE_STAFF:
        return Q()
    if user.role == Role.PROFESSOR.value:
        return _scope_q(_teacher_class_ids(user), _teacher_student_ids(user))
    if user.role == Role.RESPONSAVEL.value:
        return Q(audience__in=FAMILY_AUDIENCE) & _scope_q(
            _guardian_class_ids(user), _guardian_child_ids(user)
        )
    if user.role == Role.ESTUDANTE.value:
        own = _own_student(user)
        if own is None:
            return Q(pk__in=[])
        class_ids = Enrollment.objects.filter(student=own, status="ativo").values_list(
            "class_group_id", flat=True
        )
        return Q(audience__in=FAMILY_AUDIENCE) & _scope_q(class_ids, None)
    return Q(pk__in=[])


def can_view_announcement(user, announcement):
    if not can_view_announcements(user) or announcement.school_id != user.school_id:
        return False
    return Announcement.objects.filter(
        announcement_q(user), pk=announcement.pk
    ).exists()


def announcement_recipients(announcement):
    """Quem é avisado de um comunicado: exatamente quem pode abri-lo.

    Antes, o público "todos" ignorava a abrangência: um comunicado individual
    sobre um estudante avisava todas as famílias da escola, com o começo do
    texto na notificação.
    """
    from apps.registry.models import Student

    ann = announcement
    users = User.objects.filter(school=ann.school, is_active=True)
    ids = set()

    if ann.scope == Announcement.Scope.INSTITUCIONAL:
        student_ids = None  # todos
    elif ann.scope == Announcement.Scope.TURMA:
        student_ids = set(
            Enrollment.objects.filter(
                class_group_id=ann.class_group_id, status="ativo"
            ).values_list("student_id", flat=True)
        )
    else:
        student_ids = {ann.student_id} if ann.student_id else set()

    if ann.audience in STAFF_AUDIENCE:
        ids |= set(users.filter(role__in=MANAGE_STAFF).values_list("pk", flat=True))
        teachers = TeacherAssignment.objects.filter(school=ann.school)
        if ann.scope == Announcement.Scope.TURMA:
            teachers = teachers.filter(class_group_id=ann.class_group_id)
        elif ann.scope == Announcement.Scope.INDIVIDUAL:
            teachers = teachers.filter(
                class_group_id__in=Enrollment.objects.filter(
                    student_id__in=student_ids, status="ativo"
                ).values("class_group_id")
            )
        ids |= set(
            users.filter(
                role=Role.PROFESSOR.value,
                pk__in=teachers.values("teacher_id"),
            ).values_list("pk", flat=True)
        )

    if ann.audience in FAMILY_AUDIENCE:
        links = GuardianLink.objects.filter(school=ann.school, status="aprovado")
        if student_ids is not None:
            links = links.filter(student_id__in=student_ids)
        ids |= set(
            users.filter(
                role=Role.RESPONSAVEL.value, pk__in=links.values("guardian_id")
            ).values_list("pk", flat=True)
        )
        if ann.scope != Announcement.Scope.INDIVIDUAL:
            contas = Student.objects.filter(school=ann.school, user__isnull=False)
            if student_ids is not None:
                contas = contas.filter(pk__in=student_ids)
            ids |= set(
                users.filter(
                    role=Role.ESTUDANTE.value, pk__in=contas.values("user_id")
                ).values_list("pk", flat=True)
            )

    ids.discard(ann.created_by_id)
    return users.filter(pk__in=ids)


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