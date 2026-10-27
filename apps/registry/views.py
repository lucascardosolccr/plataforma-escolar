import mimetypes

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.core.models import AuditLog, Role, User, create_audit_log
from apps.core.pagination import paginate
from apps.core.uploads import ALLOWED_PHOTO_EXTENSIONS

from apps.academics.models import SchoolYear

from .access import (
    can_manage_guardian_links,
    can_manage_registry,
    can_view_birth_date,
    can_view_student,
    can_view_student_notes,
    guardian_of,
    require_student_access,
)
from .forms import (
    EnrollmentForm,
    GuardianLinkAdminForm,
    GuardianLinkRequestForm,
    GuardianProfileForm,
    StudentForm,
)
from .models import Enrollment, GuardianLink, GuardianProfile, Student


def _resolver_student_list(request, qs):
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            first_name__icontains=q
        ) | qs.filter(last_name__icontains=q)
    return qs, q


def student_list(request):
    user = request.user
    if user.role == Role.RESPONSAVEL.value:
        ids = GuardianLink.objects.filter(guardian=user, status="aprovado").values_list(
            "student_id", flat=True
        )
        qs = Student.objects.filter(pk__in=ids)
    elif user.role == Role.PROFESSOR.value:
        qs = Student.objects.filter(
            school=user.school,
            enrollments__status="ativo",
            enrollments__class_group__teacher_assignments__teacher=user,
        ).distinct()
    elif can_manage_registry(user):
        qs = Student.objects.filter(school=user.school)
    else:
        raise PermissionDenied

    qs, q = _resolver_student_list(request, qs)
    page = paginate(request, qs.select_related("school"))
    return render(
        request,
        "registry/student_list.html",
        {
            "students": page,
            "page": page,
            "q": q,
            "can_manage": can_manage_registry(user),
        },
    )


def student_create(request):
    if not can_manage_registry(request.user):
        raise PermissionDenied
    form = StudentForm(request.POST or None, request.FILES or None, school=request.user.school)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            student = form.save(commit=False)
            student.school = request.user.school
            student.save()
            create_audit_log(
                user=request.user,
                action="create",
                request=request,
                target=student,
                detail=f"Cadastrou o estudante {student.full_name}",
            )
        messages.success(request, "Estudante cadastrado com sucesso.")
        return redirect("student_detail", student_id=student.pk)
    return render(
        request,
        "registry/student_form.html",
        {
            "form": form,
            "student": None,
            "heading": "Novo estudante",
            "subheading": "Dados do prontuário escolar individual.",
            "back_url": reverse("student_list"),
            "submit_label": "Cadastrar estudante",
            "multipart": True,
        },
    )


def student_detail(request, student_id):
    student = get_object_or_404(Student.objects.select_related("school"), pk=student_id)
    require_student_access(request.user, student)

    enrollments = (
        student.enrollments.select_related("class_group", "school_year")
        .order_by("-school_year__name")
        if can_view_student(request.user, student)
        else student.enrollments.none()
    )
    links = student.guardian_links.select_related("guardian")
    assignments = (
        _assignments_for_student(request.user, student)
        if request.user.role in (Role.ADMIN.value, Role.DIRECAO.value, Role.COORDENACAO.value, Role.SECRETARIA.value, Role.PROFESSOR.value)
        else None
    )
    logs = AuditLog.objects.filter(target_type="Student", target_id=str(student.pk)).order_by("-created_at")[:50]
    show_logs = can_manage_registry(request.user) or request.user.role == Role.ADMIN.value

    comm = _student_comms(request.user, student)

    from apps.pedagogy.views import student_activity_rows

    return render(
        request,
        "registry/student_detail.html",
        {
            "student": student,
            "activity_rows": student_activity_rows(student),
            "enrollments": enrollments,
            "links": links,
            "assignments": assignments,
            "logs": logs if show_logs else None,
            "can_manage": can_manage_registry(request.user),
            "is_guardian": guardian_of(request.user, student),
            "can_view_birth": can_view_birth_date(request.user),
            "can_view_notes": can_view_student_notes(request.user),
            "can_request_link": request.user.role == Role.RESPONSAVEL.value and not guardian_of(request.user, student),
            **comm,
        },
    )


def _student_comms(user, student):
    """Resumo de comunicação relacionado a um estudante (aba Comunicação)."""
    from apps.communication.forms import thread_queryset
    from apps.communication.models import Announcement
    from apps.communication.views import _visible_announcements

    return {
        "comm_threads": thread_queryset(user).filter(student=student)[:10],
        "comm_announcements": _visible_announcements(
            user,
            Announcement.objects.filter(
                school=user.school,
                student=student,
                scope=Announcement.Scope.INDIVIDUAL,
            ),
        )[:10],
        "comm_can_message": user.role == Role.RESPONSAVEL.value
        or (user.role == Role.PROFESSOR.value and guardian_of(user, student))
        or user.role in (
            Role.ADMIN.value,
            Role.DIRECAO.value,
            Role.COORDENACAO.value,
            Role.SECRETARIA.value,
        ),
    }


