"""Rótulo das listas de estudantes nos formulários.

Com dois estudantes de mesmo nome (aconteceu na escola de demonstração: duas
"Ingrid Santana", em turmas diferentes), a lista só com o nome não deixa
saber quem é quem, e a reunião ou a ocorrência podia ir para o estudante, e
para a família, errados. O rótulo leva a turma atual.
"""


def label_students_with_class(field):
    """Faz as opções do campo aparecerem como "Nome — Turma".

    Uma consulta para a lista inteira (não uma por opção)."""
    from .models import Enrollment

    classes = {}
    for sid, name in Enrollment.objects.filter(
        student__in=field.queryset, status="ativo"
    ).values_list("student_id", "class_group__name").order_by("started_on"):
        classes[sid] = name
    field.label_from_instance = lambda s: f"{s} — {classes[s.pk]}" if s.pk in classes else str(s)
    return field
