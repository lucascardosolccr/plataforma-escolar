import random
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Avg, Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.academics.models import ClassGroup, SchoolYear, TeacherAssignment
from apps.communication.services import (
    announce_publication,
    notify_attendance_limit,
    notify_evaluation_published,
    notify_justification_resolved,
    notify_publication_canceled,
)
from apps.core.params import id_param
from apps.core.models import AuditLog, Role, create_audit_log
from apps.core.pagination import paginate
from apps.core.uploads import attachment_content_type
from apps.registry.models import Enrollment, GuardianLink, Student

from . import access as acc
from .forms import (
    AbsenceJustificationForm,
    AcademicRuleForm,
    ActivityCancelForm,
    ActivityForm,
    GroupWorkCancelForm,
    GroupWorkForm,
    WorkGroupForm,
    AttendanceBatchForm,
    EvaluationForm,
    GradeBatchForm,
    InterventionPlanForm,
    JustificationResolutionForm,
    OccurrenceForm,
    OccurrenceUpdateForm,
    PedagogicalObservationForm,
    PlanNoteForm,
    SchoolConfigForm,
)
from .models import (
    AbsenceJustification,
    AcademicRule,
    Activity,
    ActivityAttachment,
    AttendanceRecord,
    Evaluation,
    Grade,
    GroupWork,
    GroupWorkAttachment,
    GroupWorkDelivery,
    InterventionPlan,
    Occurrence,
    PedagogicalObservation,
    PlanNote,
    SchoolConfig,
    Submission,
    WorkGroup,
    WorkGroupMember,
)


def _log(request, action, target, detail, target_id=None):
    create_audit_log(
        user=request.user, action=action, request=request, target=target,
        detail=detail, target_id=target_id,
    )


def _publication_message(item, noun, published_now):
    """Mensagem após salvar: diz quando a família passa a ver e ser avisada."""
    if item.status == "rascunho":
        return f"Rascunho salvo. A família ainda não vê {noun}."
    if item.published_date > timezone.localdate():
        return (
            f"Publicação agendada para {item.published_date:%d/%m/%Y}: a turma "
            "passa a ver nessa data, e a família é avisada nesse dia."
        )
    if published_now:
        return "Publicado para a turma. As famílias foram avisadas."
    return "Alterações salvas para toda a turma."


def _active_class(student):
    return (
        Enrollment.objects.filter(student=student, status="ativo")
        .select_related("class_group", "school_year")
        .first()
    )


def _enrolled_students(class_group):
    return (
        Student.objects.filter(
            school=class_group.school,
            enrollments__class_group=class_group,
            enrollments__status="ativo",
        )
        .distinct()
        .order_by("first_name", "last_name")
    )


def _teacher_assignments(user):
    return TeacherAssignment.objects.filter(teacher=user, school=user.school).select_related(
        "class_group", "subject", "school_year"
    )


def _parse_grade(value):
    """Nota digitada na tela de entregas. Aceita vírgula decimal.

    Valor em branco ou inválido vira ``None`` — a atividade fica registrada
    sem nota em vez de a tela falhar ou gravar zero.
    """
    value = (value or "").strip().replace(",", ".")
    if not value:
        return None
    try:
        nota = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    if nota < 0 or nota > Decimal("1000"):
        return None
    return nota.quantize(Decimal("0.01"))


def _parse_date(value):
    """Data vinda da URL. Valor invalido e ignorado em vez de virar erro 500."""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _guardian_child_ids(user):
    """(filhos aprovados, turmas ativas desses filhos) para responsável."""
    from apps.registry.models import GuardianLink

    child_ids = list(
        GuardianLink.objects.filter(guardian=user, status="aprovado").values_list(
            "student_id", flat=True
        )
    )
    class_ids = list(
        Enrollment.objects.filter(student_id__in=child_ids, status="ativo").values_list(
            "class_group_id", flat=True
        )
    )
    return child_ids, class_ids


# ---------- Avaliações e notas ----------

def evaluation_list(request):
    user = request.user
    acc.require(acc.can_view_evaluations(user))
    qs = Evaluation.objects.filter(school=user.school).select_related("subject", "class_group", "created_by")
    student_id = id_param(request, "estudante")
    if student_id:
        student = get_object_or_404(Student, pk=student_id, school=user.school)
        class_group = _active_class(student)
        if class_group:
            qs = qs.filter(class_group=class_group.class_group)
        else:
            qs = qs.none()
    if user.role == Role.PROFESSOR.value:
        qs = qs.filter(class_group_id__in=_teacher_assignments(user).values("class_group_id"))
    elif user.role in (Role.RESPONSAVEL.value, Role.ESTUDANTE.value):
        # Só avaliação publicada, das turmas por onde o estudante passou e do
        # período em que esteve em cada uma. Antes a família perdia as notas
        # da turma anterior na transferência, e o estudante via avaliações
        # da turma antiga aplicadas depois que ele saiu.
        qs = qs.filter(
            acc.enrollment_window_q(acc.family_enrollments(user), "date"),
            status=Evaluation.Status.PUBLISHED,
        )
    status = request.GET.get("status")
    if status in ("rascunho", "publicada"):
        qs = qs.filter(status=status)

    page = paginate(request, qs.order_by("-date", "-created_at"))
    # Média e regra acadêmica em duas consultas para a página inteira. Antes
    # eram duas POR LINHA: com 25 linhas, 50 consultas só para montar a lista.
    medias = dict(
        Grade.objects.filter(evaluation__in=page)
        .values_list("evaluation")
        .annotate(media=Avg("value"))
        .values_list("evaluation", "media")
    )
    regras = {
        r.subject_id: r
        for r in AcademicRule.objects.filter(school=user.school)
    }
    rows = [
        {
            "eval": ev,
            "avg": medias.get(ev.pk),
            "rule": regras.get(ev.subject_id),
        }
        for ev in page
    ]
    return render(
        request,
        "pedagogy/evaluation_list.html",
        {
            "rows": rows,
            "page": page,
            "status": status,
            "student_id": student_id,
            "can_edit_any": user.role == Role.PROFESSOR.value,
        },
    )


def _get_managed_evaluation(user, pk):
    ev = get_object_or_404(
        Evaluation.objects.select_related("class_group", "subject"), pk=pk, school=user.school
    )
    acc.require(acc.can_manage_evaluations(user, ev.class_group, ev.subject))
    return ev


def evaluation_create(request):
    user = request.user
    acc.require(user.role == Role.PROFESSOR.value)
    form = EvaluationForm(request.POST or None, user=user, school=user.school)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            ev = form.save(commit=False)
            ev.school = user.school
            ev.created_by = user
            ev.save()
            _log(request, "create", ev, f"Criou a avaliação {ev.title} ({ev.class_group})")
        messages.success(request, "Avaliação criada.")
        return redirect("pedagogy:evaluation_list")
    return render(request, "pedagogy/evaluation_form.html", {"form": form, "obj": None})


def evaluation_edit(request, pk):
    user = request.user
    ev = _get_managed_evaluation(user, pk)
    if ev.status != "rascunho":
        messages.error(request, "Apenas avaliações em rascunho podem ser alteradas/excluídas.")
        return redirect("pedagogy:evaluation_list")
    form = EvaluationForm(
        request.POST or None, instance=ev, user=user, school=user.school,
        class_group=ev.class_group, subject=ev.subject,
    )
    if request.method == "POST":
        if request.POST.get("_delete"):
            with transaction.atomic():
                pk = ev.pk
                detail = f"Excluiu a avaliação {ev.title} ({ev.class_group})"
                ev.delete()
                _log(request, "delete", ev, detail, target_id=pk)
            messages.success(request, "Avaliação excluída.")
            return redirect("pedagogy:evaluation_list")
        if form.is_valid():
            with transaction.atomic():
                form.save()
                _log(request, "update", ev, f"Atualizou a avaliação {ev.title}")
            messages.success(request, "Avaliação atualizada.")
            return redirect("pedagogy:evaluation_list")
    return render(request, "pedagogy/evaluation_form.html", {"form": form, "obj": ev})


