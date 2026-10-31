"""Telas do apoio à inclusão. Toda view confere o acesso no servidor
(``inclusion.access``) e registra consultas e downloads na auditoria."""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.models import Role, User
from apps.registry.models import Student

from . import access, services
from .forms import (AnalysisForm, CategoryForm, DeclarationForm, DocumentForm, DocumentReviewForm, NeedForm,
                    PlanForm, PlanReviewForm, RequestForm, ResponseForm, SettingsForm)
from .models import (SupportCase, SupportCategory, SupportDocument, SupportNeed, SupportPlan, SupportPlanVersion,
                     SupportRequest, SupportSettings)

S = SupportCase.Status


def _require(ok):
    if not ok:
        raise PermissionDenied


def _student(request, student_id):
    return get_object_or_404(Student, pk=student_id, school=request.user.school)


def _children(user):
    from apps.registry.models import GuardianLink

    return Student.objects.filter(pk__in=GuardianLink.objects.filter(guardian=user, status="aprovado")
                                  .values("student_id")).order_by("first_name")


# ---------------------------------------------------------------- entrada

def overview(request):
    """Ponto de entrada por perfil."""
    user = request.user
    if user.role == Role.PROFESSOR.value:
        return redirect("inclusion:guidance")
    if user.role == Role.RESPONSAVEL.value:
        kids = list(_children(user))
        cases = {c.student_id: c for c in SupportCase.objects.filter(student__in=kids)}
        return render(request, "inclusion/family_overview.html", {
            "rows": [(k, cases.get(k.pk)) for k in kids],
            "settings": SupportSettings.for_school(user.school),
        })
    _require(access.is_team(user) or access.is_secretaria(user))
    # Fichas abertas só por consulta (sem nada registrado) não entram.
    qs = SupportCase.objects.filter(school=user.school).select_related("student").filter(
        ~Q(status=S.NOT_INFORMED) | Q(needs__isnull=False) | Q(plans__isnull=False) | Q(documents__isnull=False))
    if user.role == Role.COORDENACAO.value:
        from apps.coordination.scope import student_ids

        ids = student_ids(user)
        if ids is not None:
            qs = qs.filter(student_id__in=ids)
    status = request.GET.get("situacao", "")
    if status in dict(S.choices):
        qs = qs.filter(status=status)
    else:
        status = ""
    qs = qs.annotate(open_requests=Count("requests", filter=Q(requests__status=SupportRequest.Status.OPEN),
                                         distinct=True),
                     docs=Count("documents", filter=~Q(documents__status=SupportDocument.Status.DISCARDED),
                                distinct=True)).distinct().order_by("student__first_name")
    services_rows = list(qs)
    plans = {}
    for p in SupportPlan.objects.filter(case__in=services_rows).order_by("case_id", "-starts_on"):
        plans.setdefault(p.case_id, p)
    is_team = access.is_team(user)
    return render(request, "inclusion/overview.html", {
        "rows": [(c, plans.get(c.pk)) for c in services_rows], "is_team": is_team,
        "status": status, "status_choices": S.choices, "filtered": bool(status),
    })


def student_entry(request, student_id):
    """Link da ficha do estudante: cada perfil vai para o que pode ver."""
    user = request.user
    student = _student(request, student_id)
    if access.can_view_case(user, student):
        return redirect("inclusion:case_detail", student_id=student.pk)
    if access.can_view_guidance(user, student):
        return redirect(f"{_url('inclusion:guidance')}?estudante={student.pk}")
    if access.can_view_admin_status(user, student):
        return redirect(f"{_url('inclusion:overview')}")
    raise PermissionDenied


def _url(name, *args):
    from django.urls import reverse

    return reverse(name, args=args)


# ---------------------------------------------------------------- ficha

def case_detail(request, student_id):
    user = request.user
    student = _student(request, student_id)
    _require(access.can_view_case(user, student))
    case = services.case_for(student)
    team = access.can_manage_case(user, student)
    services.audit(request, "view", case, f"Consultou a ficha de apoio de {student}")
    docs = case.documents.select_related("uploaded_by", "reviewed_by")
    plans = case.plans.prefetch_related("responsibles", "reviews")
    if not team:
        plans = plans.filter(status__in=[SupportPlan.Status.ACTIVE, SupportPlan.Status.REVIEW,
                                         SupportPlan.Status.CLOSED])
    plans = list(plans)
    for p in plans:
        p.filled = [(label, getattr(p, name)) for name, label in SupportPlan.PLAN_FIELDS if getattr(p, name)]
    events = case.events.select_related("actor")
    if not team:
        events = events.filter(visible_to_family=True)
    return render(request, "inclusion/case_detail.html", {
        "student": student, "case": case, "team": team, "docs": docs,
        "requests": case.requests.select_related("requested_by", "responded_by"),
        "needs": case.needs.all() if team else case.needs.filter(active=True),
        "plans": plans, "events": events[:50], "settings": SupportSettings.for_school(student.school),
        "plan_fields": SupportPlan.PLAN_FIELDS, "can_declare": access.can_declare(user, student),
    })


