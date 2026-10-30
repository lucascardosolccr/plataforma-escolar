"""Views do calendário escolar unificado.

Não cria nenhum modelo novo: consome Activity, Evaluation, GroupWork,
Occurrence e AbsenceJustification, que já possuem datas. A exibição respeita
o escopo RBAC de cada origem.
"""

import datetime as dt

from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import ClassGroup, Subject, TeacherAssignment
from apps.core.models import Role
from apps.core.params import id_param
from apps.pedagogy.models import (
    AbsenceJustification,
    Activity,
    Evaluation,
    GroupWork,
    Occurrence,
)
from apps.registry.access import student_of
from apps.registry.models import Enrollment, GuardianLink, Student

from . import access


def _parse_date(value):
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _user_student_ids(user):
    """Estudantes dentro do escopo do usuário (vínculos aprovados, ou ele mesmo)."""
    role = user.role
    if role == Role.RESPONSAVEL.value:
        return list(
            GuardianLink.objects.filter(
                guardian=user, status="aprovado"
            ).values_list("student_id", flat=True)
        )
    if role == Role.ESTUDANTE.value:
        own = student_of(user)
        return [own.pk] if own is not None else []
    return []


def _user_class_ids(user):
    """Turmas dentro do escopo do usuário."""
    role = user.role
    if role == Role.PROFESSOR.value:
        return list(
            TeacherAssignment.objects.filter(teacher=user, school=user.school)
            .values_list("class_group_id", flat=True)
            .distinct()
        )
    if role == Role.RESPONSAVEL.value:
        student_ids = _user_student_ids(user)
        return list(
            Enrollment.objects.filter(student_id__in=student_ids)
            .values_list("class_group_id", flat=True)
            .distinct()
        )
    if role == Role.ESTUDANTE.value:
        student_ids = _user_student_ids(user)
        return list(
            Enrollment.objects.filter(student_id__in=student_ids)
            .values_list("class_group_id", flat=True)
            .distinct()
        )
    return []


def _student_suffix(scope, item, student_filter=None):
    """"· Ana" para a família saber a qual filho o item pertence."""
    if student_filter is not None:
        return f" · {student_filter}"
    names = scope.reached_students(item)
    if not names:
        return ""
    return " · " + ", ".join(str(student) for student in names)


def _event_in_range(event, start, end):
    event_start = event["date"]
    event_end = event.get("date_end", event_start)
    if start and event_end < start:
        return False
    if end and event_start > end:
        return False
    return True


# Sem período escolhido, o calendário mostra uma janela em torno de hoje.
# Antes ele carregava todo o histórico da escola a cada acesso.
DEFAULT_DAYS_BEFORE = 7
DEFAULT_DAYS_AFTER = 45


def _due_in_range(start, end):
    """Atividade/trabalho cuja data exibida (entrega, ou publicação se não
    houver prazo) cai no período — o mesmo critério de ``_event_in_range``."""
    com_prazo = Q(deadline__isnull=False)
    sem_prazo = Q(deadline__isnull=True)
    if start:
        com_prazo &= Q(deadline__gte=start)
        sem_prazo &= Q(published_date__gte=start)
    if end:
        com_prazo &= Q(deadline__lte=end)
        sem_prazo &= Q(published_date__lte=end)
    return com_prazo | sem_prazo


def _scoped(qs, user, model=None):
    """Restringe no banco às turmas do usuário antes da checagem fina.

    A checagem por item (``CalendarScope``) continua decidindo; isto só evita
    trazer da escola inteira o que nunca passaria por ela.
    """
    if user.role in (Role.RESPONSAVEL.value, Role.ESTUDANTE.value):
        qs = qs.filter(class_group_id__in=_user_class_ids(user))
        if model is not None:
            qs = qs.filter(model.family_visible_q())
    elif user.role == Role.PROFESSOR.value:
        qs = qs.filter(class_group_id__in=_user_class_ids(user))
    return qs


