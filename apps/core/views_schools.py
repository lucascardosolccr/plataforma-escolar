"""Escolas da plataforma e convites da equipe (regras em ``apps.core.invites``)."""

from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import invites
from .forms import InviteForm, InviteSignupForm, SchoolForm
from .models import STAFF_ROLES, InviteCode, InviteSignup, Role, School, User, create_audit_log

STAFF = [r.value for r in STAFF_ROLES]
SIGNUP_DETAIL = "Cadastro por convite"
FAILED_DETAIL = "Convite: código recusado"


def _platform_admin(request):
    if not invites.is_platform_admin(request.user):
        raise PermissionDenied


def _school_for(request, school_id):
    school = get_object_or_404(School, pk=school_id)
    if not invites.can_manage_school(request.user, school):
        raise PermissionDenied
    return school


# --------------------------------------------------------------------------- administrador da plataforma


def school_list(request):
    _platform_admin(request)
    q = (request.GET.get("q") or "").strip()[:80]
    schools = School.objects.annotate(
        staff=Count("users", filter=Q(users__role__in=STAFF, users__is_active=True), distinct=True),
        families=Count("users", filter=Q(users__role=Role.RESPONSAVEL.value), distinct=True),
        pending=Count("invite_codes__signups", filter=Q(invite_codes__signups__status=InviteSignup.Status.PENDING),
                      distinct=True),
    ).order_by("name")
    if q:
        schools = schools.filter(Q(name__icontains=q) | Q(code__icontains=q) | Q(city__icontains=q) | Q(inep=q))
    from apps.registry.models import Student

    students = dict(Student.objects.filter(status="ativo").values_list("school").annotate(n=Count("pk")))
    rows = [{"s": s, "students": students.get(s.pk, 0)} for s in schools]
    return render(request, "core/school_list.html", {"rows": rows, "q": q})


def school_create(request):
    _platform_admin(request)
    form = SchoolForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            school = form.save()
            invite = invites.create_invite(school, Role.DIRECAO.value, request.user, note="Direção da escola")
            create_audit_log(user=request.user, action="create", request=request, target=school, school=school,
                             detail=f"Cadastrou a escola {school.name} e gerou o convite da direção")
        messages.success(request, f"Escola cadastrada. Envie à direção o código {invite.display_code} "
                                  f"(vale para 1 cadastro, por 14 dias).")
        return redirect("school_team", school.pk)
    return render(request, "core/school_form.html", {"form": form})


def school_edit(request, school_id):
    _platform_admin(request)
    school = get_object_or_404(School, pk=school_id)
    form = SchoolForm(request.POST or None, instance=school)
    if request.method == "POST" and form.is_valid():
        form.save()
        create_audit_log(user=request.user, action="update", request=request, target=school, school=school,
                         detail="Alterou os dados da escola")
        messages.success(request, "Dados da escola salvos.")
        return redirect("school_team", school.pk)
    return render(request, "core/school_form.html", {"form": form, "school": school})


@require_POST
def school_switch(request, school_id):
    """O administrador da plataforma passa a trabalhar nesta escola (as telas do dia a dia usam a escola da
    conta)."""
    _platform_admin(request)
    school = get_object_or_404(School, pk=school_id)
    request.user.school = school
    request.user.save(update_fields=["school"])
    create_audit_log(user=request.user, action="update", request=request, target=school, school=school,
                     detail=f"Passou a trabalhar na escola {school.name}")
    messages.success(request, f"Agora você está trabalhando na escola {school.name}.")
    return redirect("home")


# --------------------------------------------------------------------------- equipe e convites de uma escola


def my_team(request):
    if request.user.school_id is None:
        if invites.is_platform_admin(request.user):
            return redirect("school_list")
        raise PermissionDenied
    return school_team(request, request.user.school_id)


def school_team(request, school_id):
    school = _school_for(request, school_id)
    roles = invites.roles_user_can_invite(request.user)
    now = timezone.now()
    all_invites = list(invites.with_usage(school.invite_codes.select_related("created_by")))
    for inv in all_invites:
        inv.state, _ = invites.state(inv, now)
    show_old = request.GET.get("todos") == "1"
    team = (User.objects.filter(school=school, role__in=STAFF)
            .select_related("invite_signup__invite").order_by("role", "first_name", "username"))
    return render(request, "core/school_team.html", {
        "school": school, "form": InviteForm(roles=roles), "can_invite": bool(roles),
        "invites": [i for i in all_invites if show_old or i.state == "ativo"],
        "hidden_invites": sum(1 for i in all_invites if i.state != "ativo") if not show_old else 0,
        "pending": invites.pending_for(school), "team": team,
        "platform_admin": invites.is_platform_admin(request.user),
        "signup_url": request.build_absolute_uri("/cadastro/convite/"),
        "recent_rejected": InviteSignup.objects.filter(invite__school=school,
                                                       status=InviteSignup.Status.REJECTED)[:5],
    })


