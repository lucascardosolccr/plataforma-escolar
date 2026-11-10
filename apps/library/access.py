"""Quem faz o quê na biblioteca.

- **consultam o acervo:** todos da escola (equipe, estudantes e famílias);
- **operam o balcão** (empréstimo, devolução, cadastro de livros): direção, coordenação, secretaria e
  administração, mais quem a escola indicar nas regras da biblioteca (professor ou funcionário);
- **mudam as regras:** direção, secretaria e administração;
- **o que cada estudante leu** é visto só por ele, pelos responsáveis com vínculo e por quem opera o balcão.
  O professor vê os totais da turma, não a lista de cada um.
"""

from apps.core.models import Role

MANAGERS = (Role.DIRECAO.value, Role.COORDENACAO.value, Role.SECRETARIA.value, Role.ADMIN.value)
CONFIGURE = (Role.DIRECAO.value, Role.SECRETARIA.value, Role.ADMIN.value)
STAFF = MANAGERS + (Role.PROFESSOR.value,)
FAMILY = (Role.RESPONSAVEL.value, Role.ESTUDANTE.value)


def settings_for(school):
    from .models import LibrarySettings

    return LibrarySettings.objects.get_or_create(school=school)[0]


def can_browse(user):
    return bool(user.school_id) and user.role in STAFF + FAMILY


def can_operate(user):
    if not user.school_id:
        return False
    if user.role in MANAGERS:
        return True
    if user.role != Role.PROFESSOR.value:
        return False
    return settings_for(user.school).librarians.filter(pk=user.pk).exists()


def can_configure(user):
    return bool(user.school_id) and user.role in CONFIGURE


def own_students(user):
    """Estudantes de quem a pessoa acompanha os empréstimos: os filhos (responsável) ou ela mesma (estudante)."""
    from apps.registry.access import student_of
    from apps.registry.models import GuardianLink

    if user.role == Role.RESPONSAVEL.value:
        return [ln.student for ln in GuardianLink.objects.filter(guardian=user, status="aprovado",
                                                                 student__school=user.school)
                .select_related("student").order_by("student__first_name")]
    if user.role == Role.ESTUDANTE.value:
        own = student_of(user)
        return [own] if own else []
    return []


def can_act_for(user, student):
    """Reservar, renovar ou cancelar em nome deste estudante."""
    return student.school_id == user.school_id and (
        can_operate(user) or any(s.pk == student.pk for s in own_students(user)))