def declare(request, student_id):
    """Responsável informa se há laudo e necessidades, e pode anexar documento."""
    user = request.user
    student = _student(request, student_id)
    _require(access.can_declare(user, student))
    case = services.case_for(student)
    form = DeclarationForm(request.POST or None, request.FILES or None, instance=case, school=student.school)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            case = form.save(commit=False)
            case.declared_by, case.declared_at = user, timezone.now()
            case.save()
            form.save_m2m()
            status = S.DECLARED
            note = "Situação de laudo: " + case.get_has_report_display()
            services.record(case, user, "Família informou ou atualizou as necessidades", status, note)
            f = form.cleaned_data.get("file")
            if f:
                doc = services.store_document(case, f, source=SupportDocument.Source.FAMILY, user=user,
                                              kind=form.cleaned_data.get("kind") or "laudo",
                                              issued_on=form.cleaned_data.get("issued_on"),
                                              issuer=form.cleaned_data.get("issuer", ""))
                services.record(case, user, f"Família anexou documento: {doc.original_name}", S.AWAITING)
                services.audit(request, "create", doc, f"Responsável anexou documento de apoio de {student}")
            services.audit(request, "update", case, f"Responsável atualizou informações de apoio de {student}")
            services.notify(case, services.team_for(student), f"Informações de apoio enviadas pela família — "
                            f"{student.first_name}", "Há informações novas na ficha de apoio para analisar.",
                            services.case_url(case))
        messages.success(request, "Informações enviadas à escola. A equipe pedagógica vai analisar.")
        return redirect("inclusion:case_detail", student_id=student.pk)
    return render(request, "inclusion/declare.html", {
        "form": form, "student": student, "settings": SupportSettings.for_school(student.school)})


def document_upload(request, student_id):
    """Família anexa (ou substitui) documento; equipe e secretaria registram
    documento recebido em papel."""
    user = request.user
    student = _student(request, student_id)
    family = access.can_declare(user, student)
    _require(family or access.can_register_received(user, student))
    case = services.case_for(student)
    replaces = None
    if request.GET.get("substitui"):
        replaces = get_object_or_404(SupportDocument, public_id=request.GET["substitui"], case=case)
    form = DocumentForm(request.POST or None, request.FILES or None, school=student.school)
    if request.method == "POST" and form.is_valid():
        source = SupportDocument.Source.FAMILY if family else SupportDocument.Source.SCHOOL
        with transaction.atomic():
            doc = services.store_document(case, form.cleaned_data["file"], source=source, user=user,
                                          kind=form.cleaned_data["kind"], issued_on=form.cleaned_data["issued_on"],
                                          issuer=form.cleaned_data["issuer"],
                                          description=form.cleaned_data["description"], replaces=replaces)
            verb = "substituiu documento" if replaces else "anexou documento"
            who = "Família" if family else "Escola"
            services.record(case, user, f"{who} {verb}: {doc.original_name}" if family else
                            f"Escola registrou documento recebido: {doc.original_name}",
                            S.AWAITING if family else S.RECEIVED)
            services.audit(request, "create", doc, f"{who} {verb} de apoio de {student}")
            if family:
                services.notify(case, services.team_for(student), f"Documento de apoio recebido — {student.first_name}",
                                "A família enviou um documento para análise.", services.case_url(case))
        messages.success(request, "Documento guardado com segurança." + (" A equipe vai analisar." if family else ""))
        if access.can_view_case(user, student):
            return redirect("inclusion:case_detail", student_id=student.pk)
        return redirect("inclusion:overview")
    return render(request, "inclusion/document_form.html", {
        "form": form, "student": student, "replaces": replaces, "family": family,
        "settings": SupportSettings.for_school(student.school)})


