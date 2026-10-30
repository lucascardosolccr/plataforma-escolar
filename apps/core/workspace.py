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


def setup_steps(user):
    """Primeiros passos de uma escola nova, na ordem em que um depende do outro.

    Cada passo diz se já está feito (pelo que existe no banco) e leva à tela
    de cadastro quando o perfil pode fazê-lo. Sem esta lista, a secretaria
    abria uma plataforma vazia sem saber por onde começar.
    """
    from django.urls import reverse

    from apps.academics.models import ClassGroup, SchoolYear, Subject, TeacherAssignment
    from apps.pedagogy.models import AcademicRule
    from apps.registry.models import Enrollment, Student

    school = user.school
    is_admin = user.role == Role.ADMIN.value
    steps = [
        ("Ano letivo", SchoolYear.objects.filter(school=school).exists(), "school_year_create",
         "O ano a que turmas e matrículas pertencem."),
        ("Disciplinas", Subject.objects.filter(school=school).exists(), "subject_create",
         "Matemática, Português e as demais."),
        ("Turmas", ClassGroup.objects.filter(school=school).exists(), "class_group_create",
         "Cada turma com série e turno."),
        ("Contas dos professores", User.objects.filter(school=school, role=Role.PROFESSOR.value).exists(),
         "user_create" if is_admin else None,
         "Criadas pela administração." if not is_admin else "Uma conta por professor."),
        ("Atribuições", TeacherAssignment.objects.filter(school=school).exists(), "assignment_create",
         "Quem leciona qual disciplina em qual turma."),
        ("Estudantes", Student.objects.filter(school=school).exists(), "student_create",
         "A ficha de cada estudante."),
        ("Matrículas", Enrollment.objects.filter(school=school).exists(), "enrollment_create",
         "Cada estudante na sua turma."),
        ("Regras de média", AcademicRule.objects.filter(school=school).exists(), "pedagogy:config_edit",
         "Fórmula e nota de aprovação de cada disciplina."),
    ]
    out = [{"label": label, "done": done, "url": reverse(name) if name else None, "hint": hint}
           for label, done, name, hint in steps]
    return out if not all(s["done"] for s in out) else []


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


def today_block(user, today):
    """Rotina do dia (aulas, cardápio, calendário), igual para a tela inicial
    de todos os perfis; as aulas só para quem tem turma (estudante, família,
    professor)."""
    from apps.rotina.services import menu_for, schedule_for
    from apps.school_calendar.services import countdown

    cd = countdown(user.school, today)
    block = {"day": today, "now": timezone.localtime().time(), "menu": menu_for(user.school, today),
             "countdown": cd, "schedule": None, "no_class_reason": ""}
    if user.role in (Role.ESTUDANTE.value, Role.RESPONSAVEL.value, Role.PROFESSOR.value):
        block["schedule"] = schedule_for(user, today)
        if cd.get("published") and not cd.get("is_school_day", True):
            from apps.school_calendar.services import events_for_user

            off = [e for e in events_for_user(user, today, today) if e.no_classes]
            block["no_class_reason"] = (f"Sem aula hoje: {off[0].title}." if off
                                        else "Hoje não é dia letivo pelo calendário da escola.")
    return block


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
        if students:
            # Progresso do próprio estudante: últimas notas publicadas e
            # frequência (nada de comparação com colegas).
            from apps.analytics.services import attendance_stats
            from apps.pedagogy.models import Evaluation, Grade

            student = students[0]
            data["recent_grades"] = list(
                Grade.objects.filter(student=student, value__isnull=False,
                                     evaluation__status=Evaluation.Status.PUBLISHED)
                .select_related("evaluation__subject").order_by("-evaluation__date", "-pk")[:4]
            )
            data["attendance"] = attendance_stats(student)
            data["student_pk"] = student.pk

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
        if role in (Role.SECRETARIA.value, Role.ADMIN.value):
            data["setup"] = setup_steps(user)
            data["setup_done"] = sum(1 for s in data["setup"] if s["done"])
        if role == Role.ADMIN.value:
            data["active_users"] = User.objects.filter(
                school=user.school, is_active=True
            ).count()
        data["students_total"] = Student.objects.filter(school=user.school).count()
        data["announcements"] = _recent_announcements(user)
        if role in (Role.SECRETARIA.value, Role.ADMIN.value, Role.DIRECAO.value):
            from django.db.models import Exists, OuterRef, Q

            from apps.registry.models import PhotoException, StudentApplication

            data["students_without_photo"] = (
                Student.objects.filter(school=user.school, status="ativo")
                .filter(Q(photo="") | Q(photo__isnull=True))
                .exclude(Exists(PhotoException.objects.filter(student=OuterRef("pk"))))
                .count()
            )
            data["applications_pending"] = StudentApplication.objects.filter(
                school=user.school, status=StudentApplication.Status.SUBMITTED
            ).count()
    data["today_block"] = today_block(user, today)
    if role != Role.ESTUDANTE.value:
        from .views_photo import has_photo, photo_exempt

        data["my_photo_missing"] = not has_photo(user) and not photo_exempt(user)
    return data