def evaluation_grade(request, pk):
    user = request.user
    ev = _get_managed_evaluation(user, pk)
    students = _enrolled_students(ev.class_group)
    if request.method == "POST":
        form = GradeBatchForm(request.POST, evaluation=ev, students=students)
        if form.is_valid():
            with transaction.atomic():
                obs = form.cleaned_data.get("observation_all", "")
                changed = 0
                for student, field_name in form.grades:
                    value = form.cleaned_data.get(field_name)
                    if value is None:
                        continue
                    grade, created = Grade.objects.get_or_create(
                        school=user.school, evaluation=ev, student=student
                    )
                    old = grade.value
                    grade.value = value
                    if obs:
                        grade.observation = obs
                    grade.updated_by = user
                    grade.save()
                    if created or old != value:
                        changed += 1
                        _log(
                            request,
                            "create" if created else "update",
                            grade,
                            f"Nota {student}: {old if old is not None else '—'} → {value}",
                        )
            messages.success(request, f"{changed} nota(s) registrada(s).")
            return redirect("pedagogy:evaluation_grade", pk=ev.pk)
    else:
        form = GradeBatchForm(evaluation=ev, students=students)
    return render(
        request,
        "pedagogy/evaluation_grade.html",
        {"form": form, "evaluation": ev, "students": students},
    )


def evaluation_publish(request, pk):
    if request.method != "POST":
        raise PermissionDenied
    user = request.user
    ev = _get_managed_evaluation(user, pk)
    with transaction.atomic():
        ev.status = "publicada"
        ev.save()
        _log(request, "approve", ev, "Publicou a avaliação para a família")
        notify_evaluation_published(ev)
    messages.success(request, "Avaliação publicada. A família já visualiza as notas.")
    return redirect("pedagogy:evaluation_list")


# ---------- Atividades de casa e entregas ----------

def _guardian_visible_activities(user):
    """Atividades que a família pode ver.

    Abrange QUALQUER matrícula dos filhos vinculados, não só a ativa, para que
    transferência de turma não apague o histórico já atribuído ao estudante.
    Rascunho e atividade com data de publicação futura ficam de fora.
    """
    child_ids = GuardianLink.objects.filter(
        guardian=user, status="aprovado"
    ).values_list("student_id", flat=True)
    class_ids = Enrollment.objects.filter(student_id__in=child_ids).values_list(
        "class_group_id", flat=True
    )
    return Activity.objects.filter(
        school=user.school,
        class_group_id__in=class_ids,
        published_date__lte=timezone.localdate(),
    ).exclude(status=Activity.Status.DRAFT)


def _rows_for_students(school, students, activities):
    """Uma linha por (atividade, estudante).

    A família com mais de um filho precisa distinguir a qual estudante cada
    atividade pertence, inclusive quando os dois estão na mesma turma. Para a
    conta do próprio estudante a lista tem um único nome.
    """
    enrolled = acc.enrollments_by_student(s.pk for s in students)
    # Entrega registrada pelo PROFESSOR. Numa consulta para todos os pares,
    # para a contagem de consultas não crescer com o volume.
    submissions = {
        (s.activity_id, s.student_id): s
        for s in Submission.objects.filter(
            activity__in=activities, student__in=students or [None]
        )
    }
    rows = []
    for act in activities:
        for student in students:
            if acc.reaches(enrolled.get(student.pk, ()), act):
                key, label = act.family_situation()
                rows.append(
                    {
                        "activity": act,
                        "student": student,
                        "state": key,
                        "state_label": label,
                        "submission": submissions.get((act.pk, student.pk)),
                    }
                )
    order = {"a_vencer": 0, "pendente": 1, "publicada": 2, "encerrada": 3, "cancelada": 4}
    rows.sort(key=lambda r: (order.get(r["state"], 9), r["activity"].deadline or date.max))
    return rows


def _visible_activities(qs):
    return list(
        qs.select_related("subject", "class_group", "created_by").prefetch_related(
            "attachments"
        )
    )


def _student_own_rows(user):
    """Atividades da própria conta de estudante."""
    student = acc.own_student(user)
    if student is None:
        return [], []
    class_ids = Enrollment.objects.filter(student=student).values_list(
        "class_group_id", flat=True
    )
    activities = _visible_activities(
        Activity.objects.filter(
            school=user.school,
            class_group_id__in=class_ids,
            published_date__lte=timezone.localdate(),
        ).exclude(status=Activity.Status.DRAFT)
    )
    return _rows_for_students(user.school, [student], activities), [student]


def _family_rows(user, student_filter=None):
    """Linhas das atividades dos filhos vinculados e aprovados."""
    links = (
        GuardianLink.objects.filter(guardian=user, status="aprovado")
        .select_related("student")
        .order_by("student__first_name")
    )
    children = [link.student for link in links]
    if student_filter:
        children = [s for s in children if s.pk == student_filter]
    # Sem fatia: o conjunto já está restrito às turmas dos filhos vinculados e
    # ao que foi publicado. Cortar aqui descartaria o histórico mais antigo e a
    # contagem exibida pela paginação ficaria mentindo sobre o total.
    activities = _visible_activities(_guardian_visible_activities(user))
    return _rows_for_students(user.school, children, activities), children


def student_activity_rows(student, limit=20):
    """Atividades atribuídas a um estudante, para a ficha individual.

    Percorre todas as matrículas do estudante, não só a ativa, para que o
    histórico sobreviva a uma transferência de turma. Rascunho e atividade
    agendada ficam fora: não foram atribuídas a ninguém ainda.
    """
    enrollments = acc.enrollments_by_student([student.pk]).get(student.pk, [])
    candidates = (
        Activity.objects.filter(
            class_group_id__in={e.class_group_id for e in enrollments},
            published_date__lte=timezone.localdate(),
        )
        .exclude(status=Activity.Status.DRAFT)
        .select_related("subject", "class_group")
        .order_by("-published_date", "-created_at")
    )
    # O período na turma é conferido aqui, antes do corte: cortar primeiro
    # poderia esconder atividades válidas atrás das que ficam de fora.
    activities = []
    for act in candidates.iterator():
        if acc.reaches(enrollments, act):
            activities.append(act)
            if len(activities) >= limit:
                break
    submissions = {
        s.activity_id: s
        for s in Submission.objects.filter(student=student, activity__in=activities)
    }
    rows = []
    for act in activities:
        state, label = act.family_situation()
        rows.append(
            {
                "activity": act,
                "state": state,
                "state_label": label,
                "submission": submissions.get(act.pk),
            }
        )
    return rows


def activity_list(request):
    user = request.user
    acc.require(acc.can_view_evaluations(user))

    if user.role == Role.ESTUDANTE.value:
        rows, students = _student_own_rows(user)
        state = request.GET.get("situacao")
        if state in ("a_vencer", "pendente", "encerrada", "cancelada"):
            rows = [r for r in rows if r["state"] == state]
        page = paginate(request, rows)
        return render(
            request,
            "pedagogy/activity_family.html",
            {
                "rows": page,
                "page": page,
                "children": students,
                "is_student": True,
                "state": state,
            },
        )

    if user.role == Role.RESPONSAVEL.value:
        student_filter = id_param(request, "estudante")
        student_pk = None
        if student_filter:
            student = get_object_or_404(Student, pk=student_filter, school=user.school)
            # Sem este bloqueio o parâmetro da URL viraria consulta a aluno alheio.
            if student.pk not in _guardian_child_ids(user)[0]:
                raise PermissionDenied
            student_pk = student.pk
        rows, children = _family_rows(user, student_filter=student_pk)
        state = request.GET.get("situacao")
        if state in ("a_vencer", "pendente", "encerrada", "cancelada"):
            rows = [r for r in rows if r["state"] == state]
        page = paginate(request, rows)
        return render(
            request,
            "pedagogy/activity_family.html",
            {
                "rows": page,
                "page": page,
                "children": children,
                "student_id": student_pk,
                "state": state,
            },
        )

    qs = Activity.objects.filter(school=user.school).select_related(
        "subject", "class_group", "created_by"
    )
    student_id = id_param(request, "estudante")
    if student_id:
        student = get_object_or_404(Student, pk=student_id, school=user.school)
        class_group = _active_class(student)
        qs = qs.filter(class_group=class_group.class_group) if class_group else qs.none()
    if user.role == Role.PROFESSOR.value:
        qs = qs.filter(class_group_id__in=_teacher_assignments(user).values("class_group_id"))

    status = request.GET.get("status")
    if status in dict(Activity.Status.choices):
        qs = qs.filter(status=status)
    class_filter = id_param(request, "turma")
    if class_filter:
        qs = qs.filter(class_group_id=class_filter)
    subject_filter = id_param(request, "disciplina")
    if subject_filter:
        qs = qs.filter(subject_id=subject_filter)
    date_from = _parse_date(request.GET.get("de"))
    if date_from:
        qs = qs.filter(published_date__gte=date_from)
    date_to = _parse_date(request.GET.get("ate"))
    if date_to:
        qs = qs.filter(published_date__lte=date_to)

    page = paginate(
        request,
        qs.annotate(attachment_count=Count("attachments")).order_by(
            "-published_date", "-created_at"
        ),
    )
    today = timezone.localdate()
    # Os pares turma+disciplina do professor vêm numa consulta só. Chamar
    # can_manage_activities por linha custava uma consulta por atividade.
    pares = (
        set(
            _teacher_assignments(user).values_list("class_group_id", "subject_id")
        )
        if user.role == Role.PROFESSOR.value
        else set()
    )
    rows = []
    for act in page:
        state, label = act.family_situation(today)
        rows.append(
            {
                "activity": act,
                "state": state,
                "state_label": label,
                "can_manage": (act.class_group_id, act.subject_id) in pares,
            }
        )
    if user.role == Role.PROFESSOR.value:
        classes = ClassGroup.objects.filter(
            pk__in=_teacher_assignments(user).values("class_group_id")
        )
        subjects = user.school.subjects.filter(
            pk__in=_teacher_assignments(user).values("subject_id")
        )
    else:
        classes = ClassGroup.objects.filter(school=user.school)
        subjects = user.school.subjects.all()
    return render(
        request,
        "pedagogy/activity_list.html",
        {
            "rows": rows,
            "page": page,
            "student_id": student_id,
            "can_manage": user.role == Role.PROFESSOR.value,
            "status": status,
            "classes": classes,
            "subjects": subjects,
            "class_filter": class_filter,
            "subject_filter": subject_filter,
            "date_from": request.GET.get("de", ""),
            "date_to": request.GET.get("ate", ""),
            "activity_status_choices": Activity.Status.choices,
        },
    )


