"""Quem vê o quê no módulo de apoio à inclusão (sempre conferido no servidor).

| Perfil        | Ficha completa | Documentos | Plano | Orientações | Situação |
|---------------|----------------|------------|-------|-------------|----------|
| Coordenação   | do seu escopo  | baixa      | edita | vê          | vê       |
| Direção       | todas          | baixa      | edita | vê          | vê       |
| Professor     | não            | não        | não   | dos seus estudantes | não |
| Secretaria    | não            | só registra recebimento (não baixa) | não | não | situação e condições validadas |
| Responsável   | do filho com vínculo aprovado | baixa | vê o vigente e as devolutivas | — | vê |
| Estudante     | não            | não        | não   | não         | não      |
| Administração | não            | não        | não   | não         | não      |

Necessidade de conhecimento: o professor recebe estratégias, recursos e
cuidados, nunca o diagnóstico nem o laudo.
"""

from apps.core.models import Role

TEAM = (Role.COORDENACAO.value, Role.DIRECAO.value)


def _auth(user):
    return getattr(user, "is_authenticated", False)


def is_team(user):
    return _auth(user) and user.role in TEAM


def reaches(user, student):
    """Equipe pedagógica que alcança o estudante (coordenação pelo escopo)."""
    from apps.coordination.scope import reaches_student

    if not is_team(user) or student.school_id != user.school_id:
        return False
    if user.role == Role.COORDENACAO.value:
        return reaches_student(user, student)
    return True


def is_guardian(user, student):
    from apps.registry.access import guardian_of

    return _auth(user) and student.school_id == user.school_id and guardian_of(user, student)


def can_view_case(user, student):
    return reaches(user, student) or is_guardian(user, student)


def can_manage_case(user, student):
    return reaches(user, student)


def can_download(user, document):
    return can_view_case(user, document.case.student)


def can_declare(user, student):
    return is_guardian(user, student)


def is_secretaria(user, student=None):
    ok = _auth(user) and user.role == Role.SECRETARIA.value
    return ok and (student is None or student.school_id == user.school_id)


def can_register_received(user, student):
    """Secretaria ou equipe registra um documento entregue em papel."""
    return reaches(user, student) or is_secretaria(user, student)


def can_view_guidance(user, student):
    """Orientações pedagógicas: professor do estudante e equipe."""
    from apps.registry.access import teacher_of_student

    return reaches(user, student) or (_auth(user) and teacher_of_student(user, student))


def can_view_admin_status(user, student):
    return reaches(user, student) or is_secretaria(user, student)


def can_configure(user):
    return is_team(user)


def can_discard(user):
    return _auth(user) and user.role == Role.DIRECAO.value
