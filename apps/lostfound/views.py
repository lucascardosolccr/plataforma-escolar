"""Achados e perdidos.

Quem faz o quê:

- **registram objetos:** toda a equipe (professor, coordenação, direção, secretaria, administração);
- **entregam, doam, identificam o dono e respondem os pedidos:** direção, coordenação, secretaria,
  administração e quem registrou o objeto;
- **veem o que está guardado e pedem "é meu":** famílias e estudantes da escola. Celular, fone, documento e
  chave aparecem sem detalhes nem foto, e o nome do dono identificado só aparece para a família dele.

Entregue ou doado, a foto é apagada: não há por que guardar.
"""

import datetime
import mimetypes

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.communication.models import Notification
from apps.communication.services import notify_many
from apps.core.models import Role, User, create_audit_log
from apps.core.pagination import paginate
from apps.core.params import as_id, digits, name_q
from apps.registry.models import Student

from .models import DONATE_AFTER_DAYS, FAMILY_WINDOW_DAYS, Claim, FoundItem

MANAGERS = (Role.DIRECAO.value, Role.COORDENACAO.value, Role.SECRETARIA.value, Role.ADMIN.value)
STAFF = MANAGERS + (Role.PROFESSOR.value,)
FAMILY = (Role.RESPONSAVEL.value, Role.ESTUDANTE.value)