def document_download(request, public_id):
    doc = get_object_or_404(SupportDocument.objects.select_related("case__student"), public_id=public_id,
                            case__school=request.user.school)
    _require(access.can_download(request.user, doc))
    if not doc.available:
        raise Http404("Documento indisponível.")
    services.audit(request, "download", doc, f"Baixou documento de apoio de {doc.case.student}: {doc.original_name}")
    resp = FileResponse(doc.file.open("rb"), content_type=doc.content_type, as_attachment=True,
                        filename=doc.original_name)
    resp["Cache-Control"] = "no-store, private"
    return resp


@require_POST
def document_review(request, public_id):
    doc = get_object_or_404(SupportDocument.objects.select_related("case__student"), public_id=public_id,
                            case__school=request.user.school)
    case, student = doc.case, doc.case.student
    _require(access.can_manage_case(request.user, student))
    form = DocumentReviewForm(request.POST)
    if not form.is_valid() or doc.status in (SupportDocument.Status.DISCARDED, SupportDocument.Status.REPLACED):
        messages.error(request, "Não foi possível registrar a análise deste documento.")
        return redirect("inclusion:case_detail", student_id=student.pk)
    with transaction.atomic():
        doc.status = form.cleaned_data["decision"]
        doc.reviewed_by, doc.reviewed_at = request.user, timezone.now()
        doc.review_note = form.cleaned_data["note"]
        doc.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note"])
        analyzed = doc.status == SupportDocument.Status.ANALYZED
        services.record(case, request.user, f"Documento {'analisado' if analyzed else 'arquivado'}: "
                                            f"{doc.original_name}", S.ANALYZED if analyzed else None)
        services.audit(request, "update", doc, f"Analisou documento de apoio de {student}")
        if analyzed:
            services.notify(case, services.guardians_for(student), f"Documentação de apoio analisada — "
                            f"{student.first_name}", "A escola registrou a análise do documento enviado.",
                            services.case_url(case))
    messages.success(request, "Análise registrada.")
    return redirect("inclusion:case_detail", student_id=student.pk)


# ---------------------------------------------------------------- complementação

def request_create(request, student_id):
    user = request.user
    student = _student(request, student_id)
    _require(access.can_manage_case(user, student))
    case = services.case_for(student)
    form = RequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            req = form.save(commit=False)
            req.case, req.requested_by = case, user
            req.save()
            services.record(case, user, "Escola pediu complementação ou esclarecimento", S.NEEDS_MORE, req.message)
            services.audit(request, "create", req, f"Pediu complementação da documentação de apoio de {student}")
            services.notify(case, services.guardians_for(student), f"A escola pediu complementação — "
                            f"{student.first_name}", "Veja o pedido na ficha de apoio e responda pela plataforma.",
                            services.case_url(case))
        messages.success(request, "Pedido enviado à família.")
        return redirect("inclusion:case_detail", student_id=student.pk)
    return render(request, "inclusion/form.html", {
        "form": form, "student": student, "heading": "Pedir complementação à família",
        "subheading": f"{student}: a família recebe um aviso e responde pela plataforma.", "submit": "Enviar pedido"})


def request_respond(request, pk):
    req = get_object_or_404(SupportRequest.objects.select_related("case__student"), pk=pk,
                            case__school=request.user.school)
    student, case = req.case.student, req.case
    _require(access.can_declare(request.user, student))
    if req.status != SupportRequest.Status.OPEN:
        messages.info(request, "Este pedido já foi respondido.")
        return redirect("inclusion:case_detail", student_id=student.pk)
    form = ResponseForm(request.POST or None, request.FILES or None, school=student.school)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            claimed = SupportRequest.objects.filter(pk=req.pk, status=SupportRequest.Status.OPEN).update(
                status=SupportRequest.Status.ANSWERED, response=form.cleaned_data["response"],
                responded_by=request.user, responded_at=timezone.now())
            if claimed:
                f = form.cleaned_data.get("file")
                if f:
                    doc = services.store_document(case, f, source=SupportDocument.Source.FAMILY, user=request.user,
                                                  kind=form.cleaned_data.get("kind") or "laudo",
                                                  issued_on=form.cleaned_data.get("issued_on"),
                                                  issuer=form.cleaned_data.get("issuer", ""))
                    services.audit(request, "create", doc, f"Responsável anexou documento de apoio de {student}")
                services.record(case, request.user, "Família respondeu ao pedido de complementação", S.AWAITING,
                                form.cleaned_data["response"])
                services.notify(case, services.team_for(student), f"Família respondeu à complementação — "
                                f"{student.first_name}", "Há resposta da família na ficha de apoio.",
                                services.case_url(case))
        messages.success(request, "Resposta enviada à escola.")
        return redirect("inclusion:case_detail", student_id=student.pk)
    return render(request, "inclusion/form.html", {
        "form": form, "student": student, "heading": "Responder à escola", "request_obj": req,
        "subheading": f"Pedido de {req.created_at:%d/%m/%Y}: {req.message}", "submit": "Enviar resposta",
        "multipart": True})


