"""Dados da tela inicial ("Hoje"), por perfil.

Cada perfil abre a plataforma e vê primeiro o que pede ação: a família, os
próximos prazos de cada filho; o professor, as turmas e os prazos da semana;
a secretaria, as pendências. Tudo é contado a partir das mesmas funções que
as telas de destino usam — nenhum número daqui é calculado de outro jeito,
e nada é estimado ou simulado.
"""

from datetime import timedelta

from django.utils import timezone

from .models import Role, User

OPEN_STATES = ("a_vencer", "pendente")


def _recent_announcements(user, limit=3):
    from apps.communication.access import announcement_q, can_view_announcements
    from apps.communication.models import Announcement, AnnouncementRead

    if not can_view_announcements(user):
        return []
    items = list(
        Announcement.objects.filter(announcement_q(user), school=user.school)
        .select_related("class_group")
        .order_by("-created_at")[:limit]
    )
    lidos = set(
        AnnouncementRead.objects.filter(announcement__in=items, user=user).values_list(
            "announcement_id", flat=True
        )
    )
    for a in items:
        a.unread = a.pk not in lidos
    return items


def _children_summary(rows, children):
    """Para cada filho: tarefas em aberto, a mais próxima e as novas."""
    from apps.pedagogy.views import NEW_DAYS

    novo_desde = timezone.localdate() - timedelta(days=NEW_DAYS - 1)
    resumo = []
    for child in children:
        mine = [r for r in rows if r["student"].pk == child.pk]
        abertas = sorted(
            (r for r in mine if r["state"] in OPEN_STATES),
            key=lambda r: r["activity"].deadline or timezone.localdate() + timedelta(days=3650),
        )
        resumo.append({
            "student": child,
            "open_count": len(abertas),
            "due_soon": sum(1 for r in abertas if r["state"] == "a_vencer"),
            "new_count": sum(
                1 for r in mine
                if r["state"] != "cancelada" and r["activity"].published_date >= novo_desde
            ),
            "next": abertas[:3],
        })
    return resumo


def build(user):
    from apps.registry.models import GuardianLink, Student

    today = timezone.localdate()
    data = {"today": today}
    role = user.role

    if role == Role.RESPONSAVEL.value:
        from apps.pedagogy.views import _family_rows

        rows, children = _family_rows(user)
        data["children"] = _children_summary(rows, children)
        data["pending_links"] = GuardianLink.objects.filter(
            guardian=user, status="pendente"
        ).count()
        data["announcements"] = _recent_announcements(user)

    elif role == Role.ESTUDANTE.value:
        from apps.pedagogy.views import _student_own_rows

        rows, students = _student_own_rows(user)
        data["own"] = _children_summary(rows, students)[0] if students else None
        data["announcements"] = _recent_announcements(user)

    elif role == Role.PROFESSOR.value:
        from apps.academics.models import TeacherAssignment
        from apps.pedagogy.models import Activity, Evaluation
        from apps.registry.models import Enrollment
        from django.db.models import Count, Q

        atribuicoes = list(
            TeacherAssignment.objects.filter(teacher=user, school=user.school)
            .select_related("class_group", "subject")
            .order_by("class_group__name", "subject__name")
        )
        turmas = {a.class_group_id for a in atribuicoes}
        alunos = dict(
            Enrollment.objects.filter(class_group_id__in=turmas, status="ativo")
            .values_list("class_group_id")
            .annotate(n=Count("id"))
        )
        for a in atribuicoes:
            a.student_count = alunos.get(a.class_group_id, 0)
        data["assignments"] = atribuicoes
        # Uma linha por turma (não por turma+disciplina) com a chamada de hoje:
        # a tarefa diária que mais importa ao professor.
        from apps.pedagogy.models import AttendanceRecord

        feitas = set(
            AttendanceRecord.objects.filter(class_group_id__in=turmas, date=today)
            .values_list("class_group_id", flat=True).distinct()
        )
        por_turma = {}
        for a in atribuicoes:
            t = por_turma.setdefault(a.class_group_id, {
                "class_group": a.class_group, "subjects": [], "students": a.student_count,
                "attendance_today": a.class_group_id in feitas,
            })
            t["subjects"].append(a.subject)
        data["classes"] = list(por_turma.values())
        data["school_day"] = today.weekday() < 5
        data["attendance_pending"] = sum(1 for t in data["classes"] if not t["attendance_today"])
        pares = Q(pk__in=[])
        for a in atribuicoes:
            pares |= Q(class_group_id=a.class_group_id, subject_id=a.subject_id)
        data["due_this_week"] = list(
            Activity.objects.filter(
                pares,
                status=Activity.Status.PUBLISHED,
                deadline__gte=today,
                deadline__lte=today + timedelta(days=7),
            )
            .select_related("class_group", "subject")
            .order_by("deadline")[:6]
        )
        data["draft_activities"] = Activity.objects.filter(
            pares, status=Activity.Status.DRAFT
        ).count()
        data["draft_evaluations"] = Evaluation.objects.filter(
            pares, status=Evaluation.Status.DRAFT
        ).count()

    elif role in (Role.SECRETARIA.value, Role.ADMIN.value, Role.COORDENACAO.value,
                  Role.DIRECAO.value):
        from apps.analytics.services import institutional_indicators
        from apps.pedagogy.models import AbsenceJustification

        data["indicators"] = institutional_indicators(user.school)
        data["justifications_pending"] = AbsenceJustification.objects.filter(
            school=user.school,
            status__in=[
                AbsenceJustification.Status.RECEIVED,
                AbsenceJustification.Status.UNDER_REVIEW,
            ],
        ).count()
        from apps.communication.models import ServiceRequest

        data["requests_open"] = ServiceRequest.objects.filter(
            school=user.school,
            status__in=[ServiceRequest.Status.RECEIVED, ServiceRequest.Status.UNDER_REVIEW],
        ).count()
        if role == Role.ADMIN.value:
            data["active_users"] = User.objects.filter(
                school=user.school, is_active=True
            ).count()
        data["students_total"] = Student.objects.filter(school=user.school).count()
        data["announcements"] = _recent_announcements(user)
    return data
