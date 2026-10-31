"""Grafo de pré-requisitos, alertas precoces e validação dos modelos."""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.academics.models import ClassGroup
from apps.core.models import Role, create_audit_log
from apps.curriculum.models import CurriculumItem

from . import access, alerts, graph, predictive
from .mastery import assess, group_evidence
from .models import LearningAlert, MasteryScale, ModelRun, SkillEvidence, SkillRelation


def _staff_team(user):
    return user.role in (Role.COORDENACAO.value, Role.DIRECAO.value)


def skill_graph(request, item_id):
    """Pré-requisitos e habilidades que podem depender desta, com contexto da turma."""
    user = request.user
    if not access.can_use(user):
        raise PermissionDenied
    item = get_object_or_404(CurriculumItem.objects.filter(CurriculumItem.visible_q(user.school)), pk=item_id)
    prereqs = list(graph.prerequisites(item, user.school))
    deps = list(graph.dependents(item, user.school))
    second = graph.chain(item, user.school, depth=2)
    context_class = None
    states = {}
    cg_id = request.GET.get("turma", "")
    if cg_id.isdigit():
        cg = get_object_or_404(ClassGroup, pk=int(cg_id), school=user.school)
        if access.can_view_class(user, cg):
            context_class = cg
            scale = MasteryScale.for_school(user.school)
            ids = [r.source_id for r in prereqs] + [item.pk] + [r.target_id for r in deps]
            grouped = group_evidence(SkillEvidence.objects.filter(class_group=cg, item_id__in=ids))
            for iid in ids:
                cnt = {"dificuldade": 0, "consolidada": 0, "avaliados": 0}
                for (sid, i), evs in grouped.items():
                    if i != iid:
                        continue
                    a = assess(evs, scale)
                    if a.level >= 2:
                        cnt["avaliados"] += 1
                    if a.state == "dificuldade":
                        cnt["dificuldade"] += 1
                    if a.state in ("consolidada", "consolidacao"):
                        cnt["consolidada"] += 1
                states[iid] = cnt
    assoc = {}
    for r in prereqs:
        assoc[r.pk] = graph.association(r.source, item, user.school)
    for r in prereqs:
        r.ctx = states.get(r.source_id)
        r.assoc = assoc.get(r.pk)
    for r in deps:
        r.ctx = states.get(r.target_id)
    candidates = []
    if _staff_team(user):
        candidates = CurriculumItem.objects.filter(school__isnull=True, kind="habilidade", component=item.component,
                                                   active=True).exclude(pk=item.pk).order_by("code")
    return render(request, "cognitio/skill_graph.html", {
        "item": item, "prereqs": prereqs, "deps": deps, "second": [r for r, _ in second if r.target_id != item.pk],
        "context_class": context_class, "item_ctx": states.get(item.pk), "can_curate": _staff_team(user),
        "candidates": candidates, "kinds": SkillRelation.Kind.choices,
    })


@require_POST
def relation_curate(request, item_id):
    user = request.user
    if not _staff_team(user):
        raise PermissionDenied
    item = get_object_or_404(CurriculumItem, pk=item_id)
    action = request.POST.get("acao")
    if action == "nova":
        src = get_object_or_404(CurriculumItem, pk=request.POST.get("prerequisito"))
        kind = request.POST.get("tipo") if request.POST.get("tipo") in dict(SkillRelation.Kind.choices) else "hipotese"
        if kind == "estatistica":
            kind = "hipotese"  # associação estatística é calculada, não digitada
        SkillRelation.objects.update_or_create(
            school=user.school, source=src, target=item,
            defaults={"kind": kind, "confidence": request.POST.get("confianca") or "media", "status": "validada",
                      "origin": "manual", "validated_by": user, "validated_at": timezone.now(),
                      "rationale": (request.POST.get("justificativa") or "").strip()[:400]
                      or "Registrada pela equipe pedagógica."})
        detail = f"Registrou relação {src.code} → {item.code}"
    else:
        rel = get_object_or_404(SkillRelation, pk=request.POST.get("id"))
        if rel.school_id not in (None, user.school_id):
            raise PermissionDenied
        decision = request.POST.get("decisao")
        if rel.school_id is None:
            # Relação nacional proposta: a decisão vale para esta escola (cópia local).
            rel, _ = SkillRelation.objects.update_or_create(
                school=user.school, source=rel.source, target=rel.target,
                defaults={"kind": rel.kind, "confidence": rel.confidence, "origin": rel.origin,
                          "rationale": rel.rationale})
        rel.status = "validada" if decision == "validar" else "rejeitada"
        rel.validated_by, rel.validated_at = user, timezone.now()
        rel.save()
        detail = f"{'Validou' if decision == 'validar' else 'Rejeitou'} relação {rel.source.code} → {rel.target.code}"
    create_audit_log(user=user, action="update", request=request, target=item, detail=detail)
    messages.success(request, "Relação registrada.")
    return redirect("cognitio:skill_graph", item_id=item.pk)


def _alerts_visible(user):
    from apps.academics.permissions import teacher_pairs
    from apps.coordination.scope import class_scope

    qs = LearningAlert.objects.filter(school=user.school)
    if user.role == Role.PROFESSOR.value:
        pairs = teacher_pairs(user)
        q = Q(pk__in=[])
        for c, s in pairs:
            q |= Q(class_group_id=c, subject_id=s) | Q(class_group_id=c, subject__isnull=True)
        return qs.filter(q)
    if user.role == Role.COORDENACAO.value:
        scope = class_scope(user)
        return qs if scope is None else qs.filter(class_group_id__in=scope)
    if user.role == Role.DIRECAO.value:
        return qs
    return qs.none()


