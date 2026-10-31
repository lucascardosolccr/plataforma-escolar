"""Quem vê o quê no EIA-Cognitio (sempre no servidor).

- Professor: estudantes e turmas dos seus pares turma+disciplina, só nas disciplinas
  que leciona.
- Coordenação: turmas e estudantes do seu escopo, todas as disciplinas.
- Direção: visão institucional agregada; pode abrir o mapa individual (consulta
  registrada na auditoria).
- Secretaria, administração, família e estudante: sem acesso nesta versão (o mapa
  de competências é instrumento pedagógico interno; a família continua vendo notas,
  frequência e devolutivas nas telas próprias).
"""

from apps.core.models import Role

ROLES = (Role.PROFESSOR.value, Role.COORDENACAO.value, Role.DIRECAO.value)


def can_use(user):
    return getattr(user, "is_authenticated", False) and user.role in ROLES


def class_subjects(user, class_group):
    """Disciplinas que a pessoa pode analisar na turma (None = todas)."""
    from apps.academics.permissions import teacher_pairs
    from apps.coordination.scope import reaches_class

    if not can_use(user) or class_group.school_id != user.school_id:
        return set()
    if user.role == Role.PROFESSOR.value:
        return {s for c, s in teacher_pairs(user) if c == class_group.pk}
    if user.role == Role.COORDENACAO.value and not reaches_class(user, class_group):
        return set()
    return None


def can_view_class(user, class_group):
    subjects = class_subjects(user, class_group)
    return subjects is None or bool(subjects)


def student_subjects(user, student):
    """Disciplinas que a pessoa pode ver do estudante (None = todas; set() = nenhuma)."""
    from apps.academics.permissions import teacher_pairs
    from apps.coordination.scope import reaches_student
    from apps.registry.models import Enrollment

    if not can_use(user) or student.school_id != user.school_id:
        return set()
    if user.role == Role.PROFESSOR.value:
        classes = set(Enrollment.objects.filter(student=student, status="ativo").values_list("class_group_id", flat=True))
        return {s for c, s in teacher_pairs(user) if c in classes}
    if user.role == Role.COORDENACAO.value and not reaches_student(user, student):
        return set()
    return None


def can_teach(user, class_group, subject):
    from apps.academics.permissions import teaches

    return user.role == Role.PROFESSOR.value and teaches(user, class_group, subject, edit=True)
