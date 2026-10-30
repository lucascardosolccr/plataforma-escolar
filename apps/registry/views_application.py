"""Pré-cadastro de estudante pela família, análise pela secretaria, envio
de foto pela família e configurações de cadastro.

Regra de ouro: nada que a família envia vira ficha ou matrícula sem a
secretaria aprovar. A família só vê e mexe nos próprios pré-cadastros.
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.academics.models import SchoolYear
from apps.communication.models import Notification
from apps.communication.services import notify, notify_many
from apps.core.models import Role, User, create_audit_log
from apps.core.pagination import paginate
from apps.core.photos import process_photo, save_photo
from apps.core.uploads import attachment_content_type

from .access import guardian_of
from .forms_application import (
    ApplicationContactForm,
    ApplicationDocumentForm,
    ApplicationPhotoForm,
    ApplicationStudentForm,
    RegistrationSettingsForm,
    ReviewForm,
)
from .models import (
    ApplicationDocument,
    Enrollment,
    GuardianLink,
    GuardianProfile,
    RegistrationSettings,
    Student,
    StudentApplication,
)

STEPS = [(1, "Estudante"), (2, "Contato"), (3, "Foto e documentos"), (4, "Revisar e enviar")]


def can_review_applications(user):
    return user.is_authenticated and user.role in (Role.SECRETARIA.value, Role.ADMIN.value)


def can_edit_registration_settings(user):
    return user.is_authenticated and user.role in (
        Role.SECRETARIA.value, Role.DIRECAO.value, Role.ADMIN.value
    )


def _family_only(user):
    if not user.is_authenticated or user.role != Role.RESPONSAVEL.value:
        raise PermissionDenied


def _own_application(request, pk):
    _family_only(request.user)
    return get_object_or_404(StudentApplication, pk=pk, guardian=request.user, school=request.user.school)


def _year_for(settings_obj):
    return settings_obj.school_year or SchoolYear.objects.filter(
        school=settings_obj.school, is_current=True
    ).first()


# --------------------------------------------------------------------------
# Família


def family_applications(request):
    _family_only(request.user)
    cfg = RegistrationSettings.for_school(request.user.school)
    apps = StudentApplication.objects.filter(guardian=request.user).select_related("student")
    return render(request, "registry/application_family_list.html", {
        "applications": apps, "cfg": cfg, "can_apply": cfg.family_can_apply,
    })


@require_POST
def application_start(request):
    _family_only(request.user)
    cfg = RegistrationSettings.for_school(request.user.school)
    if not cfg.family_can_apply:
        messages.error(request, "O cadastro pela família não está aberto nesta escola agora.")
        return redirect("family_applications")
    profile = GuardianProfile.objects.filter(user=request.user).first()
    app = StudentApplication.objects.create(
        school=request.user.school, guardian=request.user,
        phone=getattr(profile, "phone", ""), address=getattr(profile, "address", ""),
        relation=getattr(profile, "relation", ""),
    )
    return redirect("application_step", pk=app.pk, step=1)


def application_step(request, pk, step):
    app = _own_application(request, pk)
    cfg = RegistrationSettings.for_school(request.user.school)
    if step not in dict(STEPS):
        raise Http404
    if not app.editable:
        return redirect("application_view", pk=app.pk)
    enabled = cfg.fields_list
    form = doc_form = None
    if step == 1:
        form = ApplicationStudentForm(request.POST or None, instance=app, enabled=enabled)
    elif step == 2:
        form = ApplicationContactForm(request.POST or None, instance=app, enabled=enabled)
    elif step == 3:
        if "photo" in enabled:
            form = ApplicationPhotoForm(request.POST or None, request.FILES or None)
        if "documents" in enabled:
            doc_form = ApplicationDocumentForm(prefix="doc")

    if request.method == "POST":
        nav = request.POST.get("nav", "next")
        if step == 3 and request.POST.get("add_document") and "documents" in enabled:
            doc_form = ApplicationDocumentForm(request.POST, request.FILES, prefix="doc")
            if doc_form.is_valid() and app.documents.count() < 6:
                doc = doc_form.save(commit=False)
                doc.application = app
                doc.original_name = doc_form.cleaned_data["file"].name[:200]
                doc.save()
                messages.success(request, "Documento anexado.")
                return redirect("application_step", pk=app.pk, step=3)
        elif form is None or form.is_valid():
            if form is not None:
                obj = form.save(commit=False) if step != 3 else app
                if step == 3 and form.cleaned_data.get("photo"):
                    try:
                        save_photo(obj, "photo", form.cleaned_data["photo"], name_hint="pre-cadastro")
                    except ValidationError as exc:
                        form.add_error("photo", exc)
                if not form.errors:
                    obj.step = max(obj.step, step + 1 if step < 4 else 4)
                    obj.save()
            else:
                app.step = max(app.step, step + 1)
                app.save(update_fields=["step", "updated_at"])
            if form is None or not form.errors:
                if nav == "save":
                    messages.success(request, "Progresso salvo. Você pode continuar depois em “Pré-cadastro”.")
                    return redirect("family_applications")
                if nav == "back":
                    return redirect("application_step", pk=app.pk, step=max(1, step - 1))
                return redirect("application_step", pk=app.pk, step=min(4, step + 1))

    missing = _missing(app)
    return render(request, "registry/application_step.html", {
        "app": app, "step": step, "steps": STEPS, "form": form, "doc_form": doc_form,
        "enabled": enabled, "missing": missing, "cfg": cfg,
    })


def _missing(app):
    out = []
    if not app.first_name:
        out.append("nome do estudante")
    if not app.birth_date:
        out.append("data de nascimento")
    if not app.desired_grade:
        out.append("ano/série")
    return out


@require_POST
def application_document_delete(request, pk, doc_id):
    app = _own_application(request, pk)
    if not app.editable:
        raise PermissionDenied
    doc = get_object_or_404(ApplicationDocument, pk=doc_id, application=app)
    doc.file.delete(save=False)
    doc.delete()
    messages.info(request, "Documento removido.")
    return redirect("application_step", pk=app.pk, step=3)


@require_POST
def application_submit(request, pk):
    app = _own_application(request, pk)
    if not app.editable:
        messages.error(request, "Este pré-cadastro já foi enviado.")
        return redirect("application_view", pk=app.pk)
    if _missing(app):
        messages.error(request, "Falta preencher: " + ", ".join(_missing(app)) + ".")
        return redirect("application_step", pk=app.pk, step=1)
    with transaction.atomic():
        resent = app.status == StudentApplication.Status.CORRECTION
        app.status = StudentApplication.Status.SUBMITTED
        app.submitted_at = timezone.now()
        app.save(update_fields=["status", "submitted_at", "updated_at"])
        create_audit_log(user=request.user, action="update" if resent else "create", request=request,
                         target=app, detail=f"Enviou o pré-cadastro de {app.full_name}")
        reviewers = User.objects.filter(school=app.school, role=Role.SECRETARIA.value, is_active=True)
        notify_many(
            app.school, reviewers, Notification.Kind.REGISTRATION,
            f"{'Pré-cadastro corrigido' if resent else 'Novo pré-cadastro'}: {app.full_name}",
            body=f"Enviado por {request.user.get_full_name() or request.user.username}. Ano/série: {app.desired_grade}.",
            url=reverse("application_review", args=[app.pk]),
        )
    messages.success(request, "Pré-cadastro enviado. A secretaria vai analisar e você será avisado aqui.")
    return redirect("application_view", pk=app.pk)


@require_POST
def application_cancel(request, pk):
    app = _own_application(request, pk)
    if app.status not in (*StudentApplication.EDITABLE, StudentApplication.Status.SUBMITTED):
        raise PermissionDenied
    app.status = StudentApplication.Status.CANCELED
    app.save(update_fields=["status", "updated_at"])
    create_audit_log(user=request.user, action="update", request=request, target=app,
                     detail=f"Cancelou o pré-cadastro de {app.full_name}")
    messages.info(request, "Pré-cadastro cancelado.")
    return redirect("family_applications")


def application_view(request, pk):
    """Situação do pré-cadastro, para a família que o fez."""
    app = _own_application(request, pk)
    return render(request, "registry/application_view.html", {
        "app": app, "documents": app.documents.all(), "steps": STEPS,
    })


# --------------------------------------------------------------------------
# Arquivos (só a família dona e quem analisa)


def _can_see_application(user, app):
    if user.role == Role.RESPONSAVEL.value:
        return app.guardian_id == user.pk
    return can_review_applications(user) and app.school_id == user.school_id


def application_photo(request, pk):
    app = get_object_or_404(StudentApplication, pk=pk)
    if not _can_see_application(request.user, app) or not app.photo:
        raise Http404
    resp = FileResponse(app.photo.open("rb"), content_type="image/jpeg")
    resp["Cache-Control"] = "private, no-store"
    return resp


def application_document(request, pk, doc_id):
    app = get_object_or_404(StudentApplication, pk=pk)
    if not _can_see_application(request.user, app):
        raise Http404
    doc = get_object_or_404(ApplicationDocument, pk=doc_id, application=app)
    resp = FileResponse(doc.file.open("rb"), as_attachment=True, filename=doc.original_name,
                        content_type=attachment_content_type(doc.original_name))
    resp["Cache-Control"] = "private, no-store"
    return resp


# --------------------------------------------------------------------------
# Secretaria


def review_list(request):
    if not can_review_applications(request.user):
        raise PermissionDenied
    status = request.GET.get("situacao", StudentApplication.Status.SUBMITTED)
    qs = StudentApplication.objects.filter(school=request.user.school).exclude(
        status=StudentApplication.Status.DRAFT
    ).select_related("guardian", "student")
    counts = dict(qs.values_list("status").annotate(n=Count("pk")))
    if status in dict(StudentApplication.Status.choices):
        qs = qs.filter(status=status)
    else:
        status = ""
    page = paginate(request, qs.order_by("submitted_at", "pk"))
    tabs = [(k, label, counts.get(k, 0)) for k, label in StudentApplication.Status.choices if k != "rascunho"]
    return render(request, "registry/application_review_list.html", {
        "applications": page, "page": page, "status": status, "tabs": tabs,
    })


def _matches(app):
    """Fichas que podem ser a mesma criança: nome e nascimento exatos."""
    if not (app.first_name and app.birth_date):
        return Student.objects.none()
    return Student.objects.filter(
        school=app.school, first_name__iexact=app.first_name.strip(),
        last_name__iexact=app.last_name.strip(), birth_date=app.birth_date,
    )


def application_review(request, pk):
    if not can_review_applications(request.user):
        raise PermissionDenied
    app = get_object_or_404(
        StudentApplication.objects.select_related("guardian", "student"),
        pk=pk, school=request.user.school,
    )
    cfg = RegistrationSettings.for_school(app.school)
    year = _year_for(cfg)
    matches = list(_matches(app))
    form = ReviewForm(request.POST or None, school=app.school, matches=matches, year=year)
    can_decide = app.status == StudentApplication.Status.SUBMITTED
    if request.method == "POST":
        if not can_decide:
            messages.error(request, "Só pré-cadastros enviados podem ser analisados.")
            return redirect("application_review", pk=app.pk)
        if form.is_valid():
            return _decide(request, app, form.cleaned_data, year)
    return render(request, "registry/application_review.html", {
        "app": app, "form": form, "documents": app.documents.all(), "matches": matches,
        "can_decide": can_decide, "year": year,
    })


def _decide(request, app, data, year):
    decision, note = data["decision"], (data.get("note") or "").strip()
    with transaction.atomic():
        app.review_note = note
        app.reviewed_by = request.user
        app.reviewed_at = timezone.now()
        if decision == "aprovar":
            target = data.get("target") or "nova"
            if target == "nova":
                student = Student.objects.create(
                    school=app.school, first_name=app.first_name.strip(), last_name=app.last_name.strip(),
                    birth_date=app.birth_date, code=data.get("code", ""),
                    guardian_contact_name=app.guardian.get_full_name() or app.guardian.username,
                    guardian_contact_phone=app.phone,
                )
            else:
                student = get_object_or_404(Student, pk=target, school=app.school)
                if data.get("code") and not student.code:
                    student.code = data["code"]
            if app.photo and not student.photo:
                with app.photo.open("rb") as fh:
                    content = process_photo(fh, name_hint=f"aluno-{student.pk}")
                student.photo.save(content.name, content, save=False)
            student.save()
            link, created = GuardianLink.objects.get_or_create(
                school=app.school, guardian=app.guardian, student=student,
                defaults={"status": "aprovado", "relation": app.relation, "requested_by": app.guardian,
                          "validated_by": request.user, "validated_at": timezone.now()},
            )
            if not created and link.status != "aprovado":
                link.status, link.validated_by, link.validated_at = "aprovado", request.user, timezone.now()
                link.save(update_fields=["status", "validated_by", "validated_at"])
            profile, _ = GuardianProfile.objects.get_or_create(user=app.guardian)
            changed = []
            for field in ("phone", "address", "relation"):
                if getattr(app, field) and not getattr(profile, field):
                    setattr(profile, field, getattr(app, field))
                    changed.append(field)
            if changed:
                profile.save(update_fields=changed + ["updated_at"])
            cg = data.get("class_group")
            if cg:
                if Enrollment.objects.filter(student=student, school_year=cg.school_year, status="ativo").exists():
                    messages.warning(request, "O estudante já tem matrícula ativa neste ano: nenhuma nova foi criada.")
                else:
                    Enrollment.objects.create(school=app.school, student=student, class_group=cg,
                                              school_year=cg.school_year, status="ativo")
            app.student = student
            app.status = StudentApplication.Status.APPROVED
            title = f"Pré-cadastro aprovado: {app.full_name}"
            body = "A ficha do estudante foi criada e já aparece em “Meus filhos”." + (
                f" Matrícula na turma {cg.name}." if cg else " A matrícula será feita pela secretaria.")
            url = reverse("my_children")
        elif decision == "correcao":
            app.status = StudentApplication.Status.CORRECTION
            title = f"Pré-cadastro precisa de correção: {app.full_name}"
            body = note
            url = reverse("application_view", args=[app.pk])
        else:
            app.status = StudentApplication.Status.REJECTED
            title = f"Pré-cadastro recusado: {app.full_name}"
            body = note
            url = reverse("application_view", args=[app.pk])
        app.save()
        create_audit_log(user=request.user, action="update", request=request, target=app,
                         detail=f"{app.get_status_display()}: pré-cadastro de {app.full_name}"
                                + (f" (ficha #{app.student_id})" if app.student_id else ""))
        notify(app.school, app.guardian, Notification.Kind.REGISTRATION, title, body=body, url=url,
               student=app.student)
    messages.success(request, f"Pré-cadastro {app.get_status_display().lower()}. A família foi avisada.")
    if app.student_id:
        return redirect("student_detail", student_id=app.student_id)
    return redirect("application_review_list")


# --------------------------------------------------------------------------
# Foto enviada pela família (modo "só fotografia" ou "completo")


def child_photo(request, student_id):
    student = get_object_or_404(Student, pk=student_id)
    if not guardian_of(request.user, student):
        raise PermissionDenied
    cfg = RegistrationSettings.for_school(student.school)
    if not cfg.family_can_send_photo:
        raise PermissionDenied
    error = None
    if request.method == "POST":
        upload = request.FILES.get("photo")
        if not upload:
            error = "Escolha uma foto."
        else:
            try:
                with transaction.atomic():
                    save_photo(student, "photo", upload, name_hint=f"aluno-{student.pk}")
                    student.save(update_fields=["photo", "updated_at"])
                    create_audit_log(user=request.user, action="update", request=request, target=student,
                                     detail=f"Família enviou nova fotografia de {student.full_name}")
            except ValidationError as exc:
                error = " ".join(exc.messages)
            else:
                messages.success(request, "Foto atualizada. Os demais dados não mudaram.")
                return redirect("my_children")
    return render(request, "registry/child_photo.html", {"student": student, "error": error})


# --------------------------------------------------------------------------
# Configurações de cadastro


def registration_settings(request):
    if not can_edit_registration_settings(request.user):
        raise PermissionDenied
    cfg = RegistrationSettings.for_school(request.user.school)
    form = RegistrationSettingsForm(request.POST or None, instance=cfg, school=request.user.school)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            obj = form.save(commit=False)
            obj.updated_by = request.user
            obj.save()
            create_audit_log(user=request.user, action="update", request=request, target=obj,
                             detail=f"Configurou o cadastro pela família: {obj.get_family_mode_display()}; "
                                    f"campos: {obj.family_fields or 'nenhum opcional'}")
        messages.success(request, "Configurações de cadastro salvas.")
        return redirect("registration_settings")
    labels = dict(RegistrationSettings.OPTIONAL_FIELDS)
    secretaria_only = [labels[k] for k, _ in RegistrationSettings.OPTIONAL_FIELDS if k not in cfg.fields_list]
    return render(request, "registry/registration_settings.html", {
        "form": form, "cfg": cfg, "secretaria_only": secretaria_only,
        "pending": StudentApplication.objects.filter(school=request.user.school,
                                                     status=StudentApplication.Status.SUBMITTED).count(),
    })
