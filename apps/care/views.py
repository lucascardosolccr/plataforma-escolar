"""Saúde e emergência; pessoas autorizadas a buscar, aviso de saída antecipada e registro da retirada."""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.academics.models import ClassGroup
from apps.core.models import Role, create_audit_log
from apps.core.params import as_id
from apps.registry.models import Enrollment, GuardianLink, Student

from . import access
from .forms import HealthForm, NoticeForm, PickupForm, contact_forms
from .models import AuthorizedPickup, DepartureNotice, EmergencyContact, HealthRecord, PickupRecord


def _student(user, student_id):
    return get_object_or_404(Student, pk=student_id, school=user.school)


def _children(user):
    return [ln.student for ln in GuardianLink.objects.filter(guardian=user, status="aprovado")
            .select_related("student").order_by("student__first_name")]


def _classes(user):
    """Turmas que a pessoa acompanha nesta tela (professor: as suas; coordenação: as da designação)."""
    qs = ClassGroup.objects.filter(school=user.school)
    current = qs.filter(school_year__is_current=True)
    qs = current if current.exists() else qs
    if user.role == Role.PROFESSOR.value:
        from apps.academics.permissions import teacher_class_ids

        qs = qs.filter(pk__in=teacher_class_ids(user))
    elif user.role == Role.COORDENACAO.value:
        from apps.coordination.scope import class_scope

        scope = class_scope(user)
        if scope is not None:
            qs = qs.filter(pk__in=scope)
    elif user.role not in access.OFFICE:
        return qs.none()
    return qs.order_by("name")


def home(request):
    user = request.user
    today = timezone.localdate()
    if user.role == Role.RESPONSAVEL.value:
        kids = _children(user)
        records = {r.student_id: r for r in HealthRecord.objects.filter(student__in=kids)}
        pickups = {}
        for p in AuthorizedPickup.objects.filter(student__in=kids, revoked_at__isnull=True):
            if p.valid_on(today):
                pickups[p.student_id] = pickups.get(p.student_id, 0) + 1
        notices = DepartureNotice.objects.filter(student__in=kids, day__gte=today,
                                                 status=DepartureNotice.Status.PENDING).select_related("student")
        from .views_incidents import pending_acks

        return render(request, "care/home_family.html", {
            "rows": [{"student": s, "record": records.get(s.pk), "pickups": pickups.get(s.pk, 0)} for s in kids],
            "notices": notices, "incidents": pending_acks(user)})
    if user.role not in access.TEAM and user.role != Role.PROFESSOR.value:
        raise PermissionDenied
    ctx = {"classes": _classes(user), "is_team": user.role in access.TEAM}
    if ctx["is_team"]:
        ctx["notices"] = (DepartureNotice.objects.filter(school=user.school, day=today,
                                                         status=DepartureNotice.Status.PENDING)
                          .select_related("student", "pickup", "created_by"))
        ctx["pickups"] = (PickupRecord.objects.filter(school=user.school, at__date=today)
                          .select_related("student"))
        ctx["q"] = (request.GET.get("q") or "").strip()[:60]
        if ctx["q"]:
            ctx["found"] = Student.objects.filter(school=user.school, status="ativo").filter(
                Q(first_name__icontains=ctx["q"]) | Q(last_name__icontains=ctx["q"])).order_by("first_name")[:15]
    return render(request, "care/home_team.html", ctx)


# ---------- Ficha de saúde ----------

def health_view(request, student_id):
    user = request.user
    student = _student(user, student_id)
    level = access.health_level(user, student)
    if level is None:
        raise PermissionDenied
    record = HealthRecord.objects.filter(student=student).first()
    if user.role != Role.RESPONSAVEL.value:
        create_audit_log(user=user, action="view", request=request, target=student,
                         detail=f"Consultou a ficha de saúde de {student}" + (" (alertas de sala)" if level == "alerts"
                                                                              else ""))
    return render(request, "care/health_view.html", {
        "student": student, "record": record, "full": level == "full",
        "contacts": student.emergency_contacts.all() if level == "full" else [],
        "can_edit": access.can_edit_health(user, student),
        "can_register": user.role != Role.RESPONSAVEL.value and access.can_register_incident(user, student)})


