"""Quem vê e quem lança o quê na trajetória escolar. Toda view confere aqui, no servidor.

- **Linha do tempo** (anos, séries, resultados, notas finais e frequência): quem pode ver o histórico escolar
  consolidado, isto é, a ficha do estudante menos o professor (``registry.views_history``). Inclui a família
  com vínculo aprovado e o próprio estudante (LGPD art. 18, acesso aos próprios dados).
- **Diagnóstico, análises da escola e previsões:** só direção e coordenação (dentro da designação). São leitura
  pedagógica, como as observações: a secretaria e a administração não veem, e a família e o estudante também
  não, porque um "sinal" fora de contexto vira rótulo.
- **Lançar anos anteriores e importar planilha:** secretaria, direção e administração (dado do histórico
  oficial, trabalho de secretaria).
- **Resultado final do ano:** secretaria e direção.
- **Treinar o modelo:** direção e coordenação da escola toda. **Aprovar ou desativar o uso:** só a direção.
"""

from apps.coordination.scope import class_scope, reaches_student, student_ids
from apps.core.models import Role
from apps.registry.views_history import can_view_school_record

ANALYSTS = (Role.DIRECAO.value, Role.COORDENACAO.value)
EDITORS = (Role.SECRETARIA.value, Role.DIRECAO.value, Role.ADMIN.value)
RESULTS = (Role.SECRETARIA.value, Role.DIRECAO.value)


def can_view_timeline(user, student):
    return can_view_school_record(user, student)


def is_analyst(user):
    return user.is_authenticated and user.role in ANALYSTS and user.school_id is not None


def can_view_diagnosis(user, student):
    if not is_analyst(user) or student.school_id != user.school_id:
        return False
    return user.role == Role.DIRECAO.value or reaches_student(user, student)


def can_edit_history(user, student=None):
    ok = user.is_authenticated and user.role in EDITORS and user.school_id is not None
    return ok and (student is None or student.school_id == user.school_id)


def can_record_results(user):
    return user.is_authenticated and user.role in RESULTS and user.school_id is not None


def can_train(user):
    return is_analyst(user) and (user.role == Role.DIRECAO.value or class_scope(user) is None)


def can_approve(user):
    return user.is_authenticated and user.role == Role.DIRECAO.value and user.school_id is not None


def scope_ids(user):
    """Estudantes que entram nas análises: None = escola toda; senão os da designação da coordenação."""
    return student_ids(user) if user.role == Role.COORDENACAO.value else None