def _get_managed_activity(user, pk):
    act = get_object_or_404(
        Activity.objects.select_related("class_group", "subject"), pk=pk, school=user.school
    )
    acc.require(acc.can_manage_activities(user, act.class_group, act.subject))
    return act


def activity_detail(request, pk):
    """Tela única da atividade: serve de prévia ao professor e de leitura à
    família, com o mesmo conteúdo que a família recebe."""
    user = request.user
    act = get_object_or_404(
        Activity.objects.select_related(
            "class_group", "subject", "created_by", "school"
        ).prefetch_related("attachments"),
        pk=pk,
    )
    acc.require(acc.can_view_activity(user, act))
    students = []
    if user.role == Role.RESPONSAVEL.value:
        por_aluno = acc.enrollments_by_student(
            _guardian_child_ids(user)[0], act.class_group_id
        )
        students = list(
            Student.objects.filter(
                pk__in=[sid for sid, enrs in por_aluno.items() if acc.reaches(enrs, act)]
            ).order_by("first_name", "last_name")
        )
    state, state_label = act.family_situation()
    return render(
        request,
        "pedagogy/activity_detail.html",
        {
            "activity": act,
            "students": students,
            "state": state,
            "state_label": state_label,
            "today": timezone.localdate(),
            "reach": _enrolled_students(act.class_group).count(),
            "can_manage": acc.can_manage_activities(user, act.class_group, act.subject),
        },
    )


def _save_attachments(request, act, form):
    for upload in form.cleaned_data.get("attachments") or []:
        ActivityAttachment.objects.create(
            activity=act,
            file=upload,
            original_name=upload.name[:255],
            size=upload.size,
            uploaded_by=request.user,
        )


def activity_create(request):
    user = request.user
    acc.require(acc.can_manage_activities(user))
    form = ActivityForm(
        request.POST or None, request.FILES or None, user=user, school=user.school
    )
    if request.method == "POST" and form.is_valid():
        publish = bool(request.POST.get("_publish"))
        with transaction.atomic():
            act = form.save(commit=False)
            act.school = user.school
            act.created_by = user
            act.status = (
                Activity.Status.PUBLISHED if publish else Activity.Status.DRAFT
            )
            act.save()
            _save_attachments(request, act, form)
            _log(
                request,
                "create",
                act,
                f"Criou a atividade {act.title} ({act.class_group}) "
                f"como {act.get_status_display().lower()}",
            )
            avisou = announce_publication(act)
        messages.success(request, _publication_message(act, "esta atividade", avisou))
        return redirect("pedagogy:activity_detail", pk=act.pk)
    return render(request, "pedagogy/activity_form.html", {"form": form, "obj": None})


def activity_edit(request, pk):
    user = request.user
    act = _get_managed_activity(user, pk)
    if act.status == Activity.Status.CANCELED:
        # A atividade cancelada é registro histórico: editar o enunciado
        # depois mudaria o que a família viu quando ela foi cancelada.
        messages.warning(request, "Atividade cancelada não pode ser editada.")
        return redirect("pedagogy:activity_detail", pk=act.pk)
    was_draft = act.status == Activity.Status.DRAFT
    form = ActivityForm(
        request.POST or None,
        request.FILES or None,
        instance=act,
        user=user,
        school=user.school,
    )
    if request.method == "POST" and form.is_valid():
        publish = bool(request.POST.get("_publish"))
        with transaction.atomic():
            act = form.save()
            _save_attachments(request, act, form)
            if publish and was_draft:
                act.status = Activity.Status.PUBLISHED
                act.save(update_fields=["status"])
            _log(request, "update", act, f"Atualizou a atividade {act.title}")
            avisou = announce_publication(act)
        messages.success(request, _publication_message(act, "esta atividade", avisou))
        return redirect("pedagogy:activity_detail", pk=act.pk)
    return render(request, "pedagogy/activity_form.html", {"form": form, "obj": act})


def activity_cancel(request, pk):
    """Cancela sem apagar: o histórico escolar e as entregas são preservados."""
    user = request.user
    act = _get_managed_activity(user, pk)
    if act.status == Activity.Status.CANCELED:
        messages.warning(request, "Esta atividade já está cancelada.")
        return redirect("pedagogy:activity_detail", pk=act.pk)
    form = ActivityCancelForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            act.status = Activity.Status.CANCELED
            act.cancel_reason = form.cleaned_data["cancel_reason"]
            act.save(update_fields=["status", "cancel_reason", "updated_at"])
            _log(
                request,
                "update",
                act,
                f"Cancelou a atividade {act.title}: {act.cancel_reason}",
            )
            notify_publication_canceled(act)
        messages.success(
            request, "Atividade cancelada. O histórico foi preservado."
        )
        return redirect("pedagogy:activity_detail", pk=act.pk)
    return render(
        request, "pedagogy/activity_cancel.html", {"form": form, "activity": act}
    )


def activity_attachment(request, pk, attachment_id):
    """Download conferido no servidor: sem isto o anexo de uma turma vazaria
    para qualquer pessoa autenticada que adivinhasse o identificador."""
    att = get_object_or_404(
        ActivityAttachment.objects.select_related(
            "activity", "activity__class_group", "activity__school"
        ),
        pk=attachment_id,
        activity_id=pk,
    )
    acc.require(acc.can_view_activity(request.user, att.activity))
    if not att.file:
        raise Http404("Anexo indisponível.")
    return FileResponse(
        att.file.open("rb"),
        content_type=attachment_content_type(att.file.name),
        as_attachment=True,
        filename=att.original_name or "anexo",
    )


def activity_submissions(request, pk):
    user = request.user
    act = _get_managed_activity(user, pk)
    students = _enrolled_students(act.class_group)
    existing = {
        s.student_id: s for s in act.submissions.select_related("student")
    }
    if request.method == "POST":
        with transaction.atomic():
            count = 0
            for st in students:
                status = request.POST.get(f"status_{st.pk}", "")
                # Vazio significa "sem registro": não inventa uma entrega para
                # quem o professor não avaliou. Antes o select era sempre
                # enviado e salvar marcava a turma inteira como entregue.
                if status not in dict(Submission.Status.choices):
                    continue
                grade = _parse_grade(request.POST.get(f"nota_{st.pk}", ""))
                sub, created = Submission.objects.update_or_create(
                    school=user.school, activity=act, student=st,
                    defaults={
                        "status": status,
                        "grade": grade,
                        "comment": request.POST.get(f"obs_{st.pk}", "").strip()[:500],
                        "updated_by": user,
                    },
                )
                _log(
                    request,
                    "create" if created else "update",
                    sub,
                    f"Entrega de {st}: {status}",
                )
                count += 1
            messages.success(request, f"{count} entrega(s) registrada(s).")
        return redirect("pedagogy:activity_submissions", pk=act.pk)
    return render(
        request,
        "pedagogy/activity_submissions.html",
        {"activity": act, "students": students, "existing": existing},
    )


# ---------- Trabalhos em grupo ----------

def _enrolled_in(class_group):
    return _enrolled_students(class_group)


