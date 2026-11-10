"""Telas da lista de materiais. As regras de quem pode o quê estão em ``services``."""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Max
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.models import create_audit_log
from apps.core.pagination import paginate
from apps.core.params import as_id

from . import services as sv
from .forms import ItemForm, ListForm, PasteForm
from .models import SupplyCheck, SupplyItem, SupplyList

S = SupplyList.Status


def _rows(lst, done=frozenset(), warnings=False):
    return [{"item": i, "unit": sv.unit_label(i.unit, i.quantity) if i.unit else "", "done": i.pk in done,
             "warnings": sv.item_warnings(i) if warnings else []} for i in lst.items.all()]


def _editable(user, pk):
    lst = get_object_or_404(SupplyList, pk=pk, school=user.school) if user.school_id else None
    if not lst or not sv.can_edit(user, lst):
        raise PermissionDenied
    return lst


def _managed(user, pk, *statuses):
    if not sv.is_manager(user):
        raise PermissionDenied
    return get_object_or_404(SupplyList, pk=pk, school=user.school, status__in=statuses)


def index(request):
    user = request.user
    if sv.is_staff(user):
        qs = (sv.staff_lists(user).select_related("school_year", "created_by").prefetch_related("class_groups")
              .annotate(n_items=Count("items")))
        status = request.GET.get("situacao", "")
        if status in S.values:
            qs = qs.filter(status=status)
        return render(request, "supplies/index.html", {
            "staff": True, "page": paginate(request, qs), "status": status, "statuses": S.choices,
            "manager": sv.is_manager(user),
            "n_review": sv.staff_lists(user).filter(status=S.REVIEW).count() if sv.is_manager(user) else 0,
            "returned": sv.staff_lists(user).filter(status=S.DRAFT, created_by=user).exclude(review_note="").count(),
        })
    if not user.school_id or user.role not in sv.FAMILY:
        raise PermissionDenied
    kids = sv.own_students(user)
    mine, ids = [], set()
    for s, lists in sv.lists_by_student(kids, user.school).items():
        entries = []
        for lst in lists:
            done, required, _ = sv.progress(lst, s)
            entries.append({"lst": lst, "done": done, "required": required})
            ids.add(lst.pk)
        mine.append({"s": s, "lists": entries})
    others = (sv.visible_published(user.school).exclude(pk__in=ids).select_related("school_year")
              .prefetch_related("class_groups"))
    return render(request, "supplies/index.html", {"staff": False, "mine": mine, "others": others})


def detail(request, pk):
    user = request.user
    lst = get_object_or_404(sv.viewable(user).select_related("school_year", "created_by", "published_by"), pk=pk)
    ctx = {"lst": lst, "classes": list(lst.class_groups.all())}
    if sv.is_staff(user):
        edit = sv.can_edit(user, lst)
        ctx.update(staff=True, can_edit=edit, manager=sv.is_manager(user), rows=_rows(lst, warnings=True),
                   item_form=ItemForm(), paste_form=PasteForm(),
                   n_students=sv.enrolled_students(lst).count() if ctx["classes"] else 0,
                   can_submit=edit and lst.status == S.DRAFT and not sv.is_manager(user))
        ctx["n_warnings"] = sum(1 for r in ctx["rows"] if r["warnings"])
        return render(request, "supplies/detail.html", ctx)
    kids = sv.own_students(user)
    linked = sv.lists_by_student(kids, user.school)
    chosen = next((s for s in kids if s.pk == as_id(request.GET.get("estudante"))), None) or next(
        (s for s in kids if lst in linked.get(s, [])), kids[0] if kids else None)
    done = set()
    if chosen:
        ctx["n_done"], ctx["n_required"], done = sv.progress(lst, chosen)
    ctx.update(staff=False, kids=kids, chosen=chosen, rows=_rows(lst, done))
    return render(request, "supplies/detail.html", ctx)


def list_text(request, pk):
    lst = get_object_or_404(sv.viewable(request.user), pk=pk)
    resp = HttpResponse(sv.as_text(lst), content_type="text/plain; charset=utf-8")
    resp["Content-Disposition"] = "inline"
    return resp


@require_POST
def checks_save(request, pk):
    user = request.user
    if user.role not in sv.FAMILY:
        raise PermissionDenied
    lst = get_object_or_404(sv.visible_published(user.school) if user.school_id else SupplyList.objects.none(), pk=pk)
    student = next((s for s in sv.own_students(user) if s.pk == as_id(request.POST.get("estudante"))), None)
    if not student:
        raise PermissionDenied
    items = set(lst.items.values_list("pk", flat=True))
    wanted = items if request.POST.get("tudo") else {as_id(v) for v in request.POST.getlist("item")} & items
    with transaction.atomic():
        SupplyCheck.objects.filter(item__supply_list=lst, student=student).exclude(item_id__in=wanted).delete()
        have = set(SupplyCheck.objects.filter(item__supply_list=lst, student=student).values_list("item_id", flat=True))
        SupplyCheck.objects.bulk_create([SupplyCheck(item_id=i, student=student, checked_by=user)
                                         for i in wanted - have])
    messages.success(request, "Tudo marcado como providenciado." if request.POST.get("tudo") else "Anotado.")
    return redirect(f"{lst.get_absolute_url()}?estudante={student.pk}")