def health_edit(request, student_id):
    user = request.user
    student = _student(user, student_id)
    if not access.can_edit_health(user, student):
        raise PermissionDenied
    record = HealthRecord.objects.filter(student=student).first() or HealthRecord(school=student.school,
                                                                                  student=student)
    family = user.role == Role.RESPONSAVEL.value
    current = [{"name": c.name, "relationship": c.relationship, "phone": c.phone}
               for c in student.emergency_contacts.all()]
    if request.method == "POST":
        form = HealthForm(request.POST, instance=record, family=family)
        contacts = contact_forms(request.POST)
        if form.is_valid() and all(c.is_valid() for c in contacts):
            with transaction.atomic():
                rec = form.save(commit=False)
                rec.updated_by = user
                rec.consent_at, rec.consent_by = timezone.now(), user
                rec.save()
                student.emergency_contacts.all().delete()
                rows = [c.cleaned_data for c in contacts if (c.cleaned_data.get("name") or "").strip()]
                EmergencyContact.objects.bulk_create(
                    EmergencyContact(student=student, name=r["name"].strip(), relationship=r["relationship"].strip(),
                                     phone=r["phone"].strip(), order=i) for i, r in enumerate(rows, start=1))
                create_audit_log(user=user, action="update", request=request, target=student,
                                 detail=f"Atualizou a ficha de saúde de {student}")
            messages.success(request, "Ficha de saúde salva.")
            return redirect("care:health", student_id=student.pk)
    else:
        form = HealthForm(instance=record, family=family)
        contacts = contact_forms(initial=current)
    return render(request, "care/health_edit.html", {"student": student, "form": form, "contacts": contacts,
                                                     "family": family})


def class_alerts(request, class_id):
    user = request.user
    cg = get_object_or_404(ClassGroup, pk=class_id, school=user.school)
    if not access.can_view_class_alerts(user, cg):
        raise PermissionDenied
    ids = Enrollment.objects.filter(class_group=cg, status="ativo").values_list("student_id", flat=True)
    records = [r for r in HealthRecord.objects.filter(student_id__in=ids).select_related("student")
               .order_by("student__first_name", "student__last_name") if r.has_alert]
    create_audit_log(user=user, action="view", request=request, target=cg,
                     detail=f"Consultou os alertas de saúde da turma {cg}")
    return render(request, "care/class_alerts.html", {"cg": cg, "records": records, "total": len(ids)})


def food_list(request):
    """Restrições alimentares e alergias por turma, para quem cuida do cardápio e da cozinha."""
    user = request.user
    if not access.can_view_food_list(user):
        raise PermissionDenied
    classes = list(_classes(user))
    enr = {e.student_id: e.class_group for e in Enrollment.objects.filter(class_group__in=classes, status="ativo")
           .select_related("class_group")}
    groups = {}
    for r in HealthRecord.objects.filter(student_id__in=enr).select_related("student"):
        if r.has_food_alert:
            groups.setdefault(enr[r.student_id], []).append(r)
    rows = [{"cg": cg, "records": sorted(groups[cg], key=lambda r: r.student.full_name)}
            for cg in classes if cg in groups]
    create_audit_log(user=user, action="view", request=request, target_type="saude", target_id="alimentacao",
                     detail="Consultou a lista de restrições alimentares e alergias")
    return render(request, "care/food_list.html", {"rows": rows, "total": sum(len(r["records"]) for r in rows)})


# ---------- Retirada ----------

def _guardians(student):
    return [ln.guardian for ln in GuardianLink.objects.filter(student=student, status="aprovado",
                                                              guardian__is_active=True).select_related("guardian")]


def pickup_student(request, student_id):
    user = request.user
    student = _student(user, student_id)
    if not access.can_see_pickups(user, student):
        raise PermissionDenied
    today = timezone.localdate()
    people = list(AuthorizedPickup.objects.filter(student=student, revoked_at__isnull=True))
    can_manage = access.can_manage_pickups(user, student)
    form = PickupForm()
    if request.method == "POST":
        if not can_manage:
            raise PermissionDenied
        form = PickupForm(request.POST)
        if form.is_valid():
            p = form.save(commit=False)
            p.school, p.student, p.created_by = student.school, student, user
            p.save()
            create_audit_log(user=user, action="create", request=request, target=student,
                             detail=f"Autorizou {p.name} ({p.relationship}) a buscar {student}")
            messages.success(request, f"{p.name} pode buscar {student.first_name}.")
            return redirect("care:pickups", student_id=student.pk)
    return render(request, "care/pickups.html", {
        "student": student, "people": [{"p": p, "valid": p.valid_on(today)} for p in people],
        "alone": _alone_signature(student),
        "guardians": _guardians(student), "form": form, "can_manage": can_manage,
        "can_register": access.can_register_pickup(user, student),
        "is_family": user.role == Role.RESPONSAVEL.value,
        "notices": DepartureNotice.objects.filter(student=student, day__gte=today)
        .exclude(status=DepartureNotice.Status.CANCELED).select_related("pickup", "created_by"),
        "records": PickupRecord.objects.filter(student=student).select_related("recorded_by")[:20]})


