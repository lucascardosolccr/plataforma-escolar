"""Navegação pela ontologia curricular e curadoria das ligações sugeridas."""

from collections import OrderedDict

from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import services
from .models import AREAS, CurriculumCorrespondence, CurriculumItem, ItemDimension, SkillDimension
from .views import _log, _require

AREA_ORDER = ["Linguagens", "Matemática", "Ciências da Natureza", "Ciências Humanas", "Ensino Religioso"]


def ontology_map(request):
    """Área → componente → unidade temática (com contagem), competências e PNED."""
    user = request.user
    _require(services.can_use(user))
    rows = (CurriculumItem.objects.filter(school__isnull=True, kind="habilidade", active=True)
            .values("area", "component", "thematic_unit").annotate(n=Count("id")).order_by("component", "thematic_unit"))
    tree = OrderedDict((a, OrderedDict()) for a in AREA_ORDER)
    for r in rows:
        area = r["area"] or AREAS.get(r["component"], "Outros")
        comp = tree.setdefault(area, OrderedDict()).setdefault(r["component"], [])
        comp.append((r["thematic_unit"] or "Sem unidade identificada", r["n"]))
    specific = CurriculumItem.objects.filter(kind="competencia_especifica", active=True).order_by("code")
    digital = (CurriculumItem.objects.filter(kind="competencia_digital", active=True).order_by("code")
               .annotate(n=Count("correspondences_in", filter=Q(correspondences_in__rejected=False))))
    dims = SkillDimension.objects.annotate(n=Count("itemdimension")).order_by("component", "order")
    by_comp = OrderedDict()
    for d in dims:
        by_comp.setdefault(d.component, []).append(d)
    return render(request, "curriculum/ontology_map.html", {
        "tree": [(a, comps) for a, comps in tree.items() if comps], "specific": specific, "digital": digital,
        "dims": by_comp.items(),
    })


@require_POST
def item_curate(request, pk):
    """Coordenação e direção validam ou rejeitam ligações sugeridas e registram a
    interpretação operacional (o texto oficial nunca é alterado)."""
    user = request.user
    _require(services.can_manage_items(user))
    item = get_object_or_404(CurriculumItem.objects.filter(CurriculumItem.visible_q(user.school)), pk=pk)
    action = request.POST.get("acao")
    if action == "dimensao":
        link = get_object_or_404(ItemDimension, pk=request.POST.get("id"), item=item)
        if request.POST.get("decisao") == "rejeitar":
            detail = f"Rejeitou a dimensão {link.dimension} para {item.code}"
            link.delete()
        else:
            link.validated, link.origin = True, link.origin
            link.save(update_fields=["validated"])
            detail = f"Validou a dimensão {link.dimension} para {item.code}"
        _log(request, "update", item, detail)
    elif action == "nova_dimensao":
        dim = get_object_or_404(SkillDimension, pk=request.POST.get("dimensao"))
        ItemDimension.objects.update_or_create(item=item, dimension=dim, defaults={"origin": "manual", "validated": True})
        _log(request, "update", item, f"Associou a dimensão {dim} a {item.code}")
    elif action == "correspondencia":
        c = get_object_or_404(CurriculumCorrespondence, pk=request.POST.get("id"))
        _require(item.pk in (c.source_id, c.target_id) and (c.school_id in (None, user.school_id)))
        reject = request.POST.get("decisao") == "rejeitar"
        c.validated, c.rejected = not reject, reject
        c.validated_by, c.validated_at = user, timezone.now()
        if request.POST.get("confianca") in dict(CurriculumCorrespondence.Confidence.choices):
            c.confidence = request.POST["confianca"]
        c.save()
        _log(request, "update", item, f"{'Rejeitou' if reject else 'Validou'} correspondência "
                                      f"{c.source.code} → {c.target.code}")
    elif action == "nota":
        item.operational_note = (request.POST.get("nota") or "").strip()[:2000]
        item.save(update_fields=["operational_note"])
        _log(request, "update", item, f"Registrou interpretação operacional de {item.code}")
    messages.success(request, "Registro salvo.")
    return redirect("curriculum:item_detail", pk=item.pk)