def list_form(request, pk=None):
    user = request.user
    if pk:
        lst = _editable(user, pk)
    elif sv.is_staff(user):
        lst = None
    else:
        raise PermissionDenied
    form = ListForm(request.POST or None, instance=lst, school=user.school)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if not lst:
            obj.school, obj.created_by = user.school, user
        obj.save()
        form.save_m2m()
        create_audit_log(user=user, action="update" if lst else "create", request=request, target=obj,
                         detail=f"{'Editou' if lst else 'Criou'} a lista de materiais “{obj.title}”")
        if not lst:
            messages.success(request, "Lista criada. Agora inclua os materiais: um a um ou colando a lista que você "
                                      "já tem.")
        return redirect(obj.get_absolute_url())
    return render(request, "supplies/list_form.html", {"form": form, "lst": lst})


@require_POST
def item_add(request, pk):
    lst = _editable(request.user, pk)
    form = ItemForm(request.POST)
    if form.is_valid():
        item = form.save(commit=False)
        item.supply_list = lst
        item.position = (lst.items.aggregate(m=Max("position"))["m"] or 0) + 1
        item.save()
        for w in sv.item_warnings(item):
            messages.warning(request, f"{item.name}: {w}")
        messages.success(request, f"Incluído: {item.name}.")
    else:
        messages.error(request, "Confira o material: " + "; ".join(e for errs in form.errors.values() for e in errs))
    return redirect(f"{lst.get_absolute_url()}#materiais")


@require_POST
def items_paste(request, pk):
    lst = _editable(request.user, pk)
    form = PasteForm(request.POST)
    parsed = sv.parse_text(form.cleaned_data["texto"]) if form.is_valid() else []
    if not parsed:
        messages.error(request, "Nenhum material reconhecido. Use uma linha por material, com a quantidade no começo.")
        return redirect(f"{lst.get_absolute_url()}#colar")
    n = sv.add_items(lst, parsed)
    messages.success(request, f"{n} materia{'is' if n != 1 else 'l'} incluído{'s' if n != 1 else ''}. Confira as "
                              "quantidades e as unidades.")
    return redirect(f"{lst.get_absolute_url()}#materiais")


def item_edit(request, pk):
    item = get_object_or_404(SupplyItem.objects.select_related("supply_list"), pk=pk)
    lst = _editable(request.user, item.supply_list_id)
    form = ItemForm(request.POST or None, instance=item)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect(f"{lst.get_absolute_url()}#materiais")
    return render(request, "supplies/item_form.html", {"form": form, "lst": lst, "item": item})


@require_POST
def item_delete(request, pk):
    item = get_object_or_404(SupplyItem, pk=pk)
    lst = _editable(request.user, item.supply_list_id)
    item.delete()
    messages.success(request, f"Retirado: {item.name}.")
    return redirect(f"{lst.get_absolute_url()}#materiais")


@require_POST
def item_move(request, pk):
    item = get_object_or_404(SupplyItem, pk=pk)
    lst = _editable(request.user, item.supply_list_id)
    items = list(lst.items.all())
    i = next(n for n, it in enumerate(items) if it.pk == item.pk)
    j = i - 1 if request.POST.get("para") == "cima" else i + 1
    if 0 <= j < len(items):
        items[i], items[j] = items[j], items[i]
        for n, it in enumerate(items, start=1):
            it.position = n
        SupplyItem.objects.bulk_update(items, ["position"])
    return redirect(f"{lst.get_absolute_url()}#item-{item.pk}")


@require_POST
def list_submit(request, pk):
    user = request.user
    lst = _editable(user, pk)
    if lst.status != S.DRAFT or not lst.items.exists():
        messages.error(request, "Inclua os materiais antes de enviar.")
        return redirect(lst.get_absolute_url())
    lst.status, lst.review_note = S.REVIEW, ""
    lst.save(update_fields=["status", "review_note", "updated_at"])
    create_audit_log(user=user, action="update", request=request, target=lst,
                     detail=f"Enviou para revisão a lista de materiais “{lst.title}”")
    sv.notify_people(lst, sv.reviewers(lst.school, exclude=user), f"Lista de materiais para revisar: {lst.title}",
                     f"{user.get_full_name() or user.username} enviou a lista. Confira e publique, ou devolva com "
                     f"uma observação.")
    messages.success(request, "Enviada. A coordenação confere e publica, ou devolve com uma observação.")
    return redirect(lst.get_absolute_url())


