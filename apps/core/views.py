from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from .access import role_required
from .forms import ProfessionalUserForm, PublicSignupForm
from .models import AuditLog, Role, School, User, create_audit_log


@role_required(Role.ADMIN)
def user_list(request):
    qs = User.objects.select_related("school")
    if request.user.school_id:
        qs = qs.filter(school=request.user.school)
    search = request.GET.get("q", "").strip()
    if search:
        qs = qs.filter(
            first_name__icontains=search
        ) | qs.filter(last_name__icontains=search) | qs.filter(username__icontains=search)
    return render(request, "core/user_list.html", {"users": qs.order_by("username"), "search": search})


@role_required(Role.ADMIN)
def user_create(request):
    allowed_schools = None
    if request.user.school_id:
        allowed_schools = School.objects.filter(pk=request.user.school_id)
    initial = {"school": request.user.school_id}
    form = ProfessionalUserForm(
        request.POST or None, initial=initial, allowed_schools=allowed_schools
    )
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = form.save()
            create_audit_log(
                user=request.user,
                action="create",
                request=request,
                target=user,
                detail=f"Criou conta do perfil {user.role_label}",
            )
        messages.success(request, f"Conta de {user.role_label} criada com sucesso.")
        return redirect("user_list")
    return render(request, "core/user_form.html", {"form": form})


@role_required(Role.ADMIN)
def user_detail(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    if request.user.school_id and user.school_id != request.user.school_id:
        messages.error(request, "Usuário não pertence à sua escola.")
        return redirect("user_list")
    logs = AuditLog.objects.filter(user=user)[:50]
    return render(request, "core/user_detail.html", {"target_user": user, "logs": logs})


@login_not_required
def signup(request):
    """Cadastro público de responsável. Nunca é possível se autodeclarar
    profissional por esta rota (o perfil é fixado no servidor)."""
    if request.user.is_authenticated:
        return redirect("home")
    form = PublicSignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = form.save()
            create_audit_log(
                user=user,
                action="create",
                request=request,
                target=user,
                detail="Cadastro público de responsável",
            )
        messages.success(
            request,
            "Conta de responsável criada. Faça login e solicite o vínculo com seu filho(a) na área de vínculos.",
        )
        return redirect("login")
    return render(request, "core/signup.html", {"form": form})


def home(request):
    context = {}
    user = request.user
    if user.is_authenticated:
        if user.role == Role.ADMIN.value:
            context["user_count"] = User.objects.filter(
                school=user.school, is_active=True
            ).count()
        elif user.role == Role.SECRETARIA.value:
            from apps.registry.models import GuardianLink, Student

            context["student_count"] = Student.objects.filter(school=user.school).count()
            context["pending_links"] = GuardianLink.objects.filter(
                school=user.school, status="pendente"
            ).count()
        elif user.role == Role.RESPONSAVEL.value:
            from apps.registry.models import GuardianLink

            context["child_count"] = GuardianLink.objects.filter(
                guardian=user, status="aprovado"
            ).count()
        elif user.role == Role.PROFESSOR.value:
            from apps.academics.models import TeacherAssignment

            context["assignment_count"] = TeacherAssignment.objects.filter(
                teacher=user
            ).count()
    return render(request, "home.html", context)