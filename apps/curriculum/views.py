from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.academics.models import ClassGroup, Subject
from apps.core.models import Role
from apps.core.pagination import paginate

from . import services
from .forms import CurriculumImportForm, CurriculumItemForm, EvidenceForm
from .models import COMPONENTS, CurriculumItem, LearningEvidence, NormativeReference


def _log(request, action, target, detail, target_type=None, target_id=None):
    from apps.core.models import create_audit_log

    create_audit_log(user=request.user, action=action, request=request, target=target, detail=detail,
                     **({"target_type": target_type, "target_id": target_id} if target is None else {}))


def _require(ok):
    if not ok:
        raise PermissionDenied


def catalog(request):
    """Catálogo: BNCC (nacional) e itens da escola, com busca e filtros."""
    user = request.user
    _require(services.can_use(user))
    qs = CurriculumItem.objects.filter(CurriculumItem.visible_q(user.school), active=True)
    kind = request.GET.get("tipo", "")
    if kind in dict(CurriculumItem.Kind.choices):
        qs = qs.filter(kind=kind)
    else:
        kind = ""
    comp = request.GET.get("componente", "")
    if comp in COMPONENTS:
        qs = qs.filter(component=comp)
    else:
        comp = ""
    year = request.GET.get("ano", "")
    if year.isdigit() and 1 <= int(year) <= 9:
        qs = qs.filter(pk__in=[i.pk for i in qs if int(year) in i.year_list])
    else:
        year = ""
    unit = (request.GET.get("unidade") or "").strip()
    unit_choices = []
    if comp:
        units_qs = CurriculumItem.objects.filter(CurriculumItem.visible_q(user.school), component=comp)
        if kind:
            units_qs = units_qs.filter(kind=kind)
        unit_choices = [(u, u) for u in units_qs.exclude(thematic_unit="").values_list("thematic_unit", flat=True)
                        .distinct().order_by("thematic_unit")]
    status = request.GET.get("situacao", "")
    if status == "a_conferir" and services.can_manage_items(user):
        qs = qs.filter(needs_review=True, school=user.school)
    elif status == "sugestoes" and services.can_manage_items(user):
        qs = qs.filter(correspondences_out__school=user.school, correspondences_out__validated=False,
                       correspondences_out__rejected=False).distinct()
    else:
        status = ""
    if unit and comp:
        qs = qs.filter(thematic_unit=unit)
    else:
        unit = ""
    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(code__icontains=q) | Q(text__icontains=q))
    page = paginate(request, qs.order_by("kind", "code"))
    return render(request, "curriculum/catalog.html", {
        "page": page, "items": page, "kind": kind, "comp": comp, "year": year, "q": q,
        "kind_choices": CurriculumItem.Kind.choices, "comp_choices": [(c, c) for c in COMPONENTS],
        "year_choices": [(str(n), f"{n}º ano") for n in range(1, 10)],
        "filtered": bool(kind or comp or year or q or unit or status), "can_manage": services.can_manage_items(user),
        "unit": unit, "unit_choices": unit_choices, "status": status,
        "status_choices": [("a_conferir", "Texto a conferir"), ("sugestoes", "Com sugestões de correspondência")],
    })


def item_detail(request, pk):
    """Um item: texto, fonte e onde foi usado no alcance de quem consulta.

    As "sugestões" são propostas já registradas no alcance da própria pessoa
    (as do professor, de qualquer ano). São sugestões: a decisão é dele.
    """
    from apps.pedagogy.models import Activity, Evaluation, LessonPlan

    user = request.user
    _require(services.can_use(user))
    item = get_object_or_404(CurriculumItem.objects.filter(CurriculumItem.visible_q(user.school)), pk=pk)
    pairs = services.pairs_for(user)
    if user.role == Role.PROFESSOR.value:
        acts = Activity.objects.filter(curriculum=item, created_by=user)
        plans = LessonPlan.objects.filter(curriculum=item, teacher=user)
        evals = Evaluation.objects.filter(curriculum=item, created_by=user)
    else:
        class_ids = {c for c, _ in pairs}
        acts = Activity.objects.filter(curriculum=item, class_group_id__in=class_ids)
        plans = LessonPlan.objects.filter(curriculum=item, class_group_id__in=class_ids)
        evals = Evaluation.objects.filter(curriculum=item, class_group_id__in=class_ids)
    acts = acts.exclude(status=Activity.Status.CANCELED).select_related("class_group", "subject")
    from .models import CurriculumCorrespondence, ItemDimension, SkillDimension

    corr = CurriculumCorrespondence.objects.filter(
        Q(source=item) | Q(target=item), Q(school__isnull=True) | Q(school=user.school), rejected=False
    ).select_related("source", "target")
    return render(request, "curriculum/item_detail.html", {
        "item": item,
        "dimension_links": ItemDimension.objects.filter(item=item).select_related("dimension"),
        "dimension_options": SkillDimension.objects.filter(
            Q(component=item.component) | Q(component="Competências digitais")).order_by("component", "order"),
        "correspondences": corr,
        "can_curate": services.can_manage_items(user),
        "activities": acts.order_by("-class_date")[:20],
        "plans": plans.select_related("class_group", "subject").order_by("-starts_on")[:20],
        "evaluations": evals.select_related("class_group", "subject").order_by("-date")[:20],
        "related": item.bncc.all() if item.is_local else item.local_items.filter(school=user.school),
        "is_teacher": user.role == Role.PROFESSOR.value,
    })


