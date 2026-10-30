"""O que acontece hoje na escola, do ponto de vista de cada perfil.

Tudo vem do que está cadastrado: quadro de horários, cardápio, calendário
oficial, atividades e avaliações. Nada é suposto: sem quadro de horários,
a tela diz que ele não foi cadastrado.
"""

from datetime import timedelta

from django.utils import timezone

from apps.core.models import Role

from .models import ClassSchedule, MealMenu


MEAL_ORDER = {key: i for i, (key, _) in enumerate(MealMenu.Meal.choices)}


def _by_meal(menus):
    """Na ordem do dia (lanche da manhã, almoço, lanche da tarde, jantar),
    não na ordem alfabética da chave."""
    return sorted(menus, key=lambda m: MEAL_ORDER.get(m.meal, 99))


def menu_for(school, day):
    return _by_meal(MealMenu.objects.filter(school=school, date=day))


def _class_ids_for(user):
    from apps.registry.access import student_of
    from apps.registry.models import Enrollment, GuardianLink

    if user.role == Role.ESTUDANTE.value:
        st = student_of(user)
        ids = [st.pk] if st else []
    elif user.role == Role.RESPONSAVEL.value:
        ids = list(GuardianLink.objects.filter(guardian=user, status="aprovado").values_list("student_id", flat=True))
    else:
        return {}
    by_class = {}
    for e in Enrollment.objects.filter(student_id__in=ids, status="ativo").select_related("student", "class_group"):
        by_class.setdefault(e.class_group, []).append(e.student)
    return by_class


def _day_items(class_ids, day):
    """Atividades com entrega e avaliações marcadas para o dia, por (turma, disciplina)."""
    from apps.pedagogy.models import Activity, Evaluation

    items = {}
    for a in Activity.objects.filter(class_group_id__in=class_ids, deadline=day, status="publicada"):
        items.setdefault((a.class_group_id, a.subject_id), []).append(f"Entrega: {a.title}")
    for ev in Evaluation.objects.filter(class_group_id__in=class_ids, date=day):
        items.setdefault((ev.class_group_id, ev.subject_id), []).append(f"Avaliação: {ev.title}")
    return items


def schedule_for(user, day=None):
    """Aulas do dia para o usuário: lista de blocos {titulo, aulas}."""
    from apps.academics.models import TeacherAssignment

    day = day or timezone.localdate()
    weekday = day.weekday()
    blocks = []
    if user.role in (Role.ESTUDANTE.value, Role.RESPONSAVEL.value):
        by_class = _class_ids_for(user)
        items = _day_items([c.pk for c in by_class], day)
        for cg, students in by_class.items():
            slots = list(ClassSchedule.objects.filter(class_group=cg, weekday=weekday)
                         .select_related("subject", "teacher"))
            for s in slots:
                s.items = items.get((cg.pk, s.subject_id), [])
            names = ", ".join(st.first_name for st in students)
            title = cg.name if user.role == Role.ESTUDANTE.value else f"{names} · {cg.name}"
            blocks.append({"title": title, "class_group": cg, "slots": slots,
                           "has_schedule": ClassSchedule.objects.filter(class_group=cg).exists()})
    elif user.role == Role.PROFESSOR.value:
        pairs = set(TeacherAssignment.objects.filter(teacher=user).values_list("class_group_id", "subject_id"))
        slots = [
            s for s in ClassSchedule.objects.filter(school=user.school, weekday=weekday)
            .select_related("subject", "class_group", "teacher")
            if s.teacher_id == user.pk or (s.teacher_id is None and (s.class_group_id, s.subject_id) in pairs)
        ]
        items = _day_items({s.class_group_id for s in slots}, day)
        for s in slots:
            s.items = items.get((s.class_group_id, s.subject_id), [])
        blocks.append({"title": "Suas aulas", "class_group": None, "slots": slots,
                       "has_schedule": bool(pairs) and ClassSchedule.objects.filter(
                           class_group_id__in={c for c, _ in pairs}).exists()})
    return blocks


def week_menu(school, monday):
    days = [monday + timedelta(days=i) for i in range(5)]
    menus = {}
    for m in MealMenu.objects.filter(school=school, date__range=(days[0], days[-1])).order_by("meal"):
        menus.setdefault(m.date, []).append(m)
    return [{"date": d, "meals": _by_meal(menus.get(d, []))} for d in days]