@require_POST
def pickup_revoke(request, pk):
    user = request.user
    p = get_object_or_404(AuthorizedPickup, pk=pk, school=user.school, revoked_at__isnull=True)
    if not access.can_manage_pickups(user, p.student):
        raise PermissionDenied
    p.revoked_at, p.revoked_by = timezone.now(), user
    p.save(update_fields=["revoked_at", "revoked_by"])
    create_audit_log(user=user, action="update", request=request, target=p.student,
                     detail=f"Retirou {p.name} da lista de quem pode buscar {p.student}")
    messages.success(request, f"{p.name} saiu da lista.")
    return redirect("care:pickups", student_id=p.student_id)


def notice_create(request, student_id):
    user = request.user
    student = _student(user, student_id)
    if not access.can_manage_pickups(user, student):
        raise PermissionDenied
    form = NoticeForm(request.POST or None, student=student,
                      initial={"day": timezone.localdate(), "guardian_pickup": user.role == Role.RESPONSAVEL.value})
    if user.role != Role.RESPONSAVEL.value:
        form.fields["guardian_pickup"].label = "Um responsável com vínculo vai buscar"
    if request.method == "POST" and form.is_valid():
        n = form.save(commit=False)
        n.school, n.student, n.created_by = student.school, student, user
        n.save()
        create_audit_log(user=user, action="create", request=request, target=student,
                         detail=f"Avisou saída antecipada de {student} em {n.day:%d/%m} às {n.time:%H:%M}")
        messages.success(request, f"Saída avisada para {n.day:%d/%m} às {n.time:%H:%M}. A portaria vê o aviso no dia.")
        return redirect("care:pickups", student_id=student.pk)
    return render(request, "care/notice_form.html", {"student": student, "form": form})


@require_POST
def notice_cancel(request, pk):
    user = request.user
    n = get_object_or_404(DepartureNotice, pk=pk, school=user.school, status=DepartureNotice.Status.PENDING)
    if not access.can_manage_pickups(user, n.student):
        raise PermissionDenied
    n.status = DepartureNotice.Status.CANCELED
    n.save(update_fields=["status"])
    create_audit_log(user=user, action="update", request=request, target=n.student,
                     detail=f"Cancelou o aviso de saída antecipada de {n.student} em {n.day:%d/%m}")
    messages.success(request, "Aviso cancelado.")
    return redirect("care:pickups", student_id=n.student_id)