def _assignments_for_student(user, student):
    from apps.academics.models import TeacherAssignment

    class_ids = Enrollment.objects.filter(student=student, status="ativo").values_list(
        "class_group_id", flat=True
    )
    qs = TeacherAssignment.objects.filter(
        school=student.school, class_group_id__in=list(class_ids)
    ).select_related("teacher", "subject", "class_group")
    if user.role == Role.PROFESSOR.value:
        qs = qs.filter(teacher=user)
    return qs


def student_edit(request, student_id):
    if not can_manage_registry(request.user):
        raise PermissionDenied
    student = get_object_or_404(Student, pk=student_id, school=request.user.school)
    form = StudentForm(
        request.POST or None, request.FILES or None, instance=student, school=request.user.school
    )
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
            create_audit_log(
                user=request.user,
                action="update",
                request=request,
                target=student,
                detail=f"Atualizou dados do estudante {student.full_name}",
            )
        messages.success(request, "Dados do estudante atualizados.")
        return redirect("student_detail", student_id=student.pk)
    return render(
        request,
        "registry/student_form.html",
        {
            "form": form,
            "student": student,
            "heading": f"Editar estudante — {student.full_name}",
            "back_url": reverse("student_detail", args=[student.pk]),
            "submit_label": "Salvar alterações",
            "multipart": True,
        },
    )


def student_photo(request, student_id):
    student = get_object_or_404(Student, pk=student_id)
    require_student_access(request.user, student)
    if not student.photo:
        raise Http404("Foto indisponível.")
    _check_extension(student.photo.name)
    return FileResponse(student.photo.open("rb"), content_type="image/jpeg")


def guardian_photo(request, user_id):
    profile = get_object_or_404(
        GuardianProfile.objects.select_related("user"), user_id=user_id
    )
    is_self = profile.user_id == request.user.pk
    if not (is_self or can_manage_registry(request.user)):
        raise PermissionDenied
    if not is_self and profile.user.school_id != request.user.school_id:
        raise PermissionDenied
    if not profile.photo:
        raise Http404("Foto indisponível.")
    _check_extension(profile.photo.name)
    return FileResponse(profile.photo.open("rb"), content_type="image/jpeg")


def _check_extension(name):
    import os

    if os.path.splitext(name)[1].lower() not in ALLOWED_PHOTO_EXTENSIONS:
        raise Http404("Arquivo não permitido.")


def guardian_list(request):
    if not can_manage_registry(request.user):
        raise PermissionDenied
    qs = User.objects.filter(school=request.user.school, role=Role.RESPONSAVEL.value, is_active=True)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(first_name__icontains=q) | qs.filter(username__icontains=q)
    page = paginate(request, qs.order_by("first_name"))
    return render(
        request,
        "registry/guardian_list.html",
        {"guardians": page, "page": page, "q": q},
    )