@require_POST
def list_publish(request, pk):
    user = request.user
    lst = _managed(user, pk, S.DRAFT, S.REVIEW)
    if not lst.items.exists():
        messages.error(request, "A lista está vazia.")
        return redirect(lst.get_absolute_url())
    lst.status, lst.review_note = S.PUBLISHED, ""
    lst.published_at, lst.published_by, lst.revision = timezone.now(), user, lst.revision + 1
    lst.save()
    n = sv.notify_families(lst)
    create_audit_log(user=user, action="update", request=request, target=lst,
                     detail=f"Publicou a lista de materiais “{lst.title}” ({n} estudante(s) com aviso)")
    if lst.created_by_id and lst.created_by_id != user.pk:
        sv.notify_people(lst, [lst.created_by], f"Lista de materiais publicada: {lst.title}",
                         "A lista que você montou já está com as famílias.")
    if n:
        messages.success(request, f"Lista publicada. As famílias de {n} estudante{'s' if n != 1 else ''} foram "
                                  "avisadas.")
    else:
        messages.success(request, "Lista publicada. Nenhuma turma vinculada tem estudantes ainda, então ninguém foi "
                                  "avisado: a lista já aparece para todas as famílias em Lista de materiais. Quando "
                                  "as turmas existirem, vincule-as e use “Avisar as famílias”.")
    return redirect(lst.get_absolute_url())


@require_POST
def list_return(request, pk):
    user = request.user
    lst = _managed(user, pk, S.REVIEW)
    note = (request.POST.get("observacao") or "").strip()[:300]
    if len(note) < 5:
        messages.error(request, "Diga o que precisa mudar.")
        return redirect(lst.get_absolute_url())
    lst.status, lst.review_note = S.DRAFT, note
    lst.save(update_fields=["status", "review_note", "updated_at"])
    create_audit_log(user=user, action="update", request=request, target=lst,
                     detail=f"Devolveu a lista de materiais “{lst.title}”: {note}")
    if lst.created_by_id and lst.created_by_id != user.pk:
        sv.notify_people(lst, [lst.created_by], f"Lista de materiais devolvida: {lst.title}", note)
    messages.success(request, "Devolvida com a observação.")
    return redirect(lst.get_absolute_url())


@require_POST
def list_unpublish(request, pk):
    user = request.user
    lst = _managed(user, pk, S.PUBLISHED)
    lst.status = S.DRAFT
    lst.save(update_fields=["status", "updated_at"])
    create_audit_log(user=user, action="update", request=request, target=lst,
                     detail=f"Recolheu a lista de materiais “{lst.title}”")
    messages.success(request, "Lista recolhida: as famílias não a veem mais até nova publicação.")
    return redirect(lst.get_absolute_url())


@require_POST
def list_notify(request, pk):
    user = request.user
    lst = _managed(user, pk, S.PUBLISHED)
    lst.revision += 1
    lst.save(update_fields=["revision", "updated_at"])
    n = sv.notify_families(lst, update=True)
    create_audit_log(user=user, action="update", request=request, target=lst,
                     detail=f"Avisou as famílias da mudança na lista “{lst.title}” ({n} estudante(s))")
    messages.success(request, f"Aviso enviado às famílias de {n} estudante{'s' if n != 1 else ''}." if n else
                     "Nenhuma turma vinculada tem estudantes: ninguém foi avisado.")
    return redirect(lst.get_absolute_url())


@require_POST
def list_duplicate(request, pk):
    user = request.user
    if not sv.is_staff(user):
        raise PermissionDenied
    src = get_object_or_404(sv.viewable(user), pk=pk)
    with transaction.atomic():
        copy = SupplyList.objects.create(school=user.school, school_year=src.school_year, title=f"{src.title} (cópia)"[:120],
                                         grade=src.grade, intro=src.intro, created_by=user)
        SupplyItem.objects.bulk_create([SupplyItem(supply_list=copy, name=i.name, quantity=i.quantity, unit=i.unit,
                                                   notes=i.notes, optional=i.optional, position=i.position)
                                        for i in src.items.all()])
    create_audit_log(user=user, action="create", request=request, target=copy,
                     detail=f"Copiou a lista de materiais “{src.title}”")
    messages.success(request, "Cópia criada em rascunho. Ajuste o título, o ano e as turmas.")
    return redirect("supplies:edit", pk=copy.pk)


@require_POST
def list_delete(request, pk):
    user = request.user
    lst = _editable(user, pk)
    if lst.status == S.PUBLISHED:
        messages.error(request, "Recolha a lista antes de apagar.")
        return redirect(lst.get_absolute_url())
    create_audit_log(user=user, action="delete", request=request, target=lst,
                     detail=f"Apagou a lista de materiais “{lst.title}”")
    lst.delete()
    messages.success(request, "Lista apagada.")
    return redirect("supplies:index")
