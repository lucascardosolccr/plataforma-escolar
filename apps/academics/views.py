from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.models import Role, create_audit_log
from apps.core.pagination import Sort, paginate
from apps.registry.models import Student

from .access import can_manage_academics, can_view_academics
from .forms import (
    ClassGroupForm,
    SchoolYearForm,
    SubjectForm,
    TeacherAssignmentForm,
)
from .models import ClassGroup, SchoolYear, Subject, TeacherAssignment


def _manage_only(user):
    if not can_manage_academics(user):
        raise PermissionDenied


def _view_only(user):
    if not can_view_academics(user):
        raise PermissionDenied


def class_group_list(request):
    _view_only(request.user)
    qs = ClassGroup.objects.filter(school=request.user.school).select_related("school_year")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(name__icontains=q)
    sort = Sort(request, {"turma": "name", "serie": ("grade", "name"), "turno": ("turn", "name"),
                          "ano": ("school_year__name", "name")}, "turma")
    page = paginate(request, sort.apply(qs))
    from apps.coordination.scope import class_scope

    scope = class_scope(request.user)  # coordenação restrita: painel só das turmas que acompanha
    return render(
        request,
        "academics/classgroup_list.html",
        {
            "dashboard_ids": scope,
            "class_groups": page,
            "page": page,
            "sort": sort,
            "q": q,
            "can_manage": can_manage_academics(request.user),
        },
    )


def class_group_create(request):
    _manage_only(request.user)
    form = ClassGroupForm(request.POST or None, school=request.user.school)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            group = form.save(commit=False)
            group.school = request.user.school
            group.save()
            create_audit_log(
                user=request.user,
                action="create",
                request=request,
                target=group,
                detail=f"Criou a turma {group}",
            )
        messages.success(request, "Turma criada.")
        return redirect("class_group_list")
    return render(request, "academics/classgroup_form.html", {"form": form, "obj": None})


def class_group_edit(request, class_group_id):
    _manage_only(request.user)
    group = get_object_or_404(ClassGroup, pk=class_group_id, school=request.user.school)
    form = ClassGroupForm(request.POST or None, instance=group, school=request.user.school)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
            create_audit_log(
                user=request.user,
                action="update",
                request=request,
                target=group,
                detail=f"Atualizou a turma {group}",
            )
        messages.success(request, "Turma atualizada.")
        return redirect("class_group_list")
    return render(request, "academics/classgroup_form.html", {"form": form, "obj": group})


def subject_list(request):
    _view_only(request.user)
    qs = Subject.objects.filter(school=request.user.school)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(name__icontains=q)
    sort = Sort(request, {"disciplina": "name", "codigo": ("code", "name")}, "disciplina")
    page = paginate(request, sort.apply(qs))
    return render(
        request,
        "academics/subject_list.html",
        {
            "subjects": page,
            "page": page,
            "sort": sort,
            "q": q,
            "can_manage": can_manage_academics(request.user),
        },
    )


def subject_create(request):
    _manage_only(request.user)
    form = SubjectForm(request.POST or None, school=request.user.school)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            subject = form.save(commit=False)
            subject.school = request.user.school
            subject.save()
            create_audit_log(
                user=request.user,
                action="create",
                request=request,
                target=subject,
                detail=f"Criou a disciplina {subject.name}",
            )
        messages.success(request, "Disciplina criada.")
        return redirect("subject_list")
    return render(request, "academics/subject_form.html", {"form": form, "obj": None})


def subject_edit(request, subject_id):
    _manage_only(request.user)
    subject = get_object_or_404(Subject, pk=subject_id, school=request.user.school)
    form = SubjectForm(request.POST or None, instance=subject, school=request.user.school)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
            create_audit_log(
                user=request.user,
                action="update",
                request=request,
                target=subject,
                detail=f"Atualizou a disciplina {subject.name}",
            )
        messages.success(request, "Disciplina atualizada.")
        return redirect("subject_list")
    return render(request, "academics/subject_form.html", {"form": form, "obj": subject})


def school_year_list(request):
    _view_only(request.user)
    qs = SchoolYear.objects.filter(school=request.user.school)
    return render(
        request,
        "academics/schoolyear_list.html",
        {
            "years": qs.order_by("-name"),
            "can_manage": can_manage_academics(request.user),
        },
    )