@require_POST
def request_close(request, pk):
    req = get_object_or_404(SupportRequest.objects.select_related("case__student"), pk=pk,
                            case__school=request.user.school)
    _require(access.can_manage_case(request.user, req.case.student))
    if req.status != SupportRequest.Status.CLOSED:
        req.status = SupportRequest.Status.CLOSED
        req.save(update_fields=["status"])
        services.record(req.case, request.user, "Escola encerrou o pedido de complementação")
    return redirect("inclusion:case_detail", student_id=req.case.student_id)


# ---------------------------------------------------------------- análise e necessidades

def case_analysis(request, student_id):
    user = request.user
    student = _student(request, student_id)
    _require(access.can_manage_case(user, student))
    case = services.case_for(student)
    form = AnalysisForm(request.POST or None, instance=case, school=student.school,
                        initial={"status": case.status if case.status in (S.ANALYZED, S.UPDATED, S.ARCHIVED)
                                 else S.ANALYZED})
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            before = set(case.validated_categories.values_list("name", flat=True))
            case = form.save(commit=False)
            case.save()
            form.save_m2m()
            after = set(case.validated_categories.values_list("name", flat=True))
            if before != after:
                case.validated_by, case.validated_at = user, timezone.now()
                case.save(update_fields=["validated_by", "validated_at"])
            note = form.cleaned_data["note"]
            services.record(case, user, "Equipe registrou a análise da ficha", form.cleaned_data["status"], note)
            if before != after:
                services.record(case, user, "Condições validadas conforme procedimento institucional", None,
                                ", ".join(sorted(after)) or "nenhuma")
            services.audit(request, "update", case, f"Registrou análise da ficha de apoio de {student}")
        messages.success(request, "Análise registrada.")
        return redirect("inclusion:case_detail", student_id=student.pk)
    return render(request, "inclusion/form.html", {
        "form": form, "student": student, "heading": "Análise e validação",
        "subheading": "Validar é registrar o que a escola confirmou pelo próprio procedimento. Enviar documento não "
                      "valida nada sozinho, e a escola não faz diagnóstico.", "submit": "Registrar análise"})


def need_edit(request, student_id, pk=None):
    user = request.user
    student = _student(request, student_id)
    _require(access.can_manage_case(user, student))
    case = services.case_for(student)
    need = get_object_or_404(SupportNeed, pk=pk, case=case) if pk else None
    form = NeedForm(request.POST or None, instance=need)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            obj = form.save(commit=False)
            obj.case = case
            if not obj.pk:
                obj.created_by = user
            changed = ", ".join(str(form.fields[f].label).lower() for f in form.changed_data) or "sem mudanças"
            obj.save()
            services.record(case, user, f"Equipe {'atualizou' if need else 'registrou'} necessidade de apoio: "
                                        f"{obj.get_area_display()}", S.UPDATED if case.status != S.NOT_INFORMED
                            else S.UPDATED, f"Campos: {changed}")
            services.audit(request, "update" if need else "create", obj, f"Necessidade de apoio de {student}")
        messages.success(request, "Necessidade registrada. Ela vale com ou sem laudo.")
        return redirect("inclusion:case_detail", student_id=student.pk)
    return render(request, "inclusion/form.html", {
        "form": form, "student": student,
        "heading": "Editar necessidade de apoio" if need else "Registrar necessidade de apoio",
        "subheading": "Necessidade observada pela equipe no contexto escolar. Não depende de laudo nem de "
                      "categoria, e não é diagnóstico.", "submit": "Salvar"})


# ---------------------------------------------------------------- plano

