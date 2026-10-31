"""Navegação pela ontologia curricular e curadoria das ligações sugeridas."""

from collections import OrderedDict

from django.contrib import messages
from django.db.models import Case, Count, Q, When
from django.http import QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import services
from .models import (AREAS, CurriculumCorrespondence, CurriculumItem, CurriculumItemVersion, ItemDimension,
                     SkillDimension)
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
    elif action == "conferir_texto":
        # só item da própria escola (ex.: Currículo em Movimento extraído do PDF); a BNCC nacional não é editada
        _require(item.school_id == user.school_id)
        text = " ".join((request.POST.get("texto") or "").split())
        if not text:
            messages.error(request, "O texto não pode ficar vazio.")
            return redirect("curriculum:item_detail", pk=item.pk)
        changed = text != item.text
        if changed:
            CurriculumItemVersion.objects.create(item=item, text=item.text, version_label="extração automática")
            item.text = text
        item.needs_review, item.verified_on = False, timezone.localdate()
        item.save(update_fields=["text", "needs_review", "verified_on"])
        _log(request, "update", item, f"Conferiu o texto de {item.code}{' e corrigiu a extração' if changed else ''}")
    elif action == "nota":
        item.operational_note = (request.POST.get("nota") or "").strip()[:2000]
        item.save(update_fields=["operational_note"])
        _log(request, "update", item, f"Registrou interpretação operacional de {item.code}")
    messages.success(request, "Registro salvo.")
    return redirect("curriculum:item_detail", pk=item.pk)


def curation_queue(request):
    """Fila de curadoria: correspondências da escola ainda não decididas, com os dois textos lado a lado,
    para validar ou rejeitar várias de uma vez. Correspondências nacionais (BNCC → PNED) ficam fora:
    a decisão de uma escola não altera o catálogo das outras."""
    from apps.core.pagination import paginate

    from .models import COMPONENTS

    user = request.user
    _require(services.can_manage_items(user))
    pending = CurriculumCorrespondence.objects.filter(school=user.school, validated=False, rejected=False)
    if request.method == "POST":
        decision = request.POST.get("decisao")
        ids = [i for i in request.POST.getlist("ids") if i.isdigit()]
        rows = list(pending.filter(pk__in=ids).select_related("source", "target"))
        if decision in ("validar", "rejeitar") and rows:
            reject = decision == "rejeitar"
            now = timezone.now()
            relation = request.POST.get("relacao", "")
            relation = relation if not reject and relation in dict(CurriculumCorrespondence.Relation.choices) else ""
            for c in rows:
                c.validated, c.rejected, c.validated_by, c.validated_at = not reject, reject, user, now
                c.relation = relation or c.relation
            CurriculumCorrespondence.objects.bulk_update(
                rows, ["validated", "rejected", "validated_by", "validated_at", "relation"])
            sample = ", ".join(f"{c.source.code} → {c.target.code}" for c in rows[:20])
            _log(request, "update", None, f"{'Rejeitou' if reject else 'Validou'} {len(rows)} correspondência(s) "
                                          f"na fila de curadoria: {sample}{' …' if len(rows) > 20 else ''}",
                 target_type="CurriculumCorrespondence", target_id="lote")
            messages.success(request, f"{len(rows)} correspondência{'s' if len(rows) > 1 else ''} "
                                      f"{'rejeitada' if reject else 'validada'}{'s' if len(rows) > 1 else ''}.")
        # volta para a mesma página e filtros (o caminho é sempre o desta tela; só a consulta é reaproveitada)
        back = QueryDict(mutable=True)
        for k, v in QueryDict(request.POST.get("voltar", "")).items():
            if k in ("componente", "ano", "confianca", "page"):
                back[k] = v
        return redirect(f"{request.path}?{back.urlencode()}" if back else request.path)
    comp = request.GET.get("componente", "")
    if comp in COMPONENTS:
        pending = pending.filter(source__component=comp)
    else:
        comp = ""
    year = request.GET.get("ano", "")
    if year.isdigit() and 1 <= int(year) <= 9:
        pending = pending.filter(source__years__regex=rf"(^|,){year}(,|$)")
    else:
        year = ""
    conf = request.GET.get("confianca", "")
    if conf in dict(CurriculumCorrespondence.Confidence.choices):
        pending = pending.filter(confidence=conf)
    else:
        conf = ""
    totals = dict(CurriculumCorrespondence.objects.filter(school=user.school, validated=False, rejected=False)
                  .values_list("confidence").annotate(n=Count("pk")))
    rank = Case(When(confidence="alta", then=0), When(confidence="media", then=1), default=2)
    page = paginate(request, pending.select_related("source", "target")
                    .annotate(rank=rank).order_by("rank", "source__code", "pk"))
    return render(request, "curriculum/curation_queue.html", {
        "page": page, "rows": page, "comp": comp, "year": year, "conf": conf,
        "comp_choices": [(c, c) for c in COMPONENTS], "year_choices": [(str(n), f"{n}º ano") for n in range(1, 10)],
        "conf_choices": CurriculumCorrespondence.Confidence.choices,
        "relation_choices": CurriculumCorrespondence.Relation.choices,
        "totals": [(label, totals[k]) for k, label in CurriculumCorrespondence.Confidence.choices if totals.get(k)],
        "total": sum(totals.values()), "filtered": bool(comp or year or conf),
        "back_qs": request.GET.urlencode(),
    })