def _collect_events(user, start, end, class_filter=None, subject_filter=None,
                    kind_filter=None, student_filter=None):
    """Coleta eventos das fontes existentes dentro do escopo do usuário."""
    events = []
    today = timezone.localdate()
    scope = access.CalendarScope(user)

    # ---------- Atividades ----------
    if kind_filter is None or kind_filter == "activity":
        qs = _scoped(
            Activity.objects.filter(
                _due_in_range(start, end), school=user.school, published_date__lte=today
            ).exclude(status=Activity.Status.DRAFT),
            user,
            Activity,
        ).select_related("class_group", "subject", "created_by")
        if class_filter:
            qs = qs.filter(class_group=class_filter)
        if subject_filter:
            qs = qs.filter(subject=subject_filter)
        for act in qs:
            show = scope.activity_visible(act)
            if not show:
                continue
            if student_filter and not scope.item_reaches_student(act, student_filter):
                continue
            events.append({
                "kind": "activity",
                "kind_label": "Atividade de casa",
                "title": act.title,
                "date": act.deadline or act.published_date,
                "date_label": "entrega" if act.deadline else "publicação",
                "subtitle": f"{act.class_group.name} · {act.subject.name}"
                + _student_suffix(scope, act, student_filter),
                "url": reverse("pedagogy:activity_detail", args=[act.pk]),
                "school_id": act.school_id,
                "state": act.family_situation()[0],
                "state_label": act.family_situation()[1],
            })

    # ---------- Trabalhos em grupo ----------
    if kind_filter is None or kind_filter == "group_work":
        qs = _scoped(
            GroupWork.objects.filter(
                _due_in_range(start, end), school=user.school, published_date__lte=today
            ).exclude(status=GroupWork.Status.DRAFT),
            user,
            GroupWork,
        ).select_related("class_group", "subject", "created_by")
        if class_filter:
            qs = qs.filter(class_group=class_filter)
        if subject_filter:
            qs = qs.filter(subject=subject_filter)
        for gw in qs:
            show = scope.group_work_visible(gw)
            if not show:
                continue
            if student_filter and not scope.item_reaches_student(gw, student_filter):
                continue
            events.append({
                "kind": "group_work",
                "kind_label": "Trabalho em grupo",
                "title": gw.title,
                "date": gw.deadline or gw.published_date,
                "date_label": "entrega" if gw.deadline else "publicação",
                "subtitle": f"{gw.class_group.name} · {gw.subject.name} (grupo)"
                + _student_suffix(scope, gw, student_filter),
                "url": reverse("pedagogy:group_work_detail", args=[gw.pk]),
                "school_id": gw.school_id,
                "state": gw.situation()[0],
                "state_label": gw.situation()[1],
            })

    # ---------- Avaliações ----------
    if kind_filter is None or kind_filter == "evaluation":
        qs = _scoped(
            Evaluation.objects.filter(
                school=user.school, status=Evaluation.Status.PUBLISHED
            ),
            user,
        ).select_related("class_group", "subject")
        if start:
            qs = qs.filter(date__gte=start)
        if end:
            qs = qs.filter(date__lte=end)
        if class_filter:
            qs = qs.filter(class_group=class_filter)
        if subject_filter:
            qs = qs.filter(subject=subject_filter)
        for ev in qs:
            show = scope.evaluation_visible(ev)
            if not show:
                continue
            if student_filter and not scope.item_reaches_student(ev, student_filter):
                continue
            events.append({
                "kind": "evaluation",
                "kind_label": "Avaliação",
                "title": ev.title,
                "date": ev.date,
                "date_label": "avaliação",
                "subtitle": f"{ev.class_group.name} · {ev.subject.name}"
                + _student_suffix(scope, ev, student_filter),
                "url": reverse("pedagogy:evaluation_list"),
                "school_id": ev.school_id,
            })

    # ---------- Ocorrências ----------
    if kind_filter is None or kind_filter == "occurrence":
        qs = Occurrence.objects.filter(school=user.school).select_related("student")
        if user.role in (Role.RESPONSAVEL.value, Role.ESTUDANTE.value):
            qs = qs.filter(student_id__in=_user_student_ids(user))
        if start:
            qs = qs.filter(date__gte=start)
        if end:
            qs = qs.filter(date__lte=end)
        if class_filter:
            qs = qs.filter(
                student__enrollments__class_group=class_filter
            ).distinct()
        if student_filter:
            qs = qs.filter(student=student_filter)
        for oc in qs:
            if not scope.occurrence_visible(oc.student):
                continue
            events.append({
                "kind": "occurrence",
                "kind_label": "Ocorrência",
                "title": f"Ocorrência: {oc.description[:60]}",
                "date": oc.date,
                "date_label": "registro",
                "subtitle": f"{oc.student} · {oc.get_status_display()}",
                "url": reverse("pedagogy:occurrence_detail", args=[oc.pk]),
                "school_id": oc.school_id,
            })

    # ---------- Justificativas de falta ----------
    if kind_filter is None or kind_filter == "justification":
        qs = AbsenceJustification.objects.filter(school=user.school).select_related(
            "student"
        )
        if user.role in (Role.RESPONSAVEL.value, Role.ESTUDANTE.value):
            qs = qs.filter(student_id__in=_user_student_ids(user))
        # Intervalo: entra se encostar no período, como em _event_in_range.
        if start:
            qs = qs.filter(end_date__gte=start)
        if end:
            qs = qs.filter(start_date__lte=end)
        if class_filter:
            qs = qs.filter(class_group=class_filter)
        if student_filter:
            qs = qs.filter(student=student_filter)
        for j in qs:
            if not scope.justification_visible(j.student):
                continue
            label_start = j.start_date.strftime("%d/%m")
            label_end = j.end_date.strftime("%d/%m")
            events.append({
                "kind": "justification",
                "kind_label": "Justificativa de falta",
                "title": f"Justificativa de falta: {j.reason[:50]}",
                "date": j.start_date,
                "date_end": j.end_date,
                "date_label": f"falta {label_start}–{label_end}",
                "subtitle": f"{j.student} · {j.get_status_display()}",
                "url": reverse("pedagogy:justification_list"),
                "school_id": j.school_id,
            })

    # ---------- Calendário oficial (feriados, férias, reuniões...) ----------
    if kind_filter is None or kind_filter == "school":
        from .services import events_for_user

        for ev in events_for_user(user, start or today, end or today + dt.timedelta(days=365)):
            when = ev.start.strftime("%d/%m") + (f" a {ev.end:%d/%m}" if ev.end and ev.end != ev.start else "")
            events.append({
                "kind": "school",
                "kind_label": ev.get_kind_display(),
                "title": ev.title,
                "date": max(ev.start, start) if start else ev.start,
                "date_label": when + (" · sem aula" if ev.no_classes else ""),
                "subtitle": ev.description or ("Só a equipe" if ev.audience == "equipe" else "Calendário escolar"),
                "url": "",
                "school_id": ev.school_id,
            })

    # Filtro por período (um intervalo como o de uma justificativa conta se
    # encostar no período, não só se começar dentro dele).
    if start or end:
        events = [e for e in events if _event_in_range(e, start, end)]

    events.sort(key=lambda e: (e["date"], e["title"]))
    return events


