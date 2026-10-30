from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .access import role_required
from .forms import ProfessionalUserForm, PublicSignupForm
from .models import AuditLog, Role, School, User, create_audit_log
from .pagination import Sort, paginate
from .passwords import can_reset_password, reset_password


@role_required(Role.ADMIN)
def user_list(request):
    qs = User.objects.select_related("school", "guardian_profile")
    if request.user.school_id:
        qs = qs.filter(school=request.user.school)
    search = request.GET.get("q", "").strip()
    if search:
        qs = qs.filter(
            first_name__icontains=search
        ) | qs.filter(last_name__icontains=search) | qs.filter(username__icontains=search)
    perfil = request.GET.get("perfil")
    if perfil in Role.values:
        qs = qs.filter(role=perfil)
    sort = Sort(request, {"usuario": "username", "nome": ("first_name", "last_name"), "perfil": ("role", "username"),
                          "status": ("is_active", "username")}, "usuario")
    page = paginate(request, sort.apply(qs))
    return render(
        request,
        "core/user_list.html",
        {"users": page, "page": page, "search": search, "sort": sort, "perfil": perfil,
         "role_choices": Role.choices, "filtered": bool(search or perfil),
         # Com escola definida, todas as linhas teriam o mesmo nome: a coluna sai.
         "show_school": not request.user.school_id},
    )


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
    return render(
        request,
        "core/user_detail.html",
        {
            "target_user": user,
            "logs": logs,
            "can_reset_password": can_reset_password(request.user, user),
        },
    )


@require_POST
def password_reset_user(request, user_id):
    """Gera senha temporária para outra conta e a mostra uma única vez.

    Exige POST para que um link ou um prefetch do navegador não possa
    invalidar a senha de alguém por navegação acidental.
    """
    target = get_object_or_404(User, pk=user_id)
    if not can_reset_password(request.user, target):
        raise PermissionDenied
    with transaction.atomic():
        senha = reset_password(request.user, target)
        create_audit_log(
            user=request.user,
            action="update",
            request=request,
            target=target,
            detail=(
                f"Redefiniu a senha de {target.username} "
                f"({target.role_label}); troca obrigatória no próximo acesso"
            ),
        )
    return render(
        request,
        "core/password_reset_done.html",
        {"target_user": target, "temp_password": senha},
    )


class ForcedPasswordChangeView(auth_views.PasswordChangeView):
    """Troca de senha que também limpa a marca de senha temporária.

    Sem limpar aqui, o middleware continuaria exigindo a troca depois de ela
    já ter acontecido, e o usuário ficaria preso.
    """

    def form_valid(self, form):
        response = super().form_valid(form)
        user = form.user
        if user.must_change_password:
            user.must_change_password = False
            user.save(update_fields=["must_change_password"])
            create_audit_log(
                user=user,
                action="update",
                request=self.request,
                target=user,
                detail="Trocou a senha temporária no primeiro acesso",
            )
        return response


SIGNUP_LIMIT_PER_HOUR = 5


def _signup_limit_reached(request):
    """Cadastro público limitado por endereço: sem isso, um robô podia criar
    contas em massa. Conta os cadastros já gravados na auditoria."""
    from datetime import timedelta

    ip = request.META.get("REMOTE_ADDR")
    if not ip:
        return False
    since = timezone.now() - timedelta(hours=1)
    return AuditLog.objects.filter(
        action="create", detail="Cadastro público de responsável", ip_address=ip, created_at__gte=since,
    ).count() >= SIGNUP_LIMIT_PER_HOUR


@login_not_required
def signup(request):
    """Cadastro público de responsável. Nunca é possível se autodeclarar
    profissional por esta rota (o perfil é fixado no servidor)."""
    if request.user.is_authenticated:
        return redirect("home")
    form = PublicSignupForm(request.POST or None)
    if request.method == "POST" and _signup_limit_reached(request):
        form.is_valid()
        form.add_error(None, "Muitos cadastros feitos a partir desta rede na última hora. "
                             "Tente mais tarde ou procure a secretaria da escola.")
    elif request.method == "POST" and form.is_valid():
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
    """Tela "Hoje": o que pede ação para este perfil (ver core.workspace)."""
    from . import workspace

    return render(request, "home.html", {"ws": workspace.build(request.user)})

def help_page(request):
    """Ajuda por perfil: guias passo a passo e perguntas frequentes."""
    from . import help as help_content
    from .navigation import all_visible_urls

    return render(request, "core/help.html",
                  help_content.build(request.user, all_visible_urls(request.user)))


SEARCH_LIMIT = 8


def global_search(request):
    """Busca de registros para a paleta Ctrl+K (estudantes e turmas).

    Usa exatamente as regras de acesso das telas de destino: estudantes por
    ``students_visible_to`` (a mesma da lista de estudantes) e turmas pelo
    painel da turma. Nada que a pessoa não possa abrir aparece no resultado.
    Páginas e ações não passam por aqui: já vêm no HTML, filtradas por perfil.
    """
    from django.db.models import Q
    from django.http import JsonResponse
    from django.urls import reverse

    from apps.academics.models import ClassGroup, TeacherAssignment
    from apps.registry.access import ADMIN_RECORD_ROLES, students_visible_to

    user = request.user
    q = " ".join(request.GET.get("q", "").split())[:60]
    results = []
    if len(q) >= 2:
        students = students_visible_to(user)
        if students is not None:
            filtro = Q()
            for termo in q.split():
                filtro &= Q(first_name__icontains=termo) | Q(last_name__icontains=termo)
            encontrados = list(
                students.filter(filtro).order_by("first_name", "last_name")[:SEARCH_LIMIT]
            )
            # A turma atual distingue homônimos (três "Alice Almeida" numa
            # escola não podem aparecer iguais no resultado).
            from apps.registry.models import Enrollment

            turma_atual = dict(
                Enrollment.objects.filter(
                    student__in=encontrados, status="ativo"
                ).values_list("student_id", "class_group__name")
            )
            for st in encontrados:
                turma = turma_atual.get(st.pk)
                results.append({
                    "group": "Estudantes",
                    "label": st.full_name,
                    "url": reverse("student_detail", args=[st.pk]),
                    "icon": "user-round",
                    "hint": f"Turma {turma}" if turma else "Sem matrícula ativa",
                })
        turmas = None
        if user.role in ADMIN_RECORD_ROLES:
            turmas = ClassGroup.objects.filter(school=user.school)
        elif user.role == Role.PROFESSOR.value:
            turmas = ClassGroup.objects.filter(
                pk__in=TeacherAssignment.objects.filter(teacher=user).values("class_group_id")
            )
        if turmas is not None:
            for cg in turmas.filter(name__icontains=q).select_related("school_year").order_by(
                "name"
            )[:SEARCH_LIMIT]:
                results.append({
                    "group": "Turmas",
                    "label": cg.name,
                    "url": reverse("analytics:class_dashboard", args=[cg.pk]),
                    "icon": "layers",
                    "hint": f"Painel da turma · {cg.school_year.name}",
                })
    return JsonResponse({"results": results})
