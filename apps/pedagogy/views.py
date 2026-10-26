from datetime import date

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Avg, Count
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.academics.models import ClassGroup, SchoolYear, TeacherAssignment
from apps.communication.services import (
    notify_activity_created,
    notify_attendance_limit,
    notify_evaluation_published,
    notify_justification_resolved,
)
from apps.core.models import AuditLog, Role, create_audit_log
from apps.core.uploads import attachment_content_type
from apps.registry.models import Enrollment, GuardianLink, Student

from . import access as acc
from .forms import (
    AbsenceJustificationForm,
    AcademicRuleForm,
    ActivityCancelForm,
    ActivityForm,
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
    InterventionPlan,
    Occurrence,
    PedagogicalObservation,
    PlanNote,
    SchoolConfig,
    Submission,
)


def _log(request, action, target, detail, target_id=None):
    create_audit_log(
        user=request.user, action=action, request=request, target=target,
        detail=detail, target_id=target_id,
    )


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
    student_id = request.GET.get("estudante")
    if student_id:
        student = get_object_or_404(Student, pk=student_id, school=user.school)
        class_group = _active_class(student)
        if class_group:
            qs = qs.filter(class_group=class_group.class_group)
        else:
            qs = qs.none()
    if user.role == Role.PROFESSOR.value:
        qs = qs.filter(class_group_id__in=_teacher_assignments(user).values("class_group_id"))
    elif user.role == Role.RESPONSAVEL.value:
        qs = qs.filter(
            class_group_id__in=_guardian_child_ids(user)[1],
            status=Evaluation.Status.PUBLISHED,
        )
    status = request.GET.get("status")
    if status in ("rascunho", "publicada"):
        qs = qs.filter(status=status)

    evals = qs.order_by("-date", "-created_at")[:200]
    rows = []
    for ev in evals:
        avg = Grade.objects.filter(evaluation=ev).aggregate(Avg("value"))["value__avg"]
        try:
            rule = AcademicRule.objects.get(school=user.school, subject=ev.subject)
        except AcademicRule.DoesNotExist:
            rule = None
        rows.append({"eval": ev, "avg": avg, "rule": rule})
    return render(
        request,
        "pedagogy/evaluation_list.html",
        {
            "rows": rows,
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


def _family_rows(user, student_filter=None):
    """Uma linha por (atividade, filho) para a família saber de quem é a tarefa.

    Um responsável com mais de um filho precisa distinguir a qual estudante
    cada atividade pertence, inclusive quando os dois estão na mesma turma.
    """
    links = (
        GuardianLink.objects.filter(guardian=user, status="aprovado")
        .select_related("student")
        .order_by("student__first_name")
    )
    children = [link.student for link in links]
    if student_filter:
        children = [s for s in children if s.pk == student_filter]
    activities = list(
        _guardian_visible_activities(user)
        .select_related("subject", "class_group", "created_by")
        .prefetch_related("attachments")[:300]
    )
    enrolled = {}
    for enr in Enrollment.objects.filter(
        student__in=children or [None]
    ).values_list("student_id", "class_group_id"):
        enrolled.setdefault(enr[0], set()).add(enr[1])
    # Entrega registrada pelo PROFESSOR. Numa consulta para todos os pares,
    # para a contagem de consultas nao crescer com o volume.
    submissions = {
        (s.activity_id, s.student_id): s
        for s in Submission.objects.filter(
            activity__in=activities, student__in=children or [None]
        )
    }
    rows = []
    for act in activities:
        for student in children:
            if act.class_group_id in enrolled.get(student.pk, ()):
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
    return rows, children


def student_activity_rows(student, limit=20):
    """Atividades atribuídas a um estudante, para a ficha individual.

    Percorre todas as matrículas do estudante, não só a ativa, para que o
    histórico sobreviva a uma transferência de turma. Rascunho e atividade
    agendada ficam fora: não foram atribuídas a ninguém ainda.
    """
    class_ids = Enrollment.objects.filter(student=student).values_list(
        "class_group_id", flat=True
    )
    activities = (
        Activity.objects.filter(
            class_group_id__in=class_ids,
            published_date__lte=timezone.localdate(),
        )
        .exclude(status=Activity.Status.DRAFT)
        .select_related("subject", "class_group")
        .order_by("-published_date", "-created_at")[:limit]
    )
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

    if user.role == Role.RESPONSAVEL.value:
        student_filter = request.GET.get("estudante")
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
        return render(
            request,
            "pedagogy/activity_family.html",
            {
                "rows": rows,
                "children": children,
                "student_id": student_pk,
                "state": state,
            },
        )

    qs = Activity.objects.filter(school=user.school).select_related(
        "subject", "class_group", "created_by"
    )
    student_id = request.GET.get("estudante")
    if student_id:
        student = get_object_or_404(Student, pk=student_id, school=user.school)
        class_group = _active_class(student)
        qs = qs.filter(class_group=class_group.class_group) if class_group else qs.none()
    if user.role == Role.PROFESSOR.value:
        qs = qs.filter(class_group_id__in=_teacher_assignments(user).values("class_group_id"))

    status = request.GET.get("status")
    if status in dict(Activity.Status.choices):
        qs = qs.filter(status=status)
    class_filter = request.GET.get("turma")
    if class_filter:
        qs = qs.filter(class_group_id=class_filter)
    subject_filter = request.GET.get("disciplina")
    if subject_filter:
        qs = qs.filter(subject_id=subject_filter)
    date_from = _parse_date(request.GET.get("de"))
    if date_from:
        qs = qs.filter(published_date__gte=date_from)
    date_to = _parse_date(request.GET.get("ate"))
    if date_to:
        qs = qs.filter(published_date__lte=date_to)

    activities = list(
        qs.annotate(attachment_count=Count("attachments")).order_by(
            "-published_date", "-created_at"
        )[:200]
    )
    today = timezone.localdate()
    rows = [
        {
            "activity": act,
            "state_label": act.family_situation(today)[1],
            "state": act.family_situation(today)[0],
            "can_manage": acc.can_manage_activities(user, act.class_group, act.subject),
        }
        for act in activities
    ]
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
        child_ids = _guardian_child_ids(user)[0]
        students = list(
            Student.objects.filter(
                pk__in=child_ids, enrollments__class_group=act.class_group
            ).distinct()
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
            if act.status == Activity.Status.PUBLISHED:
                notify_activity_created(act)
        messages.success(
            request,
            "Atividade publicada para a turma."
            if publish
            else "Rascunho salvo. A família ainda não vê esta atividade.",
        )
        return redirect("pedagogy:activity_detail", pk=act.pk)
    return render(request, "pedagogy/activity_form.html", {"form": form, "obj": None})


def activity_edit(request, pk):
    user = request.user
    act = _get_managed_activity(user, pk)
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
            if publish and was_draft:
                notify_activity_created(act)
        messages.success(
            request,
            "Atividade publicada para a turma."
            if publish and was_draft
            else "Atividade atualizada para toda a turma.",
        )
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
                key = f"status_{st.pk}"
                if key not in request.POST:
                    continue
                status = request.POST.get(key)
                sub, created = Submission.objects.update_or_create(
                    school=user.school, activity=act, student=st,
                    defaults={"status": status, "updated_by": user},
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


# ---------- Frequência ----------

def attendance_list(request):
    user = request.user
    acc.require(acc.can_view_attendance(user))
    classes = ClassGroup.objects.filter(school=user.school).select_related("school_year")
    student_id = request.GET.get("estudante")
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
    return render(
        request,
        "pedagogy/attendance_list.html",
        {
            "classes": classes.order_by("name")[:200],
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
    elif user.role == Role.PROFESSOR.value:
        acc.require(acc._teacher_of(user, class_group))
    records = (
        AttendanceRecord.objects.filter(class_group=class_group)
        .order_by("date", "student__first_name")
    )
    if user.role == Role.RESPONSAVEL.value:
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
    from decimal import Decimal

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
    student_id = request.GET.get("estudante")
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
    return render(
        request,
        "pedagogy/occurrence_list.html",
        {
            "occurrences": qs.order_by("-date", "-created_at")[:200],
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
    student_id = request.GET.get("estudante")
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
    return render(
        request,
        "pedagogy/observation_list.html",
        {"observations": qs.order_by("-observed_at", "-created_at")[:200]},
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
    student_id = request.GET.get("estudante")
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
    return render(
        request,
        "pedagogy/plan_list.html",
        {
            "plans": qs.order_by("-created_at")[:200],
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
    student_id = request.GET.get("estudante")
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
    return render(
        request,
        "pedagogy/justification_list.html",
        {
            "justifications": qs.order_by("-created_at")[:200],
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
    sid = request.POST.get("student_id") or request.GET.get("estudante")
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