def _group_rows(work, groups):
    """Grupos com integrantes ativos e os que saíram, para a tela do professor.

    ``removable`` segue a mesma regra da ação de remover: grupo com entrega,
    ou com integrantes num trabalho já fora do rascunho, tem histórico.
    """
    com_entrega = set(work.deliveries.values_list("group_id", flat=True))
    rows = []
    for g in groups.prefetch_related("members__student"):
        membros = [m for m in g.members.all() if m.removed_at is None]
        saidos = [m for m in g.members.all() if m.removed_at is not None]
        removable = g.pk not in com_entrega and (
            work.status == GroupWork.Status.DRAFT or not (membros or saidos)
        )
        rows.append(
            {"group": g, "members": membros, "former": saidos, "removable": removable}
        )
    return rows


def _visible_group_works(user):
    """Trabalhos publicados das turmas em que o usuário tem vínculo."""
    if user.role == Role.RESPONSAVEL.value:
        child_ids = GuardianLink.objects.filter(
            guardian=user, status="aprovado"
        ).values_list("student_id", flat=True)
        class_ids = Enrollment.objects.filter(
            student_id__in=child_ids
        ).values_list("class_group_id", flat=True)
    elif user.role == Role.ESTUDANTE.value:
        class_ids = acc._student_class_ids(user)
    else:
        class_ids = []
    return (
        GroupWork.objects.filter(
            school=user.school,
            class_group_id__in=class_ids,
            published_date__lte=timezone.localdate(),
        )
        .exclude(status=GroupWork.Status.DRAFT)
        .select_related("subject", "class_group", "created_by")
    )


def _family_work_rows(user, student_filter=None):
    """Uma linha por (trabalho, estudante) com o grupo daquele estudante.

    A §7.3 exige que fique explícito de quem é o registro que se está vendo e
    qual é a composição do grupo DAQUELE estudante — não a dos outros grupos.
    """
    alvos = []
    if user.role == Role.RESPONSAVEL.value:
        links = (
            GuardianLink.objects.filter(guardian=user, status="aprovado")
            .select_related("student")
            .order_by("student__first_name")
        )
        alvos = [l.student for l in links]
    elif user.role == Role.ESTUDANTE.value:
        own = acc.own_student(user)
        alvos = [own] if own is not None else []
    if student_filter:
        alvos = [s for s in alvos if s.pk == student_filter]
    if not alvos:
        return [], []

    works = list(_visible_group_works(user).prefetch_related("attachments"))
    # Uma consulta para todas as participações relevantes.
    membros = (
        WorkGroupMember.objects.filter(
            group__group_work__in=works,
            student__in=alvos,
            removed_at__isnull=True,
        )
        .select_related("group", "student")
        .prefetch_related("group__members__student")
    )
    por_par = {(m.group.group_work_id, m.student_id): m for m in membros}

    rows = []
    for w in works:
        for st in alvos:
            m = por_par.get((w.pk, st.pk))
            if m is None:
                continue  # o estudante não participa de nenhum grupo deste trabalho
            colegas = [
                x.student
                for x in m.group.members.all()
                if x.removed_at is None and x.student_id != st.pk
            ]
            state, label = w.situation()
            rows.append(
                {
                    "work": w,
                    "student": st,
                    "group": m.group,
                    "colleagues": colegas,
                    "state": state,
                    "state_label": label,
                }
            )
    ordem = {"a_vencer": 0, "pendente": 1, "publicada": 2, "encerrada": 3, "cancelada": 4}
    rows.sort(key=lambda r: (ordem.get(r["state"], 9), r["work"].deadline or date.max))
    return rows, alvos


def student_group_work_rows(student, limit=20):
    """Trabalhos em grupo do estudante, para a ficha individual.

    Percorre qualquer matrícula, não só a ativa, para a transferência de turma
    não apagar o histórico de participação.
    """
    membros = (
        WorkGroupMember.objects.filter(student=student, removed_at__isnull=True)
        .exclude(group__group_work__status=GroupWork.Status.DRAFT)
        .filter(group__group_work__published_date__lte=timezone.localdate())
        .select_related(
            "group", "group__group_work", "group__group_work__subject",
            "group__group_work__class_group",
        )
        .prefetch_related("group__members__student")
        .order_by("-group__group_work__published_date")[:limit]
    )
    rows = []
    for m in membros:
        w = m.group.group_work
        state, label = w.situation()
        rows.append(
            {
                "work": w,
                "group": m.group,
                "colleagues": [
                    x.student
                    for x in m.group.members.all()
                    if x.removed_at is None and x.student_id != student.pk
                ],
                "state": state,
                "state_label": label,
            }
        )
    return rows


def group_work_list(request):
    user = request.user
    acc.require(acc.can_view_evaluations(user))

    if user.role in (Role.RESPONSAVEL.value, Role.ESTUDANTE.value):
        student_pk = None
        student_filter = id_param(request, "estudante")
        if student_filter:
            student = get_object_or_404(Student, pk=student_filter, school=user.school)
            permitidos = (
                _guardian_child_ids(user)[0]
                if user.role == Role.RESPONSAVEL.value
                else [getattr(acc.own_student(user), "pk", None)]
            )
            if student.pk not in permitidos:
                raise PermissionDenied
            student_pk = student.pk
        rows, alvos = _family_work_rows(user, student_filter=student_pk)
        state = request.GET.get("situacao")
        if state in ("a_vencer", "pendente", "encerrada", "cancelada"):
            rows = [r for r in rows if r["state"] == state]
        page = paginate(request, rows)
        return render(
            request,
            "pedagogy/groupwork_family.html",
            {
                "rows": page,
                "page": page,
                "children": alvos,
                "is_student": user.role == Role.ESTUDANTE.value,
                "student_id": student_pk,
                "state": state,
            },
        )

    qs = GroupWork.objects.filter(school=user.school).select_related(
        "subject", "class_group", "created_by"
    )
    if user.role == Role.PROFESSOR.value:
        qs = qs.filter(
            class_group_id__in=_teacher_assignments(user).values("class_group_id")
        )
    status = request.GET.get("status")
    if status in dict(GroupWork.Status.choices):
        qs = qs.filter(status=status)
    class_filter = id_param(request, "turma")
    if class_filter:
        qs = qs.filter(class_group_id=class_filter)
    subject_filter = id_param(request, "disciplina")
    if subject_filter:
        qs = qs.filter(subject_id=subject_filter)

    page = paginate(
        request,
        qs.annotate(
            group_count=Count("groups", distinct=True),
            member_count=Count(
                "groups__members",
                filter=Q(groups__members__removed_at__isnull=True),
                distinct=True,
            ),
        ).order_by("-published_date", "-created_at"),
    )
    today = timezone.localdate()
    pares = (
        set(_teacher_assignments(user).values_list("class_group_id", "subject_id"))
        if user.role == Role.PROFESSOR.value
        else set()
    )
    rows = []
    for w in page:
        state, label = w.situation(today)
        rows.append(
            {
                "work": w,
                "state": state,
                "state_label": label,
                "can_manage": (w.class_group_id, w.subject_id) in pares,
            }
        )
    if user.role == Role.PROFESSOR.value:
        classes = ClassGroup.objects.filter(
            pk__in=_teacher_assignments(user).values("class_group_id")
        )
        subjects = user.school.subjects.filter(
            pk__in=_teacher_assignments(user).values("subject_id")
        )
    else:
        classes = ClassGroup.objects.filter(school=user.school)
        subjects = user.school.subjects.all()
    return render(
        request,
        "pedagogy/groupwork_list.html",
        {
            "rows": rows,
            "page": page,
            "can_manage": user.role == Role.PROFESSOR.value,
            "status": status,
            "classes": classes,
            "subjects": subjects,
            "class_filter": class_filter,
            "subject_filter": subject_filter,
            "status_choices": GroupWork.Status.choices,
        },
    )


def _get_managed_work(user, pk):
    work = get_object_or_404(
        GroupWork.objects.select_related("class_group", "subject"),
        pk=pk,
        school=user.school,
    )
    acc.require(acc.can_manage_group_works(user, work.class_group, work.subject))
    return work