def pickup_register(request, student_id):
    """Portaria ou secretaria: quem está levando o estudante agora."""
    user = request.user
    student = _student(user, student_id)
    if not access.can_register_pickup(user, student):
        raise PermissionDenied
    today = timezone.localdate()
    guardians = _guardians(student)
    people = [p for p in AuthorizedPickup.objects.filter(student=student, revoked_at__isnull=True)
              if p.valid_on(today)]
    notice = DepartureNotice.objects.filter(student=student, day=today,
                                            status=DepartureNotice.Status.PENDING).first()
    alone = _alone_signature(student)
    error = None
    if request.method == "POST":
        who = request.POST.get("quem", "")
        kind, ref = (who.split(":", 1) + [""])[:2]
        guardian = pickup = None
        name = verification = ""
        if kind == "g":
            guardian = next((g for g in guardians if g.pk == as_id(ref)), None)
            name = (guardian.get_full_name() or guardian.username) if guardian else ""
        elif kind == "a":
            pickup = next((p for p in people if p.pk == as_id(ref)), None)
            name = pickup.name if pickup else ""
        elif kind == "o":
            name = (request.POST.get("nome") or "").strip()[:120]
            verification = (request.POST.get("confirmacao") or "").strip()[:300]
        elif kind == "s" and alone:
            # Só com a autorização "sair sozinho(a)" assinada, íntegra e valendo hoje (conferida de novo agora).
            name, verification = "sozinho(a)", f"Autorização assinada {alone.display_code}"
        if not name:
            error = "Escolha quem está buscando o estudante."
        elif kind == "o" and not verification:
            error = ("Pessoa fora da lista: antes de liberar, confirme com um responsável e escreva com quem falou "
                     "e por qual meio.")
        else:
            return _register(request, student, user, guardian, pickup, name, verification, notice,
                             alone=kind == "s")
    chosen = request.POST.get("quem") if request.method == "POST" else (
        f"a:{notice.pickup_id}" if notice and notice.pickup_id else
        f"g:{notice.created_by_id}" if notice and notice.guardian_pickup else "")
    options = ([{"value": f"g:{g.pk}", "label": f"{g.get_full_name() or g.username} · responsável com vínculo"}
                for g in guardians]
               + [{"value": f"a:{p.pk}", "label": f"{p.name} · {p.relationship} · conferir {p.document_hint}"}
                  for p in people]
               + ([{"value": "s:", "label": f"Sai sozinho(a) · autorização da família {alone.display_code}, "
                                           f"vale até {alone.authorization.valid_until:%d/%m/%Y}"}] if alone else [])
               + [{"value": "o:", "label": "Outra pessoa, fora da lista (só depois de confirmar com um responsável)"}])
    for o in options:
        o["checked"] = o["value"] == chosen
    return render(request, "care/register.html", {
        "student": student, "options": options, "notice": notice, "error": error, "alone": alone,
        "post": request.POST if request.method == "POST" else {},
        "health": HealthRecord.objects.filter(student=student).first()})


def _alone_signature(student):
    """A assinatura da família que deixa o estudante sair sozinho hoje, ou None (``communication.consents``)."""
    from apps.communication.consents import allowed
    from apps.communication.models import Authorization

    return allowed(student, Authorization.Kind.ALONE)


def _register(request, student, user, guardian, pickup, name, verification, notice, alone=False):
    from apps.communication.family_events import family_of
    from apps.communication.models import Notification
    from apps.communication.services import notify_many
    from apps.gate import services as gate
    from apps.gate.models import GateEvent

    kind = (PickupRecord.Kind.GUARDIAN if guardian else PickupRecord.Kind.AUTHORIZED if pickup
            else PickupRecord.Kind.ALONE if alone
            else PickupRecord.Kind.OTHER)
    with_whom = "sozinho(a)" if kind == PickupRecord.Kind.ALONE else f"com {name}"
    with transaction.atomic():
        rec = PickupRecord.objects.create(
            school=student.school, student=student, at=timezone.now(), kind=kind, guardian=guardian, pickup=pickup,
            person_name=name, verification=verification, notice=notice, recorded_by=user)
        if notice:
            notice.status = DepartureNotice.Status.DONE
            notice.save(update_fields=["status"])
        create_audit_log(user=user, action="create", request=request, target=student,
                         detail=f"Registrou a saída de {student} {with_whom} ({rec.get_kind_display().lower()}"
                                + (f", {verification})" if kind == PickupRecord.Kind.ALONE else ")"))
    # A saída entra na portaria (painel do dia) e avisa a família com quem o estudante saiu.
    event, existed = gate.register(student, GateEvent.Kind.EXIT, GateEvent.Method.MANUAL, user)
    if existed:
        from apps.communication.family_events import notify_family

        notify_family(student, "saida_escola", f"{student.first_name} saiu da escola {with_whom}",
                      body=f"Registrado às {timezone.localtime(rec.at):%H:%M}.",
                      url=reverse("care:pickups", args=[student.pk]), dedupe_key=f"retirada:{rec.pk}")
    if kind == PickupRecord.Kind.OTHER:
        # Segurança: vai a todos os responsáveis, mesmo a quem silenciou os avisos da portaria.
        notify_many(student.school, family_of(student, include_student=False), Notification.Kind.GATE,
                    f"Atenção: {student.first_name} foi retirado(a) por pessoa fora da lista de autorizados",
                    body=f"{name}, às {timezone.localtime(rec.at):%H:%M}. Confirmação registrada pela escola: "
                         f"{verification}",
                    url=reverse("care:pickups", args=[student.pk]), student=student,
                    dedupe_key=f"retirada-fora:{rec.pk}", priority=Notification.Priority.HIGH)
    messages.success(request, f"Saída registrada: {student.first_name} saiu {with_whom} às "
                              f"{timezone.localtime(rec.at):%H:%M}.")
    return redirect("care:home")
