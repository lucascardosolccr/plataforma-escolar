from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.models import Role, create_audit_log
from apps.core.pagination import paginate
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
    page = paginate(request, qs.order_by("name"))
    return render(
        request,
        "academics/classgroup_list.html",
        {
            "class_groups": page,
            "page": page,
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
    page = paginate(request, qs.order_by("name"))
    return render(
        request,
        "academics/subject_list.html",
        {
            "subjects": page,
            "page": page,
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
    page = paginate(request, qs.order_by("class_group__name", "subject__name"))
    return render(
        request,
        "academics/assignment_list.html",
        {"assignments": page, "page": page},
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
    if request.user.role != Role.PROFESSOR.value:
        raise PermissionDenied
    assignments = TeacherAssignment.objects.filter(
        teacher=request.user, school=request.user.school
    ).select_related("class_group", "school_year", "subject")
    rosters = []
    for a in assignments.order_by("class_group__name", "subject__name"):
        students = Student.objects.filter(
            school=request.user.school,
            enrollments__class_group=a.class_group,
            enrollments__status="ativo",
        ).distinct().order_by("first_name")
        rosters.append({"assignment": a, "students": students})
    return render(
        request,
        "academics/my_classrooms.html",
        {"rosters": rosters},
    )