def alert_list(request):
    user = request.user
    if not access.can_use(user):
        raise PermissionDenied
    if request.method == "POST" and request.POST.get("recalcular"):
        from apps.academics.permissions import teacher_class_ids
        from apps.coordination.scope import class_scope

        if user.role == Role.PROFESSOR.value:
            classes = ClassGroup.objects.filter(pk__in=teacher_class_ids(user))
        else:
            scope = class_scope(user) if user.role == Role.COORDENACAO.value else None
            classes = ClassGroup.objects.filter(school=user.school, school_year__is_current=True)
            if scope is not None:
                classes = classes.filter(pk__in=scope)
        new = sum(alerts.generate_for_class(cg)[0] for cg in classes)
        messages.success(request, f"Alertas recalculados: {new} novo(s).")
        return redirect("cognitio:alerts")
    qs = _alerts_visible(user).select_related("student", "class_group", "subject", "item")
    status = request.GET.get("situacao", "ativos")
    if status == "ativos":
        qs = qs.filter(active=True).exclude(status__in=["descartado", "resolvido"])
    elif status in dict(LearningAlert.Status.choices):
        qs = qs.filter(status=status)
    rule = request.GET.get("regra", "")
    if rule in alerts.RULES:
        qs = qs.filter(rule=rule)
    cg = request.GET.get("turma", "")
    if cg.isdigit():
        qs = qs.filter(class_group_id=int(cg))
    from apps.core.pagination import paginate

    page = paginate(request, qs)
    classes = ClassGroup.objects.filter(pk__in=_alerts_visible(user).values("class_group_id")).order_by("name")
    return render(request, "cognitio/alerts.html", {
        "page": page, "alerts": page, "status": status, "rule": rule, "turma": cg,
        "status_choices": [("ativos", "Ativos")] + list(LearningAlert.Status.choices),
        "rule_choices": list(alerts.RULES.items()), "class_choices": [(c.pk, c.name) for c in classes],
        "model_run": predictive.active_run(user.school),
    })


@require_POST
def alert_review(request, pk):
    """O professor revisa o alerta: em análise, descartado (com motivo) ou com intervenção."""
    user = request.user
    alert = get_object_or_404(_alerts_visible(user), pk=pk)
    decision = request.POST.get("decisao")
    note = (request.POST.get("registro") or "").strip()[:400]
    if decision == "descartar" and not note:
        messages.error(request, "Para descartar, registre o motivo (ex.: a situação já foi resolvida em sala).")
        return redirect(request.POST.get("next") or "cognitio:alerts")
    mapping = {"analisar": "analise", "descartar": "descartado", "resolvido": "resolvido"}
    if decision in mapping:
        alert.status = mapping[decision]
        alert.status_note = note
        alert.reviewed_by, alert.reviewed_at = user, timezone.now()
        alert.save()
        create_audit_log(user=user, action="update", request=request, target=alert,
                         detail=f"Revisou alerta ({alert.get_status_display()}): {alert.title}")
        messages.success(request, "Revisão registrada.")
    if decision == "intervir":
        return redirect(f"{_url('cognitio:intervention_create')}?alerta={alert.pk}")
    nxt = request.POST.get("next", "")
    return redirect(nxt if nxt.startswith("/") else "cognitio:alerts")


def _url(name):
    from django.urls import reverse

    return reverse(name)


def models_page(request):
    """Validação e monitoramento dos modelos (coordenação e direção)."""
    user = request.user
    if not _staff_team(user):
        raise PermissionDenied
    if request.method == "POST":
        action = request.POST.get("acao")
        if action == "treinar":
            run = predictive.train_and_validate(user.school, user)
            create_audit_log(user=user, action="create", request=request, target=run,
                             detail=f"Executou validação do modelo {run.name}: {run.get_status_display()}")
            messages.success(request, f"Validação executada: {run.get_status_display()}.")
        elif action in ("aprovar", "desativar") and user.role == Role.DIRECAO.value:
            run = get_object_or_404(ModelRun, pk=request.POST.get("id"), school=user.school)
            if action == "aprovar" and run.status != ModelRun.Status.EXPERIMENTAL:
                messages.error(request, "Só um modelo validado tecnicamente (experimental) pode ser aprovado.")
            else:
                ModelRun.objects.filter(school=user.school, name=run.name, status=ModelRun.Status.APPROVED) \
                    .update(status=ModelRun.Status.DISABLED)
                run.status = ModelRun.Status.APPROVED if action == "aprovar" else ModelRun.Status.DISABLED
                run.decided_by, run.decided_at = user, timezone.now()
                run.save()
                create_audit_log(user=user, action="update", request=request, target=run,
                                 detail=f"{'Aprovou' if action == 'aprovar' else 'Desativou'} o modelo {run.name} "
                                        f"v{run.version}")
        return redirect("cognitio:models")
    runs = ModelRun.objects.filter(school=user.school)[:10]
    alert_stats = {}
    for a in LearningAlert.objects.filter(school=user.school).values("rule", "status"):
        d = alert_stats.setdefault(a["rule"], {"total": 0, "descartado": 0})
        d["total"] += 1
        d["descartado"] += a["status"] == "descartado"
    rows = [(alerts.RULES.get(k, k), v["total"], v["descartado"]) for k, v in alert_stats.items()]
    return render(request, "cognitio/models.html", {
        "runs": runs, "rules": alerts.RULES, "alert_rows": rows, "mins": (predictive.MIN_TRAIN, predictive.MIN_POS,
                                                                          predictive.MIN_TEST),
        "is_direction": user.role == Role.DIRECAO.value,
    })