def guardian_profile(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    is_self = target == request.user and request.user.role == Role.RESPONSAVEL.value
    is_admin = can_manage_registry(request.user)
    if not (is_self or is_admin):
        raise PermissionDenied
    if is_admin and target.school_id != request.user.school_id:
        raise PermissionDenied

    profile, _created = GuardianProfile.objects.get_or_create(user=target)
    form = GuardianProfileForm(request.POST or None, request.FILES or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
            create_audit_log(
                user=request.user,
                action="update",
                request=request,
                target=profile,
                detail=f"Atualizou perfil do responsável {target.get_full_name() or target.username}",
            )
        messages.success(request, "Perfil atualizado.")
        return redirect(request.path)

    linked = (
        GuardianLink.objects.filter(
            guardian=target, status="aprovado"
        ).select_related("student")
        if is_admin
        else None
    )
    from apps.core.passwords import can_reset_password

    return render(
        request,
        "registry/guardian_profile.html",
        {
            "form": form,
            "target": target,
            "is_self": is_self,
            "is_admin": is_admin,
            "linked": linked,
            "can_reset_password": can_reset_password(request.user, target),
        },
    )


def my_children(request):
    if request.user.role != Role.RESPONSAVEL.value:
        raise PermissionDenied
    links = GuardianLink.objects.filter(
        guardian=request.user, status="aprovado"
    ).select_related("student")
    return render(request, "registry/my_children.html", {"links": links})


def link_list(request):
    user = request.user
    if can_manage_guardian_links(user):
        links = GuardianLink.objects.filter(school=user.school).select_related(
            "guardian", "student"
        )
    elif user.role == Role.RESPONSAVEL.value:
        links = GuardianLink.objects.filter(guardian=user).select_related("student")
    else:
        raise PermissionDenied
    status = request.GET.get("status", "")
    if status in ("pendente", "aprovado", "rejeitado"):
        links = links.filter(status=status)
    page = paginate(request, links.order_by("-created_at"))
    return render(
        request,
        "registry/link_list.html",
        {
            "links": page,
            "page": page,
            "status": status,
            "can_manage": can_manage_guardian_links(user),
        },
    )


def link_request(request):
    if request.user.role != Role.RESPONSAVEL.value:
        raise PermissionDenied
    form = GuardianLinkRequestForm(request.POST or None, guardian=request.user)
    if request.method == "POST" and form.is_valid():
        student = form.cleaned_data["student_name"]
        with transaction.atomic():
            link = GuardianLink.objects.create(
                school=request.user.school,
                guardian=request.user,
                student=student,
                relation=form.cleaned_data["relation"],
                status="pendente",
                requested_by=request.user,
            )
            create_audit_log(
                user=request.user,
                action="create",
                request=request,
                target=link,
                detail=f"Solicitou vínculo com o estudante {student.full_name}",
            )
        messages.success(
            request,
            "Solicitação enviada. A secretaria analisará e você poderá acompanhar o status na área de vínculos.",
        )
        return redirect("link_list")
    return render(request, "registry/link_request.html", {"form": form})


def link_create(request):
    if not can_manage_guardian_links(request.user):
        raise PermissionDenied
    form = GuardianLinkAdminForm(request.POST or None, school=request.user.school)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            link = form.save(commit=False)
            link.school = request.user.school
            link.status = "aprovado"
            link.requested_by = request.user
            link.validated_by = request.user
            from django.utils import timezone

            link.validated_at = timezone.now()
            link.save()
            create_audit_log(
                user=request.user,
                action="approve",
                request=request,
                target=link,
                detail=f"Vínculo criado e validado: {link.guardian} ↔ {link.student}",
            )
        messages.success(request, "Vínculo criado e validado.")
        return redirect("link_list")
    return render(request, "registry/link_form.html", {"form": form})


@require_POST
def link_approve(request, link_id):
    if not can_manage_guardian_links(request.user):
        raise PermissionDenied
    link = get_object_or_404(GuardianLink, pk=link_id, school=request.user.school)
    with transaction.atomic():
        link.status = "aprovado"
        link.validated_by = request.user
        from django.utils import timezone

        link.validated_at = timezone.now()
        link.rejection_reason = ""
        link.save()
        create_audit_log(
            user=request.user,
            action="approve",
            request=request,
            target=link,
            detail=f"Aprovou vínculo {link.guardian} ↔ {link.student}",
        )
    messages.success(request, "Vínculo aprovado.")
    return redirect("link_list")


@require_POST
def link_reject(request, link_id):
    if not can_manage_guardian_links(request.user):
        raise PermissionDenied
    link = get_object_or_404(GuardianLink, pk=link_id, school=request.user.school)
    reason = request.POST.get("reason", "").strip()
    with transaction.atomic():
        link.status = "rejeitado"
        link.validated_by = request.user
        link.rejection_reason = reason[:255]
        link.save()
        create_audit_log(
            user=request.user,
            action="reject",
            request=request,
            target=link,
            detail=f"Rejeitou vínculo {link.guardian} ↔ {link.student}: {reason[:120]}",
        )
    messages.success(request, "Vínculo rejeitado.")
    return redirect("link_list")


def enrollment_list(request):
    if not can_manage_registry(request.user):
        raise PermissionDenied
    qs = Enrollment.objects.filter(school=request.user.school).select_related(
        "student", "class_group", "school_year"
    )
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(student__first_name__icontains=q) | qs.filter(
            student__last_name__icontains=q
        )
    year_id = request.GET.get("year", "")
    status = request.GET.get("status", "")
    if year_id:
        qs = qs.filter(school_year_id=year_id)
    if status in ("ativo", "transferido", "concluido", "desistente"):
        qs = qs.filter(status=status)
    page = paginate(request, qs.order_by("-school_year__name"))
    return render(
        request,
        "registry/enrollment_list.html",
        {
            "enrollments": page,
            "page": page,
            "q": q,
            "years": SchoolYear.objects.filter(school=request.user.school),
            "statuses": Enrollment.STATUS_CHOICES,
        },
    )


def enrollment_create(request):
    if not can_manage_registry(request.user):
        raise PermissionDenied
    form = EnrollmentForm(request.POST or None, school=request.user.school)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            enrollment = form.save(commit=False)
            enrollment.school = request.user.school
            enrollment.save()
            create_audit_log(
                user=request.user,
                action="create",
                request=request,
                target=enrollment,
                detail=f"Matriculou {enrollment.student} em {enrollment.class_group} ({enrollment.school_year})",
            )
        messages.success(request, "Matrícula registrada.")
        return redirect("enrollment_list")
    return render(request, "registry/enrollment_form.html", {"form": form, "enrollment": None})


def enrollment_edit(request, enrollment_id):
    if not can_manage_registry(request.user):
        raise PermissionDenied
    enrollment = get_object_or_404(Enrollment, pk=enrollment_id, school=request.user.school)
    form = EnrollmentForm(
        request.POST or None, instance=enrollment, school=request.user.school
    )
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
            create_audit_log(
                user=request.user,
                action="update",
                request=request,
                target=enrollment,
                detail=f"Atualizou matrícula de {enrollment.student}",
            )
        messages.success(request, "Matrícula atualizada.")
        return redirect("enrollment_list")
    return render(
        request, "registry/enrollment_form.html", {"form": form, "enrollment": enrollment}
    )