class ItemForm(forms.ModelForm):
    class Meta:
        model = FoundItem
        fields = ["title", "category", "details", "place", "found_on", "photo"]
        widgets = {"found_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def clean_found_on(self):
        day = self.cleaned_data["found_on"]
        if day > timezone.localdate():
            raise forms.ValidationError("A data não pode ser no futuro.")
        return day


def _staff(user):
    return bool(user.school_id) and user.role in STAFF


def _can_manage(user, item):
    return item.school_id == user.school_id and (user.role in MANAGERS or item.registered_by_id == user.pk)


def _own_students(user):
    from apps.library.access import own_students

    return own_students(user)


def _visible_item(user, pk):
    item = get_object_or_404(FoundItem.objects.select_related("student"), pk=pk, school=user.school)
    if _staff(user):
        return item
    window = timezone.localdate() - datetime.timedelta(days=FAMILY_WINDOW_DAYS)
    if user.role not in FAMILY or item.status != FoundItem.Status.KEPT or item.found_on < window:
        raise Http404
    return item


def _close_photo(item):
    if item.photo:
        item.photo.delete(save=False)
        item.photo = None


def item_list(request):
    user = request.user
    if not user.school_id or user.role not in STAFF + FAMILY:
        raise PermissionDenied
    today = timezone.localdate()
    qs = FoundItem.objects.filter(school=user.school)
    staff = _staff(user)
    status = request.GET.get("situacao", FoundItem.Status.KEPT)
    if staff:
        if status in FoundItem.Status.values:
            qs = qs.filter(status=status)
    else:
        status = FoundItem.Status.KEPT
        qs = qs.filter(status=status, found_on__gte=today - datetime.timedelta(days=FAMILY_WINDOW_DAYS))
    category = request.GET.get("tipo", "")
    if category in FoundItem.Category.values:
        qs = qs.filter(category=category)
    ctx = {"page": paginate(request, qs.select_related("student")), "staff": staff, "status": status,
           "statuses": FoundItem.Status.choices, "category": category, "categories": FoundItem.Category.choices,
           "today": today, "window": FAMILY_WINDOW_DAYS}
    if staff:
        ctx["n_claims"] = Claim.objects.filter(item__school=user.school, status=Claim.Status.PENDING,
                                               item__status=FoundItem.Status.KEPT).count()
        ctx["old"] = FoundItem.objects.filter(school=user.school, status=FoundItem.Status.KEPT,
                                              found_on__lt=today - datetime.timedelta(days=DONATE_AFTER_DAYS)).count()
        ctx["donate_after"] = DONATE_AFTER_DAYS
        ctx["can_donate"] = user.role in MANAGERS
    else:
        ctx["my_claims"] = Claim.objects.filter(user=user).select_related("item").order_by("-pk")[:10]
    return render(request, "lostfound/list.html", ctx)


def item_create(request):
    user = request.user
    if not _staff(user):
        raise PermissionDenied
    form = ItemForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        item = form.save(commit=False)
        item.school, item.registered_by = user.school, user
        item.save()
        create_audit_log(user=user, action="create", request=request, target=item,
                         detail=f"Registrou nos achados e perdidos: {item.title}")
        messages.success(request, "Objeto registrado. Se tiver nome escrito, identifique o dono para avisar a família.")
        return redirect("lostfound:item", pk=item.pk)
    return render(request, "lostfound/form.html", {"form": form})


def item_detail(request, pk):
    user = request.user
    item = _visible_item(user, pk)
    staff = _staff(user)
    kids = _own_students(user)
    ctx = {"item": item, "staff": staff, "can_manage": staff and _can_manage(user, item),
           "show_details": staff or not item.valuable,
           "owner_is_mine": item.student_id and any(s.pk == item.student_id for s in kids), "kids": kids}
    if ctx["can_manage"]:
        ctx["claims"] = item.claims.select_related("user", "student")
        q = (request.GET.get("q") or "").strip()[:60]
        if q and item.status == FoundItem.Status.KEPT:
            qs = Student.objects.filter(school=user.school, status="ativo")
            from apps.library.services import class_names

            found = list((qs.filter(code=q) if digits(q) else qs.filter(name_q(q)))
                         .order_by("first_name", "last_name")[:15])
            classes = class_names(found)
            ctx["found"] = [{"s": s, "cls": classes.get(s.pk, "")} for s in found]
        ctx["q"] = q
    elif not staff:
        ctx["mine"] = item.claims.filter(user=user).order_by("-pk").first()
    return render(request, "lostfound/item.html", ctx)


def item_photo(request, pk):
    user = request.user
    item = _visible_item(user, pk)
    if not item.photo or (item.valuable and not _staff(user)):
        raise Http404
    resp = FileResponse(item.photo.open("rb"),
                        content_type=mimetypes.guess_type(item.photo.name)[0] or "image/jpeg")
    resp["Cache-Control"] = "private, max-age=300"
    return resp


@require_POST
def item_claim(request, pk):
    user = request.user
    item = _visible_item(user, pk)
    if user.role not in FAMILY or item.status != FoundItem.Status.KEPT:
        raise PermissionDenied
    kids = _own_students(user)
    student = next((s for s in kids if s.pk == as_id(request.POST.get("estudante"))), kids[0] if len(kids) == 1
                   else None)
    description = (request.POST.get("descricao") or "").strip()[:300]
    if len(description) < 10:
        messages.error(request, "Descreva um detalhe que só o dono sabe (marca, adesivo, nome escrito, o que tem "
                                "dentro). É assim que a escola confere antes de entregar.")
        return redirect("lostfound:item", pk=item.pk)
    if item.claims.filter(user=user, status=Claim.Status.PENDING).exists():
        messages.info(request, "Você já pediu este objeto. A escola vai conferir.")
        return redirect("lostfound:item", pk=item.pk)
    claim = Claim.objects.create(item=item, user=user, student=student, description=description)
    create_audit_log(user=user, action="create", request=request, target=claim,
                     detail=f"Disse que “{item.title}” é seu" + (f" ({student})" if student else ""))
    staff = User.objects.filter(school=item.school, is_active=True, role=Role.SECRETARIA.value)
    notify_many(item.school, list(staff) + ([item.registered_by] if item.registered_by else []),
                Notification.Kind.LIBRARY, f"Achados e perdidos: pedido de “{item.title}”",
                body=f"{user.get_full_name() or user.username} diz que é seu. Confira a descrição antes de entregar.",
                url=reverse("lostfound:item", args=[item.pk]), dedupe_key=f"achados:pedido:{claim.pk}")
    messages.success(request, "Pedido enviado. A escola confere a descrição e avisa quando puder retirar.")
    return redirect("lostfound:item", pk=item.pk)


@require_POST
def item_owner(request, pk):
    """Nome escrito no objeto: a escola indica o estudante e a família é avisada."""
    from apps.communication.family_events import notify_family

    user = request.user
    item = get_object_or_404(FoundItem, pk=pk, school=user.school, status=FoundItem.Status.KEPT)
    if not _can_manage(user, item):
        raise PermissionDenied
    student = get_object_or_404(Student, pk=as_id(request.POST.get("estudante")), school=user.school)
    item.student = student
    item.save(update_fields=["student"])
    create_audit_log(user=user, action="update", request=request, target=item,
                     detail=f"Identificou {student} como dono de “{item.title}”")
    notify_family(student, "achados", f"Achados e perdidos: {item.title} de {student.first_name}",
                  body=f"Encontramos com o nome de {student.first_name}{f' ({item.place})' if item.place else ''}. "
                       f"Está guardado na escola: retire na secretaria.",
                  url=reverse("lostfound:item", args=[item.pk]), dedupe_key=f"achados:dono:{item.pk}:{student.pk}")
    messages.success(request, f"A família de {student.first_name} foi avisada.")
    return redirect("lostfound:item", pk=item.pk)


@require_POST
def item_return(request, pk):
    """Entregue: a quem (pedido confirmado ou pessoa no balcão). Os outros pedidos ficam recusados."""
    user = request.user
    with transaction.atomic():
        item = get_object_or_404(FoundItem, pk=pk, school=user.school, status=FoundItem.Status.KEPT)
        if not _can_manage(user, item):
            raise PermissionDenied
        claim = item.claims.filter(pk=as_id(request.POST.get("pedido")), status=Claim.Status.PENDING).first()
        to = (request.POST.get("entregue_a") or "").strip()[:120] or (
            (claim.user.get_full_name() or claim.user.username) if claim else "")
        if not to:
            messages.error(request, "Diga a quem o objeto foi entregue.")
            return redirect("lostfound:item", pk=item.pk)
        now = timezone.now()
        item.status, item.returned_to, item.closed_at, item.closed_by = FoundItem.Status.RETURNED, to, now, user
        _close_photo(item)
        item.save()
        if claim:
            claim.status, claim.answered_by, claim.answered_at = Claim.Status.ACCEPTED, user, now
            claim.save(update_fields=["status", "answered_by", "answered_at"])
        others = list(item.claims.filter(status=Claim.Status.PENDING).select_related("user"))
        item.claims.filter(status=Claim.Status.PENDING).update(status=Claim.Status.REJECTED, answered_by=user,
                                                               answered_at=now)
        create_audit_log(user=user, action="update", request=request, target=item,
                         detail=f"Entregou “{item.title}” a {to}")
    for c in others:
        notify_many(item.school, [c.user], Notification.Kind.LIBRARY, f"Achados e perdidos: {item.title}",
                    body="O objeto foi entregue a quem comprovou ser o dono. Se o seu continua sumido, fale com a "
                         "secretaria.", url=reverse("lostfound:list"), dedupe_key=f"achados:outro:{c.pk}")
    messages.success(request, f"Entrega registrada: {to}.")
    return redirect("lostfound:list")


@require_POST
def claim_reject(request, pk):
    user = request.user
    claim = get_object_or_404(Claim.objects.select_related("item", "user"), pk=pk, item__school=user.school,
                              status=Claim.Status.PENDING)
    if not _can_manage(user, claim.item):
        raise PermissionDenied
    claim.status, claim.answered_by, claim.answered_at = Claim.Status.REJECTED, user, timezone.now()
    claim.save(update_fields=["status", "answered_by", "answered_at"])
    create_audit_log(user=user, action="update", request=request, target=claim,
                     detail=f"Recusou o pedido de “{claim.item.title}”: a descrição não confere")
    notify_many(claim.item.school, [claim.user], Notification.Kind.LIBRARY,
                f"Achados e perdidos: {claim.item.title}",
                body="A descrição não confere com o objeto guardado. Se tiver certeza de que é seu, fale com a "
                     "secretaria pessoalmente.", url=reverse("lostfound:list"), dedupe_key=f"achados:recusa:{claim.pk}")
    messages.success(request, "Pedido recusado e a família avisada.")
    return redirect("lostfound:item", pk=claim.item_id)


@require_POST
def donate_old(request):
    """Guardados há mais de 60 dias, sem pedido aguardando: doados ou descartados de uma vez."""
    user = request.user
    if not user.school_id or user.role not in MANAGERS:
        raise PermissionDenied
    limit = timezone.localdate() - datetime.timedelta(days=DONATE_AFTER_DAYS)
    items = list(FoundItem.objects.filter(school=user.school, status=FoundItem.Status.KEPT, found_on__lt=limit)
                 .exclude(claims__status=Claim.Status.PENDING))
    now = timezone.now()
    for item in items:
        item.status, item.closed_at, item.closed_by = FoundItem.Status.DONATED, now, user
        _close_photo(item)
        item.save()
    create_audit_log(user=user, action="update", request=request, target=None,
                     detail=f"Marcou {len(items)} objeto(s) dos achados e perdidos como doados")
    messages.success(request, f"{len(items)} objeto(s) marcados como doados ou descartados.")
    return redirect("lostfound:list")