def coverage(request):
    """Acompanhamento curricular por turma e disciplina."""
    user = request.user
    _require(services.can_use(user))
    options = services.pair_options(user)
    chosen = request.GET.get("par", "")
    pair = None
    for cg, s in options:
        if chosen == f"{cg.pk}:{s.pk}":
            pair = (cg, s)
    if pair is None and options and not chosen:
        pair = options[0]
    if chosen and pair is None:
        raise PermissionDenied
    data = services.coverage(*pair) if pair else None
    return render(request, "curriculum/coverage.html", {
        "options": [(f"{cg.pk}:{s.pk}", f"{cg.name} — {s.name}") for cg, s in options],
        "pair": pair, "par": f"{pair[0].pk}:{pair[1].pk}" if pair else "", "data": data,
        "can_record": user.role == Role.PROFESSOR.value,
    })


def evidence_list(request):
    user = request.user
    _require(services.can_use(user))
    pairs = services.pairs_for(user)
    q = Q(pk__in=[])
    for c, s in pairs:
        q |= Q(class_group_id=c, subject_id=s)
    qs = LearningEvidence.objects.filter(q, school=user.school).select_related("item", "class_group", "subject",
                                                                               "teacher")
    page = paginate(request, qs)
    return render(request, "curriculum/evidence_list.html", {"page": page, "items": page,
                                                             "can_record": user.role == Role.PROFESSOR.value})


def evidence_create(request):
    """O professor registra a evidência de aprendizagem da turma."""
    from apps.academics.permissions import teaches

    user = request.user
    _require(user.role == Role.PROFESSOR.value)
    pairs = [(cg, s) for cg, s in services.pair_options(user) if teaches(user, cg, s, edit=True)]
    _require(bool(pairs))
    item_qs = CurriculumItem.objects.filter(CurriculumItem.visible_q(user.school), active=True)
    initial = {}
    if request.GET.get("par"):
        initial["pair"] = request.GET["par"]
    if request.GET.get("item", "").isdigit():
        initial["item"] = request.GET["item"]
    form = EvidenceForm(request.POST or None, user=user, pairs=pairs, item_qs=item_qs, initial=initial)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            ev = form.save(commit=False)
            ev.school = user.school
            ev.class_group, ev.subject = form.class_group, form.subject
            ev.teacher = user
            ev.save()
            _log(request, "create", ev, f"Registrou evidência de aprendizagem ({ev.item.code}) em "
                                        f"{ev.class_group} — {ev.subject}")
        messages.success(request, "Evidência registrada.")
        return redirect(f"{_coverage_url()}?par={ev.class_group_id}:{ev.subject_id}")
    return render(request, "curriculum/evidence_form.html", {"form": form})


def _coverage_url():
    from django.urls import reverse

    return reverse("curriculum:coverage")


def item_create(request):
    user = request.user
    _require(services.can_manage_items(user))
    form = CurriculumItemForm(request.POST or None, school=user.school)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            item = form.save(commit=False)
            item.school = user.school
            item.created_by = user
            item.save()
            item.bncc.set(form.cleaned_data["bncc_codes"])
            _link_bncc(item, form.cleaned_data["bncc_codes"], user, "manual", "media")
            _log(request, "create", item, f"Cadastrou item curricular {item.code}")
        messages.success(request, "Item curricular cadastrado.")
        return redirect("curriculum:item_detail", pk=item.pk)
    return render(request, "curriculum/item_form.html", {"form": form})


def _link_bncc(item, targets, user, origin, confidence, relation=""):
    """Correspondência do item da escola com a BNCC, a validar pedagogicamente."""
    from .models import CurriculumCorrespondence as C

    relation = relation if relation in dict(C.Relation.choices) else C.Relation.RELATED
    for t in targets:
        C.objects.update_or_create(school=item.school, source=item, target=t, defaults={
            "relation": relation, "confidence": confidence, "origin": origin, "rejected": False,
            "rationale": "Informada na planilha importada" if origin == "importacao" else "Informada no cadastro"})