def group_work_detail(request, pk):
    """Tela central da §7.3: o trabalho, o prazo, a turma e QUEM participa.

    Serve de prévia ao professor e de leitura à família e ao estudante, com a
    composição recortada pelo que cada um pode ver.
    """
    user = request.user
    work = get_object_or_404(
        GroupWork.objects.select_related(
            "class_group", "subject", "created_by", "school"
        ).prefetch_related("attachments"),
        pk=pk,
    )
    acc.require(acc.can_view_group_work(user, work))

    grupos = acc.visible_groups_for(user, work)
    state, state_label = work.situation()
    meus = acc.group_work_students_for(user, work)
    # Quando é a família ou o estudante, marca a qual estudante o registro se
    # refere — exigência explícita do item 6 da §7.3.
    destaque = {s.pk for s in meus}
    can_manage = acc.can_manage_group_works(user, work.class_group, work.subject)
    sem_grupo = []
    if can_manage:
        com_grupo = set(
            WorkGroupMember.objects.filter(
                group__group_work=work, removed_at__isnull=True
            ).values_list("student_id", flat=True)
        )
        sem_grupo = [
            s for s in _enrolled_in(work.class_group) if s.pk not in com_grupo
        ]
    return render(
        request,
        "pedagogy/groupwork_detail.html",
        {
            "work": work,
            "group_rows": _group_rows(work, grupos),
            "state": state,
            "state_label": state_label,
            "today": timezone.localdate(),
            "viewer_students": meus,
            "highlight_ids": destaque,
            "can_manage": can_manage,
            "ungrouped": sem_grupo,
            "reach": _enrolled_in(work.class_group).count(),
            "sees_all_groups": can_manage
            or user.role
            in (
                Role.COORDENACAO.value,
                Role.DIRECAO.value,
                Role.SECRETARIA.value,
                Role.ADMIN.value,
            ),
        },
    )


def _save_work_attachments(request, work, form):
    for upload in form.cleaned_data.get("attachments") or []:
        GroupWorkAttachment.objects.create(
            group_work=work,
            file=upload,
            original_name=upload.name[:255],
            size=upload.size,
            uploaded_by=request.user,
        )


def group_work_create(request):
    user = request.user
    acc.require(acc.can_manage_group_works(user))
    form = GroupWorkForm(
        request.POST or None, request.FILES or None, user=user, school=user.school
    )
    if request.method == "POST" and form.is_valid():
        publish = bool(request.POST.get("_publish"))
        with transaction.atomic():
            work = form.save(commit=False)
            work.school = user.school
            work.created_by = user
            work.status = (
                GroupWork.Status.PUBLISHED if publish else GroupWork.Status.DRAFT
            )
            work.save()
            _save_work_attachments(request, work, form)
            _log(
                request,
                "create",
                work,
                f"Criou o trabalho em grupo {work.title} ({work.class_group}) "
                f"como {work.get_status_display().lower()}",
            )
            announce_publication(work)
        messages.success(
            request,
            "Rascunho criado. Agora organize os grupos."
            if not publish
            else "Trabalho publicado. Organize os grupos: as famílias dos "
            "integrantes são avisadas quando a composição for salva.",
        )
        return redirect("pedagogy:group_work_groups", pk=work.pk)
    return render(request, "pedagogy/groupwork_form.html", {"form": form, "obj": None})


def group_work_edit(request, pk):
    user = request.user
    work = _get_managed_work(user, pk)
    if work.status == GroupWork.Status.CANCELED:
        messages.warning(request, "Trabalho cancelado não pode ser editado.")
        return redirect("pedagogy:group_work_detail", pk=work.pk)
    was_draft = work.status == GroupWork.Status.DRAFT
    form = GroupWorkForm(
        request.POST or None,
        request.FILES or None,
        instance=work,
        user=user,
        school=user.school,
    )
    if request.method == "POST" and form.is_valid():
        publish = bool(request.POST.get("_publish"))
        with transaction.atomic():
            work = form.save()
            _save_work_attachments(request, work, form)
            if publish and was_draft:
                work.status = GroupWork.Status.PUBLISHED
                work.save(update_fields=["status"])
            _log(request, "update", work, f"Atualizou o trabalho {work.title}")
            avisou = announce_publication(work)
        messages.success(request, _publication_message(work, "este trabalho", avisou))
        return redirect("pedagogy:group_work_detail", pk=work.pk)
    return render(request, "pedagogy/groupwork_form.html", {"form": form, "obj": work})


def group_work_groups(request, pk):
    """Tela única de organização dos grupos.

    Criar grupo, distribuir automaticamente e atribuir cada estudante
    acontecem aqui. A §7.2 pede explicitamente para não espalhar isso por
    telas desconectadas.
    """
    user = request.user
    work = _get_managed_work(user, pk)
    estudantes = list(_enrolled_in(work.class_group))
    form = WorkGroupForm(group_work=work)
    cancelado = work.status == GroupWork.Status.CANCELED
    tem_entregas = work.deliveries.exists()

    if request.method == "POST" and cancelado:
        # Trabalho cancelado é registro histórico: a composição fica como
        # estava no cancelamento.
        messages.error(request, "Trabalho cancelado: a composição dos grupos não muda mais.")
        return redirect("pedagogy:group_work_groups", pk=work.pk)

    if request.method == "POST":
        acao = request.POST.get("_acao", "")

        if acao == "criar":
            form = WorkGroupForm(request.POST, group_work=work)
            if form.is_valid():
                g = WorkGroup.objects.create(
                    group_work=work, name=form.cleaned_data["name"]
                )
                _log(request, "create", work, f"Criou o grupo {g.name} em {work.title}")
                messages.success(request, f"Grupo {g.name} criado.")
                return redirect("pedagogy:group_work_groups", pk=work.pk)

        elif acao == "remover_grupo":
            g = get_object_or_404(
                WorkGroup, pk=id_param(request, "grupo", request.POST), group_work=work
            )
            nome = g.name
            # Apagar o grupo apagaria em cascata integrantes e entregas (com
            # nota). Só se apaga grupo sem histórico: sem entrega registrada e
            # que nunca teve integrante num trabalho já visível à família.
            com_historico = g.deliveries.exists() or (
                work.status != GroupWork.Status.DRAFT and g.members.exists()
            )
            if com_historico:
                messages.error(
                    request,
                    f"O grupo {nome} já tem histórico (integrantes ou entregas) "
                    "e não é apagado. Para desfazê-lo, retire os integrantes: "
                    "a saída fica registrada.",
                )
                return redirect("pedagogy:group_work_groups", pk=work.pk)
            with transaction.atomic():
                g.delete()
                _log(request, "delete", work, f"Removeu o grupo {nome} de {work.title}")
            messages.success(request, f"Grupo {nome} removido.")
            return redirect("pedagogy:group_work_groups", pk=work.pk)

        elif acao == "sortear":
            try:
                quantos = int(request.POST.get("quantidade", "0"))
            except (TypeError, ValueError):
                quantos = 0
            ja_divulgado = work.status != GroupWork.Status.DRAFT and WorkGroupMember.objects.filter(
                group__group_work=work
            ).exists()
            if tem_entregas or ja_divulgado:
                # O sorteio recomeça do zero (apaga grupos e integrantes).
                # Depois de a família ver a composição, ou com entrega
                # registrada, isso destruiria histórico.
                messages.error(
                    request,
                    "O sorteio refaz todos os grupos e só é possível enquanto "
                    "a composição não foi divulgada nem há entregas. Ajuste os "
                    "integrantes um a um abaixo.",
                )
            elif quantos < 1:
                messages.error(request, "Informe quantos grupos deseja formar.")
            elif not estudantes:
                messages.error(request, "Esta turma não tem estudantes matriculados.")
            else:
                with transaction.atomic():
                    work.groups.all().delete()
                    criados = [
                        WorkGroup.objects.create(
                            group_work=work, name=f"Grupo {i + 1}"
                        )
                        for i in range(quantos)
                    ]
                    sorteados = list(estudantes)
                    random.shuffle(sorteados)
                    for i, st in enumerate(sorteados):
                        WorkGroupMember.objects.create(
                            group=criados[i % quantos], student=st, added_by=user
                        )
                    _log(
                        request,
                        "update",
                        work,
                        f"Sorteou {quantos} grupo(s) em {work.title}",
                    )
                    announce_publication(work)
                messages.success(
                    request,
                    f"{quantos} grupo(s) formados por sorteio. "
                    "Revise e ajuste antes de considerar pronto.",
                )
                return redirect("pedagogy:group_work_groups", pk=work.pk)

        elif acao == "atribuir":
            grupos = {str(g.pk): g for g in work.groups.all()}
            mudancas = 0
            with transaction.atomic():
                for st in estudantes:
                    escolhido = request.POST.get(f"grupo_{st.pk}", "")
                    atual = WorkGroupMember.objects.filter(
                        group__group_work=work, student=st, removed_at__isnull=True
                    ).first()
                    if escolhido and escolhido in grupos:
                        destino = grupos[escolhido]
                        if atual and atual.group_id == destino.pk:
                            continue
                        if atual:
                            # Sai do grupo anterior sem apagar o histórico.
                            atual.removed_at = timezone.now()
                            atual.save(update_fields=["removed_at"])
                        membro = WorkGroupMember.objects.filter(
                            group=destino, student=st
                        ).first()
                        if membro:
                            membro.removed_at = None
                            membro.added_by = user
                            membro.save(update_fields=["removed_at", "added_by"])
                        else:
                            WorkGroupMember.objects.create(
                                group=destino, student=st, added_by=user
                            )
                        mudancas += 1
                    elif atual:
                        atual.removed_at = timezone.now()
                        atual.save(update_fields=["removed_at"])
                        mudancas += 1
                if mudancas:
                    _log(
                        request,
                        "update",
                        work,
                        f"Ajustou a composição dos grupos de {work.title} "
                        f"({mudancas} alteração/ões)",
                    )
                    announce_publication(work)
            messages.success(
                request,
                f"{mudancas} alteração(ões) na composição."
                if mudancas
                else "Nenhuma alteração na composição.",
            )
            return redirect("pedagogy:group_work_groups", pk=work.pk)

    atual = {
        m.student_id: m.group_id
        for m in WorkGroupMember.objects.filter(
            group__group_work=work, removed_at__isnull=True
        )
    }
    grupos = list(work.groups.prefetch_related("members__student"))
    return render(
        request,
        "pedagogy/groupwork_groups.html",
        {
            "work": work,
            "form": form,
            "groups": grupos,
            "group_rows": _group_rows(work, work.groups.all()),
            "students": estudantes,
            "current": atual,
            "ungrouped": [s for s in estudantes if s.pk not in atual],
            "read_only": cancelado,
            "can_draw": not tem_entregas
            and not (work.status != GroupWork.Status.DRAFT and atual),
        },
    )