KIND_CHOICES = [
    ("school", "Calendário escolar"),
    ("activity", "Atividade de casa"),
    ("group_work", "Trabalho em grupo"),
    ("evaluation", "Avaliação"),
    ("occurrence", "Ocorrência"),
    ("justification", "Justificativa de falta"),
]


def calendar_index(request):
    if not access.can_view_calendar(request.user):
        raise PermissionDenied

    view_mode = request.GET.get("ver", "agenda")
    start = _parse_date(request.GET.get("start"))
    end = _parse_date(request.GET.get("end"))
    month_ref = None
    if view_mode == "mes":
        month_ref = _parse_date((request.GET.get("mes") or "") + "-01") or timezone.localdate().replace(day=1)
        start = month_ref.replace(day=1)
        end = (start + dt.timedelta(days=32)).replace(day=1) - dt.timedelta(days=1)
    elif view_mode == "semana":
        ref = _parse_date(request.GET.get("semana")) or timezone.localdate()
        start = ref - dt.timedelta(days=ref.weekday())
        end = start + dt.timedelta(days=6)
    else:
        view_mode = "agenda"
    default_window = start is None and end is None
    if default_window:
        hoje = timezone.localdate()
        start = hoje - dt.timedelta(days=DEFAULT_DAYS_BEFORE)
        end = hoje + dt.timedelta(days=DEFAULT_DAYS_AFTER)

    class_filter = None
    subject_filter = None
    kind_filter = request.GET.get("type") or None
    if kind_filter not in dict(KIND_CHOICES):
        kind_filter = None
    student_filter = None

    if id_param(request, "class"):
        class_filter = get_object_or_404(
            ClassGroup, pk=id_param(request, "class"), school=request.user.school
        )
    if id_param(request, "subject"):
        subject_filter = get_object_or_404(
            Subject, pk=id_param(request, "subject"), school=request.user.school
        )
    if id_param(request, "student"):
        student_filter = get_object_or_404(
            Student, pk=id_param(request, "student"), school=request.user.school
        )
        if request.user.role == Role.RESPONSAVEL.value:
            if not GuardianLink.objects.filter(
                guardian=request.user, student=student_filter, status="aprovado"
            ).exists():
                raise PermissionDenied
        elif request.user.role == Role.ESTUDANTE.value:
            own = student_of(request.user)
            if own is None or own.pk != student_filter.pk:
                raise PermissionDenied

    events = _collect_events(
        request.user, start, end, class_filter, subject_filter,
        kind_filter, student_filter,
    )

    classes = ClassGroup.objects.filter(school=request.user.school).order_by("name")
    subjects = Subject.objects.filter(school=request.user.school).order_by("name")
    if request.user.role == Role.PROFESSOR.value:
        assigned = TeacherAssignment.objects.filter(teacher=request.user)
        classes = classes.filter(pk__in=assigned.values("class_group_id"))
        subjects = subjects.filter(pk__in=assigned.values("subject_id"))
    elif request.user.role in (Role.RESPONSAVEL.value, Role.ESTUDANTE.value):
        # A família só escolhe entre as turmas dos próprios estudantes; as
        # demais não aparecem nem como opção de filtro.
        classes = classes.filter(pk__in=_user_class_ids(request.user))

    students = None
    if request.user.role in (
        Role.ADMIN.value, Role.DIRECAO.value, Role.COORDENACAO.value,
        Role.SECRETARIA.value, Role.RESPONSAVEL.value,
    ):
        students_qs = Student.objects.filter(school=request.user.school)
        if request.user.role == Role.RESPONSAVEL.value:
            sid = list(
                GuardianLink.objects.filter(
                    guardian=request.user, status="aprovado"
                ).values_list("student_id", flat=True)
            )
            students_qs = students_qs.filter(pk__in=sid)
        students = students_qs.order_by("first_name", "last_name")

    by_date = {}
    for e in events:
        by_date.setdefault(e["date"], []).append(e)
    days = [{"date": day, "events": by_date[day]} for day in sorted(by_date)]
    month = None
    if view_mode == "mes":
        from .views_official import month_grid

        month = month_grid(request.user, month_ref, [e for e in events if e["kind"] != "school"])
    elif view_mode == "semana":
        days = [{"date": start + dt.timedelta(days=i), "events": by_date.get(start + dt.timedelta(days=i), [])}
                for i in range(7)]
    from .services import countdown
    from .views_official import can_manage_calendar

    return render(
        request,
        "school_calendar/index.html",
        {
            "events": events,
            "days": days,
            "start": start,
            "end": end,
            "default_window": default_window,
            "classes": classes,
            "subjects": subjects,
            "students": students,
            "class_filter": class_filter,
            "subject_filter": subject_filter,
            "student_filter": student_filter,
            "kind_filter": kind_filter,
            "kind_choices": KIND_CHOICES,
            "today": timezone.localdate(),
            "view_mode": view_mode,
            "month": month,
            "week_prev": (start - dt.timedelta(days=7)).isoformat() if view_mode == "semana" else "",
            "week_next": (start + dt.timedelta(days=7)).isoformat() if view_mode == "semana" else "",
            "summary": countdown(request.user.school),
            "can_manage_calendar": can_manage_calendar(request.user),
        },
    )