def item_import(request):
    """Importa objetivos do Currículo em Movimento ou próprios a partir de CSV."""
    from . import df_curriculum

    user = request.user
    _require(services.can_manage_items(user))
    if request.method == "POST" and request.POST.get("acao") == "curriculo_df":
        r = df_curriculum.import_for_school(user.school, user)
        _log(request, "import", None, f"Importou o Currículo em Movimento do DF (arquivo incluído): {r['created']} novos, "
                                      f"{r['updated']} atualizados, {r['kept']} já conferidos mantidos, "
                                      f"{r['suggestions']} sugestões de correspondência",
             target_type="CurriculumItem", target_id="curriculo_df")
        messages.success(request, f"Currículo em Movimento do DF: {r['created']} itens novos, {r['updated']} atualizados, "
                                  f"{r['kept']} já conferidos mantidos sem alteração e {r['suggestions']} sugestões "
                                  "de correspondência com a BNCC para validar.")
        return redirect("curriculum:item_import")
    form = CurriculumImportForm(request.POST or None, request.FILES or None)
    report = None
    if request.method == "POST" and form.is_valid():
        kinds = {CurriculumItem.Kind.DF_OBJECTIVE, CurriculumItem.Kind.DF_CONTENT, CurriculumItem.Kind.OWN}
        created = updated = 0
        errors = []
        with transaction.atomic():
            for n, row in enumerate(form.cleaned_data["file"], start=2):
                kind, code, text = row.get("tipo", ""), row.get("codigo", ""), row.get("texto", "")
                if kind not in kinds or not code or not text or not row.get("fonte"):
                    errors.append(f"Linha {n}: tipo, código, texto e fonte são obrigatórios "
                                  "(tipo: objetivo_df, conteudo_df ou proprio).")
                    continue
                comp = row.get("componente", "")
                if comp and comp not in COMPONENTS:
                    errors.append(f"Linha {n}: componente '{comp}' não reconhecido.")
                    continue
                item, new = CurriculumItem.objects.update_or_create(
                    school=user.school, kind=kind, code=code[:30],
                    defaults={"text": text, "component": comp, "years": row.get("anos", "").replace(" ", "")[:40],
                              "source": row["fonte"][:250], "source_url": row.get("url", "")[:200],
                              "created_by": user, "active": True})
                codes = [c.upper() for c in row.get("habilidades_bncc", "").replace(";", ",").split(",") if c.strip()]
                if codes:
                    targets = CurriculumItem.objects.filter(school__isnull=True, kind="habilidade",
                                                            code__in=[c.strip() for c in codes])
                    item.bncc.set(targets)
                    conf = row.get("confianca", "").lower()
                    _link_bncc(item, targets, user, "importacao", conf if conf in ("alta", "media", "baixa") else "media",
                               row.get("relacao", "").lower())
                created += new
                updated += not new
            _log(request, "import", None, f"Importou itens curriculares: {created} novos, {updated} atualizados, "
                                          f"{len(errors)} linhas recusadas", target_type="CurriculumItem",
                 target_id="importacao")
        report = {"created": created, "updated": updated, "errors": errors}
    return render(request, "curriculum/item_import.html", {
        "form": form, "report": report, "df_meta": df_curriculum.dataset()["meta"],
        "df_total": len(df_curriculum.dataset()["itens"]), "df_imported": df_curriculum.imported_count(user.school)})


def references(request):
    """Consulta normativa e pedagógica."""
    user = request.user
    _require(getattr(user, "is_authenticated", False) and user.role in services.REFERENCE_ROLES)
    qs = NormativeReference.objects.all()
    nature = request.GET.get("natureza", "")
    if nature in dict(NormativeReference.Nature.choices):
        qs = qs.filter(nature=nature)
    else:
        nature = ""
    topic = request.GET.get("assunto", "")
    topics = sorted(set(NormativeReference.objects.values_list("topic", flat=True)))
    if topic in topics:
        qs = qs.filter(topic=topic)
    else:
        topic = ""
    return render(request, "curriculum/references.html", {
        "refs": qs, "nature": nature, "topic": topic,
        "nature_choices": NormativeReference.Nature.choices, "topic_choices": [(t, t) for t in topics],
        "filtered": bool(nature or topic),
    })


def picker_group(request):
    """Itens de um grupo do seletor de habilidades, carregados quando a pessoa abre o grupo.

    O catálogo é público (BNCC e itens da própria escola); só a equipe usa o seletor."""
    user = request.user
    if not user.is_staff_role:
        raise PermissionDenied
    comp, kind = request.GET.get("comp", ""), request.GET.get("kind", "")
    year = int(request.GET["year"]) if (request.GET.get("year") or "").isdigit() else None
    items = services.group_items(user.school, comp, year, kind) if comp and kind else []
    return render(request, "curriculum/_picker_items.html", {
        "items": items, "name": "curriculum", "group": (request.GET.get("g") or "0")[:4]})