def group_work_cancel(request, pk):
    """Cancela sem apagar: o trabalho, os grupos e as entregas permanecem."""
    user = request.user
    work = _get_managed_work(user, pk)
    if work.status == GroupWork.Status.CANCELED:
        messages.warning(request, "Este trabalho já está cancelado.")
        return redirect("pedagogy:group_work_detail", pk=work.pk)
    form = GroupWorkCancelForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            work.status = GroupWork.Status.CANCELED
            work.cancel_reason = form.cleaned_data["cancel_reason"]
            work.save(update_fields=["status", "cancel_reason", "updated_at"])
            _log(
                request,
                "update",
                work,
                f"Cancelou o trabalho {work.title}: {work.cancel_reason}",
            )
            notify_publication_canceled(work)
        messages.success(request, "Trabalho cancelado. O histórico foi preservado.")
        return redirect("pedagogy:group_work_detail", pk=work.pk)
    return render(
        request, "pedagogy/groupwork_cancel.html", {"form": form, "work": work}
    )


def group_work_attachment(request, pk, attachment_id):
    """Download conferido no servidor, como nos anexos de atividade."""
    att = get_object_or_404(
        GroupWorkAttachment.objects.select_related(
            "group_work", "group_work__class_group", "group_work__school"
        ),
        pk=attachment_id,
        group_work_id=pk,
    )
    acc.require(acc.can_view_group_work(request.user, att.group_work))
    if not att.file:
        raise Http404("Anexo indisponível.")
    return FileResponse(
        att.file.open("rb"),
        content_type=attachment_content_type(att.file.name),
        as_attachment=True,
        filename=att.original_name or "anexo",
    )


def group_work_deliveries(request, pk):
    """Registro da entrega pelo professor, respeitando o modo escolhido.

    No modo "grupo" há uma linha por grupo; no modo "individual", uma por
    integrante. Nunca se marca o grupo inteiro a partir de um integrante.
    """
    user = request.user
    work = _get_managed_work(user, pk)
    por_grupo = work.delivery_mode == GroupWork.DeliveryMode.GROUP
    grupos = list(work.groups.prefetch_related("members__student"))

    if request.method == "POST":
        with transaction.atomic():
            n = 0
            for g in grupos:
                membros = [m for m in g.members.all() if m.removed_at is None]
                alvos = [None] if por_grupo else [m.student for m in membros]
                for alvo in alvos:
                    chave = f"{g.pk}_{alvo.pk if alvo else 'grupo'}"
                    status = request.POST.get(f"status_{chave}", "")
                    if status not in dict(GroupWorkDelivery.Status.choices):
                        continue
                    GroupWorkDelivery.objects.update_or_create(
                        group_work=work,
                        group=g,
                        student=alvo,
                        defaults={
                            "status": status,
                            "grade": _parse_grade(
                                request.POST.get(f"nota_{chave}", "")
                            ),
                            "comment": request.POST.get(f"obs_{chave}", "").strip()[
                                :500
                            ],
                            "delivered_at": _parse_date(
                                request.POST.get(f"data_{chave}", "")
                            ),
                            "registered_by": user,
                        },
                    )
                    n += 1
            _log(request, "update", work, f"Registrou {n} entrega(s) de {work.title}")
        messages.success(request, f"{n} registro(s) de entrega salvos.")
        return redirect("pedagogy:group_work_deliveries", pk=work.pk)

    existentes = {
        (d.group_id, d.student_id): d
        for d in GroupWorkDelivery.objects.filter(group_work=work)
    }
    linhas = []
    for g in grupos:
        membros = [m for m in g.members.all() if m.removed_at is None]
        if por_grupo:
            linhas.append(
                {
                    "group": g,
                    "members": membros,
                    "student": None,
                    "chave": f"{g.pk}_grupo",
                    "delivery": existentes.get((g.pk, None)),
                }
            )
        else:
            for m in membros:
                linhas.append(
                    {
                        "group": g,
                        "members": membros,
                        "student": m.student,
                        "chave": f"{g.pk}_{m.student_id}",
                        "delivery": existentes.get((g.pk, m.student_id)),
                    }
                )
    return render(
        request,
        "pedagogy/groupwork_deliveries.html",
        {
            "work": work,
            "rows": linhas,
            "por_grupo": por_grupo,
            "status_choices": GroupWorkDelivery.Status.choices,
        },
    )


# ---------- Frequência ----------

def attendance_list(request):
    user = request.user
    acc.require(acc.can_view_attendance(user))
    classes = ClassGroup.objects.filter(school=user.school).select_related("school_year")
    student_id = id_param(request, "estudante")
    if student_id:
        student = get_object_or_404(Student, pk=student_id, school=user.school)
        if user.role == Role.RESPONSAVEL.value:
            if student.pk not in _guardian_child_ids(user)[0]:
                raise PermissionDenied
        active = _active_class(student)
        classes = classes.filter(pk=active.class_group_id) if active else classes.none()
    if user.role == Role.PROFESSOR.value:
        classes = classes.filter(
            pk__in=_teacher_assignments(user).values("class_group_id")
        )
    elif user.role == Role.RESPONSAVEL.value:
        classes = classes.filter(pk__in=_guardian_child_ids(user)[1])
    elif user.role == Role.ESTUDANTE.value:
        classes = classes.filter(pk__in=acc._student_class_ids(user))
    page = paginate(request, classes.order_by("name"))
    return render(
        request,
        "pedagogy/attendance_list.html",
        {
            "classes": page,
            "page": page,
            "can_register": user.role == Role.PROFESSOR.value,
        },
    )


def attendance_class(request, class_group_id):
    user = request.user
    class_group = get_object_or_404(
        ClassGroup.objects.select_related("school_year"), pk=class_group_id, school=user.school
    )
    students = _enrolled_students(class_group)
    if user.role == Role.RESPONSAVEL.value:
        child_ids, child_class_ids = _guardian_child_ids(user)
        if class_group.pk not in child_class_ids:
            raise PermissionDenied
        students = students.filter(pk__in=child_ids)
    elif user.role == Role.ESTUDANTE.value:
        # O estudante vê só a própria linha: a frequência dos colegas não é
        # dado dele.
        own = acc.own_student(user)
        if own is None or class_group.pk not in acc._student_class_ids(user):
            raise PermissionDenied
        students = students.filter(pk=own.pk)
    elif user.role == Role.PROFESSOR.value:
        acc.require(acc._teacher_of(user, class_group))
    records = (
        AttendanceRecord.objects.filter(class_group=class_group)
        .order_by("date", "student__first_name")
    )
    if user.role in (Role.RESPONSAVEL.value, Role.ESTUDANTE.value):
        records = records.filter(student__in=students)
    dates = sorted({r.date for r in records}, reverse=True)[:90]
    grid = {}
    for r in records:
        if r.date in dates:
            grid.setdefault(r.date, {})[r.student_id] = r
    summary = {}
    for r in records:
        summary.setdefault(r.student_id, {"presente": 0, "atraso": 0, "falta": 0})
        summary[r.student_id][r.status] += 1
    return render(
        request,
        "pedagogy/attendance_class.html",
        {
            "class_group": class_group,
            "students": students,
            "dates": dates[:30],
            "grid": grid,
            "summary": summary,
            "can_register": acc.can_register_attendance(user, class_group),
            "max_absences": _max_absences(user.school),
        },
    )