@require_POST
def invite_create(request, school_id):
    school = _school_for(request, school_id)
    form = InviteForm(request.POST, roles=invites.roles_user_can_invite(request.user))
    if not form.is_valid():
        messages.error(request, "Confira o convite: " + "; ".join(e for errs in form.errors.values() for e in errs))
        return redirect("school_team", school.pk)
    invite = invites.create_invite(school, form.cleaned_data["role"], request.user, note=form.cleaned_data["note"],
                                   max_uses=form.cleaned_data["max_uses"], days=form.cleaned_data["days"],
                                   requires_approval=form.approval_value())
    create_audit_log(user=request.user, action="create", request=request, target=invite, school=school,
                     detail=f"Gerou convite de {invite.get_role_display()} ({invite.max_uses} cadastro(s), até "
                            f"{timezone.localtime(invite.expires_at):%d/%m/%Y})")
    messages.success(request, f"Convite criado: {invite.display_code}. Copie o código ou o link e envie.")
    return redirect("school_team", school.pk)


@require_POST
def invite_revoke(request, invite_id):
    invite = get_object_or_404(InviteCode, pk=invite_id)
    _school_for(request, invite.school_id)
    if invite.role not in invites.roles_user_can_invite(request.user):
        raise PermissionDenied
    if not invite.revoked_at:
        invites.revoke(invite, request.user)
        create_audit_log(user=request.user, action="update", request=request, target=invite, school=invite.school,
                         detail=f"Cancelou o convite {invite.display_code}")
        messages.success(request, "Convite cancelado: o código não aceita mais cadastros. As contas já criadas "
                                  "continuam valendo.")
    return redirect("school_team", invite.school_id)


@require_POST
def signup_decide(request, signup_id):
    signup = get_object_or_404(InviteSignup.objects.select_related("invite", "user"), pk=signup_id,
                               status=InviteSignup.Status.PENDING)
    school = _school_for(request, signup.invite.school_id)
    approve = request.POST.get("decisao") == "aprovar"
    name = signup.name
    invites.decide(signup, approve, request.user)
    create_audit_log(user=request.user, action="approve" if approve else "reject", request=request,
                     target=signup, school=school,
                     detail=f"{'Aprovou' if approve else 'Recusou'} o cadastro de {name} "
                            f"({signup.invite.get_role_display()}) por convite")
    if approve:
        messages.success(request, f"Cadastro de {name} aprovado: a conta já funciona.")
    else:
        messages.success(request, f"Cadastro de {name} recusado: a conta foi apagada.")
    return redirect("school_team", school.pk)


# --------------------------------------------------------------------------- cadastro público com o código


@login_not_required
def invite_signup(request):
    if request.user.is_authenticated:
        return redirect("home")
    initial = {"code": (request.GET.get("codigo") or "")[:40]}
    form = InviteSignupForm(request.POST or None, initial=initial)
    invite = None
    if request.method == "GET" and initial["code"]:
        invite, _ = invites.find(initial["code"])
    if request.method == "POST":
        if invites.too_many(request, FAILED_DETAIL, invites.FAILED_LIMIT_PER_HOUR) or \
                invites.too_many(request, SIGNUP_DETAIL, invites.SIGNUP_LIMIT_PER_HOUR):
            form.is_valid()
            form.add_error(None, "Muitas tentativas a partir desta rede na última hora. Tente mais tarde.")
        elif form.is_valid():
            try:
                signup = invites.sign_up(form.invite, form.cleaned_data)
            except ValueError as exc:  # o convite esgotou entre a conferência e o cadastro
                form.add_error("code", str(exc))
            else:
                create_audit_log(user=signup.user, action="create", request=request, target=signup.user,
                                 school=form.invite.school,
                                 detail=f"{SIGNUP_DETAIL}: {form.invite.get_role_display()} com o código "
                                        f"{form.invite.display_code}")
                return render(request, "core/invite_done.html", {"signup": signup, "invite": form.invite})
        elif "code" in form.errors:
            create_audit_log(user=None, action="reject", request=request, target_type="convite",
                             target_id=invites.normalize(request.POST.get("code", ""))[:12],
                             detail=f"{FAILED_DETAIL}. {form.errors['code'][0]}"[:250])
        invite = getattr(form, "invite", None)
    return render(request, "core/invite_signup.html", {"form": form, "invite": invite})