def plan_edit(request, student_id, pk=None):
    user = request.user
    student = _student(request, student_id)
    _require(access.can_manage_case(user, student))
    case = services.case_for(student)
    plan = get_object_or_404(SupportPlan, pk=pk, case=case) if pk else None
    responsible_qs = User.objects.filter(school=student.school, is_active=True, role__in=[
        Role.COORDENACAO.value, Role.DIRECAO.value, Role.PROFESSOR.value]).order_by("first_name")
    before = plan.snapshot() if plan else None
    old_status = plan.status if plan else None
    form = PlanForm(request.POST or None, instance=plan, responsible_qs=responsible_qs)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            obj = form.save(commit=False)
            obj.case = case
            if plan:
                if form.changed_data:
                    SupportPlanVersion.objects.create(plan=plan, version=plan.version, data=before, saved_by=user)
                    obj.version = plan.version + 1
            else:
                obj.created_by = user
            obj.save()
            form.save_m2m()
            services.record(case, user, f"Plano individualizado {'atualizado' if plan else 'criado'} "
                                        f"({obj.get_status_display()})", S.UPDATED,
                            "Campos alterados: " + ", ".join(str(form.fields[f].label).lower() for f in form.changed_data)
                            if plan else "", family=False)
            services.audit(request, "update" if plan else "create", obj, f"Plano individualizado de {student}")
            if obj.status == SupportPlan.Status.ACTIVE and old_status != SupportPlan.Status.ACTIVE:
                services.record(case, user, "Plano individualizado vigente", None)
                services.notify(case, services.guardians_for(student), f"Plano individualizado disponível — "
                                f"{student.first_name}", "O plano de acompanhamento está na ficha de apoio.",
                                services.case_url(case))
        messages.success(request, "Plano salvo. As versões anteriores ficam guardadas.")
        return redirect("inclusion:case_detail", student_id=student.pk)
    return render(request, "inclusion/plan_form.html", {"form": form, "student": student, "plan": plan})


@require_POST
def plan_review(request, student_id, pk):
    user = request.user
    student = _student(request, student_id)
    _require(access.can_manage_case(user, student))
    plan = get_object_or_404(SupportPlan, pk=pk, case__student=student)
    form = PlanReviewForm(request.POST)
    if form.is_valid():
        with transaction.atomic():
            r = form.save(commit=False)
            r.plan, r.author = plan, user
            r.save()
            family = r.visible_to_family
            services.record(plan.case, user, f"Plano: {r.get_kind_display().lower()}", None,
                            r.notes if family else "", family=family)
            services.audit(request, "create", r, f"Registro no plano individualizado de {student}")
            if family:
                services.notify(plan.case, services.guardians_for(student), f"Devolutiva da escola — "
                                f"{student.first_name}", "Há uma devolutiva sobre o plano de acompanhamento.",
                                services.case_url(plan.case))
        messages.success(request, "Registro incluído no plano.")
    else:
        messages.error(request, "Preencha o tipo, a data e o registro.")
    return redirect("inclusion:case_detail", student_id=student.pk)


# ---------------------------------------------------------------- professores

def guidance(request):
    """Orientações pedagógicas para os professores do estudante."""
    from apps.academics.models import ClassGroup
    from apps.academics.permissions import teacher_class_ids
    from apps.registry.models import Enrollment

    user = request.user
    _require(user.role == Role.PROFESSOR.value or access.is_team(user))
    if user.role == Role.PROFESSOR.value:
        class_ids = teacher_class_ids(user)
    else:
        from apps.coordination.scope import class_scope

        scope = class_scope(user)
        class_ids = set(ClassGroup.objects.filter(school=user.school).values_list("pk", flat=True)) \
            if scope is None else set(scope)
    classes = ClassGroup.objects.filter(pk__in=class_ids).order_by("name")
    turma = request.GET.get("turma", "")
    selected = [c for c in classes if str(c.pk) == turma]
    enr = Enrollment.objects.filter(class_group__in=selected or classes, status="ativo").select_related(
        "student", "class_group")
    student_filter = request.GET.get("estudante", "")
    if student_filter.isdigit():
        enr = enr.filter(student_id=int(student_filter))
    students = {}
    for e in enr:
        students.setdefault(e.student_id, (e.student, []))[1].append(e.class_group.name)
    data = services.guidance([s for s, _ in students.values()])
    rows = [(s, groups, data[s.pk]) for s, groups in sorted(students.values(), key=lambda t: t[0].first_name)
            if s.pk in data]
    if rows:
        from apps.core.models import create_audit_log

        create_audit_log(user=user, action="view", request=request, target_type="SupportGuidance",
                         target_id=turma or "todas",
                         detail=f"Consultou orientações pedagógicas de apoio ({len(rows)} estudante(s))")
    return render(request, "inclusion/guidance.html", {
        "rows": rows, "classes": [(c.pk, c.name) for c in classes], "turma": turma,
        "is_teacher": user.role == Role.PROFESSOR.value})