def attendance_register(request, class_group_id):
    user = request.user
    class_group = get_object_or_404(ClassGroup, pk=class_group_id, school=user.school)
    acc.require(acc.can_register_attendance(user, class_group))
    students = _enrolled_students(class_group)
    existing = {
        r.student_id: r
        for r in AttendanceRecord.objects.filter(class_group=class_group)
    }
    tdate = request.GET.get("data") or request.POST.get("data") or date.today().isoformat()
    if request.method == "POST":
        form = AttendanceBatchForm(request.POST, class_group=class_group, students=students)
        if form.is_valid():
            tdate = form.cleaned_data["date"]
            with transaction.atomic():
                for student, field_name in form.rows:
                    status = form.cleaned_data[field_name]
                    rec, created = AttendanceRecord.objects.update_or_create(
                        class_group=class_group,
                        student=student,
                        date=tdate,
                        defaults={"status": status, "recorded_by": user, "school": user.school},
                    )
                    _log(
                        request,
                        "create" if created else "update",
                        rec,
                        f"Frequência {student} em {tdate}: {status}",
                    )
            _flag_attendance_limits(class_group, tdate)
            messages.success(request, f"Frequência de {tdate} registrada.")
            return redirect("pedagogy:attendance_class", class_group_id=class_group.pk)
    else:
        form = AttendanceBatchForm(
            initial={"date": tdate}, class_group=class_group, students=students
        )
    return render(
        request,
        "pedagogy/attendance_register.html",
        {"form": form, "class_group": class_group, "students": students},
    )


def _max_absences(school):
    try:
        return school.config.max_absences_percent
    except SchoolConfig.DoesNotExist:
        return SchoolConfig(max_absences_percent=25.0).max_absences_percent


def _flag_attendance_limits(class_group, tdate):
    """Avisa a secretaria quando um estudante alcança o limite de faltas
    configurado na escola (SchoolConfig.max_absences_percent)."""
    limit = _max_absences(class_group.school)
    for student in _enrolled_students(class_group):
        records = AttendanceRecord.objects.filter(
            class_group=class_group, student=student, date__lte=tdate
        )
        total = records.count()
        if not total:
            continue
        absences = records.filter(status="falta").count()
        percent = Decimal(absences * 100) / Decimal(total)
        if percent >= limit:
            notify_attendance_limit(student, class_group, float(percent))


# ---------- Ocorrências ----------

def occurrence_list(request):
    user = request.user
    if user.role != Role.RESPONSAVEL.value:
        acc.require(acc.can_view_occurrences(user))
    qs = Occurrence.objects.filter(school=user.school).select_related("student", "recorded_by")
    student_id = id_param(request, "estudante")
    if student_id:
        student = get_object_or_404(Student, pk=student_id, school=user.school)
        if user.role == Role.RESPONSAVEL.value:
            acc.require(acc.can_view_occurrences(user, student))
        qs = qs.filter(student=student)
    elif user.role == Role.PROFESSOR.value:
        class_ids = list(_teacher_assignments(user).values_list("class_group_id", flat=True))
        student_ids = list(
            Enrollment.objects.filter(class_group_id__in=class_ids, status="ativo").values_list(
                "student_id", flat=True
            )
        )
        qs = qs.filter(student_id__in=student_ids)
    elif user.role == Role.RESPONSAVEL.value:
        qs = qs.filter(student_id__in=_guardian_child_ids(user)[0])
    status = request.GET.get("status")
    if status in dict(Occurrence.Status.choices):
        qs = qs.filter(status=status)
    page = paginate(request, qs.order_by("-date", "-created_at"))
    return render(
        request,
        "pedagogy/occurrence_list.html",
        {
            "occurrences": page,
            "page": page,
            "status": status,
            "student_id": student_id,
            "can_manage": acc.can_manage_occurrences(user),
            "occurrence_status_choices": Occurrence.Status.choices,
        },
    )


def occurrence_create(request):
    user = request.user
    acc.require(acc.can_manage_occurrences(user))
    form = OccurrenceForm(request.POST or None, school=user.school)
    if request.method == "POST" and form.is_valid():
        student = form.cleaned_data["student"]
        acc.require(acc.can_manage_occurrences(user, student))
        with transaction.atomic():
            occ = form.save(commit=False)
            occ.school = user.school
            occ.recorded_by = user
            occ.save()
            _log(request, "create", occ, f"Registrou ocorrência de {student}")
        messages.success(request, "Ocorrência registrada.")
        return redirect("pedagogy:occurrence_list")
    return render(request, "pedagogy/occurrence_form.html", {"form": form, "obj": None})


def occurrence_detail(request, pk):
    user = request.user
    occ = get_object_or_404(
        Occurrence.objects.select_related("student", "recorded_by"), pk=pk, school=user.school
    )
    acc.require(acc.can_view_occurrences(user, occ.student))
    history = AuditLog.objects.filter(target_type="Occurrence", target_id=str(occ.pk)).order_by(
        "-created_at"
    )[:50]
    form = None
    if acc.can_manage_occurrences(user, occ.student):
        form = OccurrenceUpdateForm(request.POST or None, instance=occ)
        if request.method == "POST" and form.is_valid():
            old_status = occ.status
            with transaction.atomic():
                form.save()
                _log(
                    request,
                    "update",
                    occ,
                    f"Atualizou ocorrência: situação {old_status} → {occ.status}",
                )
            messages.success(request, "Ocorrência atualizada.")
            return redirect("pedagogy:occurrence_detail", pk=occ.pk)
    return render(
        request,
        "pedagogy/occurrence_detail.html",
        {"occurrence": occ, "history": history, "form": form},
    )


# ---------- Observações pedagógicas ----------

def observation_list(request):
    user = request.user
    acc.require(True)
    qs = PedagogicalObservation.objects.filter(school=user.school).select_related(
        "student", "teacher", "subject"
    )
    student_id = id_param(request, "estudante")
    if student_id:
        student = get_object_or_404(Student, pk=student_id, school=user.school)
        qs = qs.filter(student=student)
        acc.require(acc.can_view_observations(user, student))
    elif user.role == Role.PROFESSOR.value:
        qs = qs.filter(teacher=user)
    elif user.role == Role.RESPONSAVEL.value:
        from apps.registry.models import GuardianLink

        student_ids = list(
            GuardianLink.objects.filter(guardian=user, status="aprovado").values_list(
                "student_id", flat=True
            )
        )
        qs = qs.filter(student_id__in=student_ids)
    else:
        acc.require(acc.can_view_observations(user))
    page = paginate(request, qs.order_by("-observed_at", "-created_at"))
    return render(
        request,
        "pedagogy/observation_list.html",
        {"observations": page, "page": page},
    )


def observation_create(request):
    user = request.user
    acc.require(acc.can_manage_observations(user))
    form = PedagogicalObservationForm(request.POST or None, school=user.school)
    if request.method == "POST" and form.is_valid():
        student = form.cleaned_data["student"]
        acc.require(acc.can_manage_observations(user, student=student))
        with transaction.atomic():
            obs = form.save(commit=False)
            obs.school = user.school
            obs.teacher = user
            obs.save()
            _log(request, "create", obs, f"Registrou observação pedagógica de {student}")
        messages.success(request, "Observação registrada.")
        return redirect("pedagogy:observation_list")
    return render(request, "pedagogy/observation_form.html", {"form": form, "obj": None})


def observation_edit(request, pk):
    user = request.user
    obs = get_object_or_404(
        PedagogicalObservation.objects.select_related("student"), pk=pk, school=user.school
    )
    allowed = user.role == Role.COORDENACAO.value or (
        user.role == Role.PROFESSOR.value and obs.teacher_id == user.pk
    )
    acc.require(allowed)
    form = PedagogicalObservationForm(
        request.POST or None, instance=obs, school=user.school, student=obs.student
    )
    if request.method == "POST":
        if request.POST.get("_delete"):
            with transaction.atomic():
                obs.delete()
                _log(request, "delete", obs, "Excluiu observação pedagógica", target_id=obs.pk)
            messages.success(request, "Observação excluída.")
            return redirect("pedagogy:observation_list")
        if form.is_valid():
            with transaction.atomic():
                form.save()
                _log(request, "update", obs, "Atualizou observação pedagógica")
            messages.success(request, "Observação atualizada.")
            return redirect("pedagogy:observation_list")
    return render(request, "pedagogy/observation_form.html", {"form": form, "obj": obs})


# ---------- Planos de acompanhamento ----------