def school_year_create(request):
    _manage_only(request.user)
    form = SchoolYearForm(request.POST or None, school=request.user.school)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            year = form.save(commit=False)
            year.school = request.user.school
            year.save()
            create_audit_log(
                user=request.user,
                action="create",
                request=request,
                target=year,
                detail=f"Criou o ano letivo {year.name}",
            )
        messages.success(request, "Ano letivo criado.")
        return redirect("school_year_list")
    return render(request, "academics/schoolyear_form.html", {"form": form, "obj": None})


def school_year_edit(request, year_id):
    _manage_only(request.user)
    year = get_object_or_404(SchoolYear, pk=year_id, school=request.user.school)
    form = SchoolYearForm(request.POST or None, instance=year, school=request.user.school)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
            create_audit_log(
                user=request.user,
                action="update",
                request=request,
                target=year,
                detail=f"Atualizou o ano letivo {year.name}",
            )
        messages.success(request, "Ano letivo atualizado.")
        return redirect("school_year_list")
    return render(request, "academics/schoolyear_form.html", {"form": form, "obj": year})


def assignment_list(request):
    _manage_only(request.user)
    qs = TeacherAssignment.objects.filter(school=request.user.school).select_related(
        "teacher", "class_group", "subject", "school_year"
    )
    q = request.GET.get("q", "").strip()[:60]
    if q:
        qs = qs.filter(
            Q(teacher__first_name__icontains=q) | Q(teacher__last_name__icontains=q)
            | Q(class_group__name__icontains=q) | Q(subject__name__icontains=q)
        )
    sort = Sort(request, {
        "turma": ("class_group__name", "subject__name"), "professor": ("teacher__first_name", "teacher__last_name"),
        "disciplina": ("subject__name", "class_group__name"), "ano": ("school_year__name", "class_group__name"),
    }, "turma")
    page = paginate(request, sort.apply(qs))
    return render(
        request,
        "academics/assignment_list.html",
        {"assignments": page, "page": page, "sort": sort, "q": q},
    )


def assignment_create(request):
    _manage_only(request.user)
    form = TeacherAssignmentForm(request.POST or None, school=request.user.school)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            assignment = form.save(commit=False)
            assignment.school = request.user.school
            assignment.save()
            create_audit_log(
                user=request.user,
                action="create",
                request=request,
                target=assignment,
                detail=f"Atribuiu {assignment.teacher} a {assignment.subject} ({assignment.class_group})",
            )
        messages.success(request, "Atribuição registrada.")
        return redirect("assignment_list")
    return render(request, "academics/assignment_form.html", {"form": form, "obj": None})


def assignment_delete(request, assignment_id):
    _manage_only(request.user)
    assignment = get_object_or_404(
        TeacherAssignment, pk=assignment_id, school=request.user.school
    )
    if request.method == "POST":
        with transaction.atomic():
            detail = f"Removeu atribuição {assignment.teacher} — {assignment.subject} ({assignment.class_group})"
            assignment.delete()
            create_audit_log(
                user=request.user,
                action="delete",
                request=request,
                detail=detail,
            )
        messages.success(request, "Atribuição removida.")
    return redirect("assignment_list")


def my_classrooms(request):
    """Uma ficha por turma: disciplinas que o professor dá ali, chamada e atalhos.

    Antes era uma lista por turma+disciplina com todos os estudantes abertos:
    com 8 atribuições, mais de 140 linhas antes de chegar à segunda turma.
    """
    if request.user.role != Role.PROFESSOR.value:
        raise PermissionDenied
    from django.utils import timezone

    from apps.pedagogy.models import AttendanceRecord

    from .permissions import active_assignments

    assignments = active_assignments(request.user).select_related("class_group", "school_year", "subject").order_by("class_group__name", "subject__name")
    by_class = {}
    for a in assignments:
        entry = by_class.setdefault(a.class_group_id, {"class_group": a.class_group, "year": a.school_year,
                                                       "subjects": []})
        entry["subjects"].append(a.subject)
    today = timezone.localdate()
    done_today = set(
        AttendanceRecord.objects.filter(class_group_id__in=by_class, date=today)
        .values_list("class_group_id", flat=True).distinct()
    )
    rosters = []
    for class_id, entry in by_class.items():
        entry["students"] = Student.objects.filter(
            school=request.user.school, enrollments__class_group_id=class_id, enrollments__status="ativo",
        ).distinct().order_by("first_name", "last_name")
        entry["attendance_today"] = class_id in done_today
        rosters.append(entry)
    return render(
        request,
        "academics/my_classrooms.html",
        {"rosters": rosters, "school_day": today.weekday() < 5},
    )