# ---------------------------------------------------------------- configuração, retenção e painel

def settings_view(request):
    user = request.user
    _require(access.can_configure(user))
    SupportCategory.ensure_defaults(user.school)
    settings_obj = SupportSettings.for_school(user.school)
    form = SettingsForm(request.POST or None, instance=settings_obj, prefix="cfg")
    cat_form = CategoryForm(request.POST or None, prefix="cat")
    if request.method == "POST":
        action = request.POST.get("acao")
        if action == "config" and form.is_valid():
            obj = form.save(commit=False)
            obj.school, obj.updated_by = user.school, user
            obj.save()
            services.audit(request, "update", obj, "Atualizou a configuração do apoio à inclusão")
            messages.success(request, "Configuração salva.")
            return redirect("inclusion:settings")
        if action == "nova" and cat_form.is_valid():
            name = cat_form.cleaned_data["name"].strip()
            cat, created = SupportCategory.objects.get_or_create(school=user.school, name=name,
                                                                 defaults={"order": 99})
            if not created and not cat.active:
                cat.active = True
                cat.save(update_fields=["active"])
            services.audit(request, "create", cat, f"Categoria de necessidade: {name}")
            messages.success(request, "Categoria incluída.")
            return redirect("inclusion:settings")
        if action == "alternar":
            cat = get_object_or_404(SupportCategory, pk=request.POST.get("categoria"), school=user.school)
            cat.active = not cat.active
            cat.save(update_fields=["active"])
            services.audit(request, "update", cat, f"Categoria {'reativada' if cat.active else 'desativada'}: "
                                                   f"{cat.name}")
            return redirect("inclusion:settings")
    return render(request, "inclusion/settings.html", {
        "form": form, "cat_form": cat_form,
        "categories": SupportCategory.objects.filter(school=user.school)})


def retention(request):
    user = request.user
    _require(access.can_discard(user))
    candidates = services.discard_candidates(user.school)
    if request.method == "POST":
        ids = set(request.POST.getlist("ids"))
        done = 0
        with transaction.atomic():
            for doc in candidates:
                if str(doc.public_id) in ids:
                    services.discard(doc, user)
                    services.record(doc.case, user, f"Documento descartado ao fim do prazo de guarda: "
                                                    f"{doc.original_name}", None, family=False)
                    services.audit(request, "delete", doc, f"Descartou arquivo de apoio de {doc.case.student} "
                                                           f"(prazo de guarda); registro mantido")
                    done += 1
        messages.success(request, f"{done} arquivo(s) descartado(s). O registro de que existiram foi mantido.")
        return redirect("inclusion:retention")
    return render(request, "inclusion/retention.html", {
        "candidates": candidates, "settings": SupportSettings.for_school(user.school)})


def panel(request):
    """Indicadores agregados, sem diagnóstico individual e sem ranking."""
    user = request.user
    _require(access.is_team(user))
    cases = SupportCase.objects.filter(school=user.school)
    if user.role == Role.COORDENACAO.value:
        from apps.coordination.scope import student_ids

        ids = student_ids(user)
        if ids is not None:
            cases = cases.filter(student_id__in=ids)
    today = timezone.localdate()
    plans = SupportPlan.objects.filter(case__in=cases)
    needs = SupportNeed.objects.filter(case__in=cases, active=True)
    by_area = []
    for code, label in SupportNeed.Area.choices:
        n = needs.filter(area=code).values("case").distinct().count()
        by_area.append((label, n))
    k = {
        "students": cases.filter(Q(needs__active=True) | Q(plans__status__in=["vigente", "revisao"])).distinct()
        .count(),
        "active_plans": plans.filter(status__in=["vigente", "revisao"]).count(),
        "overdue": plans.filter(status__in=["vigente", "revisao"], review_due__lt=today).count(),
        "awaiting_docs": SupportDocument.objects.filter(case__in=cases, status="aguardando").count(),
        "open_requests": SupportRequest.objects.filter(case__in=cases, status="aberta").count(),
        "answered": SupportRequest.objects.filter(case__in=cases, status="respondida").count(),
        "without_report": cases.filter(needs__active=True).exclude(has_report="sim").distinct().count(),
    }
    return render(request, "inclusion/panel.html", {"k": k, "by_area": by_area, "min_group": 5})