def plan_list(request):
    user = request.user
    qs = InterventionPlan.objects.filter(school=user.school).select_related("student", "created_by")
    student_id = id_param(request, "estudante")
    if student_id:
        student = get_object_or_404(Student, pk=student_id, school=user.school)
        acc.require(acc.can_view_plans(user, student))
        qs = qs.filter(student=student)
    if user.role == Role.PROFESSOR.value:
        class_ids = list(_teacher_assignments(user).values_list("class_group_id", flat=True))
        student_ids = list(
            Enrollment.objects.filter(class_group_id__in=class_ids, status="ativo").values_list(
                "student_id", flat=True
            )
        )
        qs = qs.filter(student_id__in=student_ids)
    elif user.role == Role.RESPONSAVEL.value:
        from apps.registry.models import GuardianLink

        student_ids = list(
            GuardianLink.objects.filter(guardian=user, status="aprovado").values_list(
                "student_id", flat=True
            )
        )
        qs = qs.filter(student_id__in=student_ids)
    else:
        acc.require(user.role in (Role.COORDENACAO.value, Role.DIRECAO.value, Role.ADMIN.value))
    page = paginate(request, qs.order_by("-created_at"))
    return render(
        request,
        "pedagogy/plan_list.html",
        {
            "plans": page,
            "page": page,
            "can_manage": acc.can_manage_plans(user),
        },
    )


def plan_create(request):
    user = request.user
    acc.require(acc.can_manage_plans(user))
    form = InterventionPlanForm(request.POST or None, school=user.school)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            plan = form.save(commit=False)
            plan.school = user.school
            plan.created_by = user
            plan.save()
            _log(request, "create", plan, "Criou plano de acompanhamento")
        messages.success(request, "Plano criado.")
        return redirect("pedagogy:plan_list")
    return render(request, "pedagogy/plan_form.html", {"form": form, "obj": None})


def plan_detail(request, pk):
    user = request.user
    plan = get_object_or_404(
        InterventionPlan.objects.select_related("student", "created_by"), pk=pk, school=user.school
    )
    acc.require(acc.can_view_plans(user, plan.student))
    note_form = None
    if acc.can_manage_plans(user):
        note_form = PlanNoteForm(request.POST or None)
        if request.method == "POST":
            action = request.POST.get("_action")
            if action == "add_note" and note_form.is_valid():
                with transaction.atomic():
                    note = note_form.save(commit=False)
                    note.plan = plan
                    note.created_by = user
                    note.save()
                    _log(request, "create", note, "Registrou evolução no plano")
                messages.success(request, "Evolução registrada.")
                return redirect("pedagogy:plan_detail", pk=plan.pk)
            if action == "set_status":
                status = request.POST.get("status")
                if status in dict(InterventionPlan.Status.choices):
                    with transaction.atomic():
                        plan.status = status
                        plan.save()
                        _log(request, "update", plan, f"Plano → {status}")
                    messages.success(request, "Situação do plano atualizada.")
                    return redirect("pedagogy:plan_detail", pk=plan.pk)
    return render(
        request,
        "pedagogy/plan_detail.html",
        {
            "plan": plan,
            "notes": plan.notes.all(),
            "note_form": note_form,
            "status_choices": InterventionPlan.Status.choices,
        },
    )


# ---------- Justificativas de falta ----------

def justification_list(request):
    user = request.user
    qs = AbsenceJustification.objects.filter(school=user.school).select_related(
        "student", "class_group", "submitted_by"
    )
    student_id = id_param(request, "estudante")
    if student_id:
        student = get_object_or_404(Student, pk=student_id, school=user.school)
        qs = qs.filter(student=student)
        acc.require(acc.can_view_justifications(user, student))
    elif user.role == Role.PROFESSOR.value:
        class_ids = list(_teacher_assignments(user).values_list("class_group_id", flat=True))
        student_ids = list(
            Enrollment.objects.filter(class_group_id__in=class_ids, status="ativo").values_list(
                "student_id", flat=True
            )
        )
        qs = qs.filter(student_id__in=student_ids)
    elif user.role == Role.RESPONSAVEL.value:
        from apps.registry.models import GuardianLink

        student_ids = list(
            GuardianLink.objects.filter(guardian=user, status="aprovado").values_list(
                "student_id", flat=True
            )
        )
        qs = qs.filter(student_id__in=student_ids)
    else:
        acc.require(acc.can_view_justifications(user))
    status = request.GET.get("status")
    if status in dict(AbsenceJustification.Status.choices):
        qs = qs.filter(status=status)
    page = paginate(request, qs.order_by("-created_at"))
    return render(
        request,
        "pedagogy/justification_list.html",
        {
            "justifications": page,
            "page": page,
            "status": status,
            "can_manage": acc.can_manage_justifications(user),
            "status_choices": AbsenceJustification.Status.choices,
        },
    )


def justification_create(request):
    user = request.user
    if user.role != Role.RESPONSAVEL.value:
        raise PermissionDenied
    student = None
    sid = id_param(request, "student_id", request.POST) or id_param(request, "estudante")
    if sid:
        student = get_object_or_404(Student.objects.filter(school=user.school), pk=sid)
        acc.require(acc.can_view_justifications(user, student))
    form = AbsenceJustificationForm(request.POST or None, school=user.school, student=student)
    if request.method == "POST" and form.is_valid():
        if student is None:
            messages.error(request, "Selecione para qual filho(a) a justificativa será enviada.")
            return render(request, "pedagogy/justification_form.html", {"form": form, "student": None})
        acc.require(acc.can_view_justifications(user, student))
        with transaction.atomic():
            just = form.save(commit=False)
            just.school = user.school
            just.student = student
            just.submitted_by = user
            just.save()
            _log(request, "create", just, f"Enviou justificativa de falta para {student}")
        messages.success(
            request,
            "Justificativa recebida. A secretaria analisará — a frequência oficial não muda automaticamente.",
        )
        return redirect("pedagogy:justification_list")
    return render(request, "pedagogy/justification_form.html", {"form": form, "student": student})


def justification_resolve(request, pk, decision):
    user = request.user
    acc.require(acc.can_manage_justifications(user))
    just = get_object_or_404(AbsenceJustification, pk=pk, school=user.school)
    if decision not in ("aprovar", "recusar"):
        raise PermissionDenied
    if request.method != "POST":
        raise PermissionDenied
    form = JustificationResolutionForm(request.POST)
    note = form.data.get("note", "")
    with transaction.atomic():
        just.status = "aprovada" if decision == "aprovar" else "recusada"
        just.note = note
        just.validated_by = user
        just.validated_at = timezone.now()
        just.save()
        _log(
            request,
            "approve" if decision == "aprovar" else "reject",
            just,
            f"{'Aprovou' if decision == 'aprovar' else 'Recusou'} justificativa de {just.student}",
        )
        notify_justification_resolved(
            just,
            "aprovada" if decision == "aprovar" else "recusada",
        )
    messages.success(request, f"Justificativa {just.get_status_display().lower()}.")
    return redirect("pedagogy:justification_list")


# ---------- Configuração (regras acadêmicas e limites) ----------

def config_edit(request):
    user = request.user
    acc.require(acc.can_edit_school_config(user))
    config, _ = SchoolConfig.objects.get_or_create(school=user.school)
    if request.method == "POST" and "_config" in request.POST:
        form = SchoolConfigForm(request.POST, instance=config, school=user.school)
        if form.is_valid():
            with transaction.atomic():
                form.save()
                _log(request, "update", config, "Atualizou configuração da escola")
            messages.success(request, "Configuração salva.")
            return redirect("pedagogy:config_edit")
    else:
        form = SchoolConfigForm(instance=config, school=user.school)
    subjects = user.school.subjects.all()
    rules = {r.subject_id: r for r in AcademicRule.objects.filter(school=user.school)}
    return render(
        request,
        "pedagogy/config.html",
        {
            "form": form,
            "subjects": subjects,
            "rules": rules,
            "config": config,
            "formula_choices": AcademicRule.Formula.choices,
        },
    )


def academic_rule_edit(request, subject_id):
    user = request.user
    acc.require(acc.can_edit_school_config(user))
    subject = get_object_or_404(user.school.subjects.all(), pk=subject_id)
    rule, _ = AcademicRule.objects.get_or_create(school=user.school, subject=subject)
    if request.method == "POST":
        form = AcademicRuleForm(request.POST, instance=rule, school=user.school)
        if form.is_valid():
            with transaction.atomic():
                form.save()
                _log(request, "update", rule, f"Regra acadêmica de {subject}")
            messages.success(request, f"Regra de {subject} salva.")
            return redirect("pedagogy:config_edit")
        messages.error(request, "Não foi possível salvar a regra.")
    return redirect("pedagogy:config_edit")