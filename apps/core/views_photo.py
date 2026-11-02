"""Fotografia de perfil de todos os usuários, pendências e dispensas.

A foto é um recurso visual de identificação. Ela nunca bloqueia acesso a
nada e nunca é usada para reconhecimento facial ou biometria.

Onde fica a foto de cada um:
- equipe (direção, coordenação, secretaria, professor, administração):
  ``User.photo``;
- família: ``GuardianProfile.photo`` (já existia);
- estudante: ``Student.photo`` (cuidada pela secretaria e, se a escola
  permitir, pela família).
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import STAFF_ROLES, Role, User, create_audit_log
from .pagination import paginate
from .photos import save_photo

STAFF = [r.value for r in STAFF_ROLES]


def can_manage_photos(user):
    """Lista de pendências e cobrança: secretaria, direção e administração."""
    return user.is_authenticated and user.role in (Role.SECRETARIA.value, Role.DIRECAO.value, Role.ADMIN.value)


def can_grant_photo_exception(user):
    """Dispensa justificada: só a administração (direção e administrador)."""
    return user.is_authenticated and user.role in (Role.DIRECAO.value, Role.ADMIN.value)


def _photo_holder(user):
    """(objeto, campo) onde fica a foto desta conta, ou (None, None)."""
    if user.role in STAFF:
        return user, "photo"
    if user.role == Role.RESPONSAVEL.value:
        from apps.registry.models import GuardianProfile

        profile, _ = GuardianProfile.objects.get_or_create(user=user)
        return profile, "photo"
    return None, None


def has_photo(user):
    if user.role in STAFF:
        return bool(user.photo)
    if user.role == Role.RESPONSAVEL.value:
        profile = getattr(user, "guardian_profile", None)
        return bool(profile and profile.photo)
    if user.role == Role.ESTUDANTE.value:
        st = getattr(user, "student_record", None)
        return bool(st and st.photo)
    return True


def photo_exempt(user):
    from apps.registry.models import PhotoException

    return PhotoException.objects.filter(user=user).exists()


def my_photo(request):
    user = request.user
    holder, field = _photo_holder(user)
    error = None
    if holder is not None and request.method == "POST":
        upload = request.FILES.get("photo")
        if not upload:
            error = "Escolha uma foto."
        else:
            try:
                with transaction.atomic():
                    save_photo(holder, field, upload, name_hint=f"perfil-{user.pk}")
                    holder.save()
                    create_audit_log(user=user, action="update", request=request, target=user,
                                     detail="Atualizou a própria fotografia de perfil")
            except ValidationError as exc:
                error = " ".join(exc.messages)
            else:
                messages.success(request, "Foto atualizada.")
                return redirect("my_photo")
    return render(request, "core/my_photo.html", {
        "holder": holder, "has_photo": has_photo(user), "error": error,
    })


def user_photo(request, user_id):
    """Foto de uma conta da equipe. Qualquer pessoa da mesma escola vê a foto
    da equipe (identificar quem é a professora, a coordenadora...). Fotos de
    famílias e estudantes têm views próprias, com regra por vínculo."""
    target = get_object_or_404(User, pk=user_id)
    if target.role not in STAFF and target.pk != request.user.pk:
        raise Http404
    if target.pk != request.user.pk and target.school_id != request.user.school_id:
        raise Http404
    if target.role not in STAFF or not target.photo:
        raise Http404
    resp = FileResponse(target.photo.open("rb"), content_type="image/jpeg")
    resp["Cache-Control"] = "private, max-age=300"
    return resp


@require_POST
def staff_photo_upload(request, user_id):
    """Administração envia a foto de uma conta da equipe."""
    if request.user.role != Role.ADMIN.value:
        raise PermissionDenied
    target = get_object_or_404(User, pk=user_id, school=request.user.school, role__in=STAFF)
    upload = request.FILES.get("photo")
    try:
        if not upload:
            raise ValidationError("Escolha uma foto.")
        with transaction.atomic():
            save_photo(target, "photo", upload, name_hint=f"perfil-{target.pk}")
            target.save(update_fields=["photo"])
            create_audit_log(user=request.user, action="update", request=request, target=target,
                             detail=f"Atualizou a fotografia de {target.get_full_name() or target.username}")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "Foto atualizada.")
    return redirect("user_detail", user_id=target.pk)


# --------------------------------------------------------------------------
# Pendências


def photo_pending(request):
    if not can_manage_photos(request.user):
        raise PermissionDenied
    from apps.academics.models import ClassGroup
    from apps.registry.models import Enrollment, GuardianProfile, PhotoException, Student

    school = request.user.school
    tab = request.GET.get("aba", "estudantes")
    class_id = request.GET.get("turma", "")
    q = request.GET.get("q", "").strip()
    exempt_students = PhotoException.objects.filter(student=OuterRef("pk"))
    exempt_users = PhotoException.objects.filter(user=OuterRef("pk"))

    students = (
        Student.objects.filter(school=school, status="ativo")
        .filter(Q(photo="") | Q(photo__isnull=True))
        .annotate(exempt=Exists(exempt_students)).filter(exempt=False)
    )
    staff = (
        User.objects.filter(school=school, role__in=STAFF, is_active=True)
        .filter(Q(photo="") | Q(photo__isnull=True))
        .annotate(exempt=Exists(exempt_users)).filter(exempt=False)
    )
    with_photo = GuardianProfile.objects.filter(user=OuterRef("pk")).exclude(photo="").exclude(photo__isnull=True)
    families = (
        User.objects.filter(school=school, role=Role.RESPONSAVEL.value, is_active=True)
        .annotate(ok=Exists(with_photo), exempt=Exists(exempt_users)).filter(ok=False, exempt=False)
    )
    counts = {"estudantes": students.count(), "equipe": staff.count(), "familias": families.count()}

    if tab == "equipe":
        qs = staff.order_by("first_name", "last_name")
    elif tab == "familias":
        qs = families.order_by("first_name", "last_name")
    else:
        tab = "estudantes"
        if class_id.isdigit():
            students = students.filter(enrollments__class_group_id=class_id, enrollments__status="ativo")
        qs = students.order_by("first_name", "last_name")
    if q:
        qs = qs.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q))
    page = paginate(request, qs.distinct())
    if tab == "estudantes":
        current = dict(
            Enrollment.objects.filter(student__in=[s.pk for s in page], status="ativo")
            .values_list("student_id", "class_group__name")
        )
        for s in page:
            s.current_class = current.get(s.pk)
    exceptions = PhotoException.objects.filter(school=school).select_related("student", "user", "granted_by") \
        .order_by("-created_at")[:50]
    return render(request, "core/photo_pending.html", {
        "tab": tab, "page": page, "rows": page, "counts": counts, "q": q, "class_id": class_id,
        "classes": ClassGroup.objects.filter(school=school).order_by("name"),
        "exceptions": exceptions, "can_exempt": can_grant_photo_exception(request.user),
    })


@require_POST
def photo_remind(request):
    """Cobra a foto: avisa as famílias dos estudantes marcados (ou as próprias
    contas, na aba equipe/famílias). Um aviso por pessoa e assunto por dia."""
    if not can_manage_photos(request.user):
        raise PermissionDenied
    from apps.communication.models import Notification
    from apps.communication.services import notify
    from apps.registry.models import GuardianLink, Student

    school = request.user.school
    tab = request.POST.get("aba", "estudantes")
    tab = tab if tab in ("estudantes", "equipe", "familias") else "estudantes"
    ids = [int(i) for i in request.POST.getlist("ids") if i.isdigit()][:500]
    today = timezone.localdate().isoformat()
    sent = 0
    if tab == "estudantes":
        for st in Student.objects.filter(school=school, pk__in=ids):
            links = GuardianLink.objects.filter(student=st, status="aprovado", guardian__is_active=True) \
                .select_related("guardian")
            for link in links:
                if notify(school, link.guardian, Notification.Kind.PHOTO, f"Falta a foto de {st.first_name}",
                          body="A escola pede uma foto de identificação do estudante. Envie em “Meus filhos” "
                               "ou leve à secretaria.",
                          url=reverse("my_children"), student=st, dedupe_key=f"foto-{st.pk}-{today}"):
                    sent += 1
    else:
        for u in User.objects.filter(school=school, pk__in=ids, is_active=True):
            if notify(school, u, Notification.Kind.PHOTO, "Adicione sua foto de identificação",
                      body="A escola pede que todas as contas tenham foto. Leva um minuto.",
                      url=reverse("my_photo"), dedupe_key=f"foto-conta-{u.pk}-{today}"):
                sent += 1
    create_audit_log(user=request.user, action="update", request=request, target_type="foto",
                     target_id="cobranca", detail=f"Cobrou fotografia ({tab}): {sent} aviso(s)")
    messages.success(request, f"{sent} aviso(s) enviado(s)." if sent else
                     "Nenhum aviso novo: já avisados hoje ou sem família com vínculo aprovado.")
    return redirect(f"{reverse('photo_pending')}?aba={tab}")


@require_POST
def photo_exception_create(request):
    if not can_grant_photo_exception(request.user):
        raise PermissionDenied
    from apps.registry.models import PhotoException, Student

    reason = (request.POST.get("reason") or "").strip()[:300]
    kind, pk = request.POST.get("kind"), request.POST.get("id", "")
    if not reason or not pk.isdigit():
        messages.error(request, "Informe a justificativa da dispensa.")
        return redirect("photo_pending")
    school = request.user.school
    if kind == "estudante":
        target = get_object_or_404(Student, pk=pk, school=school)
        exc = PhotoException.objects.create(school=school, student=target, reason=reason, granted_by=request.user)
        label = target.full_name
    else:
        target = get_object_or_404(User, pk=pk, school=school)
        exc = PhotoException.objects.create(school=school, user=target, reason=reason, granted_by=request.user)
        label = target.get_full_name() or target.username
    create_audit_log(user=request.user, action="create", request=request, target=exc,
                     detail=f"Dispensou a fotografia de {label}: {reason}")
    messages.success(request, f"Dispensa registrada para {label}.")
    return redirect("photo_pending")


@require_POST
def photo_exception_revoke(request, pk):
    if not can_grant_photo_exception(request.user):
        raise PermissionDenied
    from apps.registry.models import PhotoException

    exc = get_object_or_404(PhotoException, pk=pk, school=request.user.school)
    label = exc.student.full_name if exc.student_id else (exc.user.get_full_name() or exc.user.username)
    create_audit_log(user=request.user, action="delete", request=request, target_type="PhotoException",
                     target_id=str(exc.pk), detail=f"Revogou a dispensa de fotografia de {label}")
    exc.delete()
    messages.success(request, "Dispensa revogada: a pendência volta a aparecer.")
    return redirect("photo_pending")


def pending_center(request):
    """Central de pendências do usuário (todos os perfis)."""
    from .pending import for_user

    from .views_followup import is_staff_user

    items = for_user(request.user)
    return render(request, "core/pending.html", {"items": items, "total": sum(i["count"] for i in items),
                                                 "is_staff": is_staff_user(request.user)})
