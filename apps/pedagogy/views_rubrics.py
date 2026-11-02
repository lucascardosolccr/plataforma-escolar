"""Rubricas de avaliação: cadastro e uso nas atividades de casa (Prompt 9 §8.2 e §8.3).

Quem cria: o professor. Quem usa: o próprio autor e, se a rubrica estiver
compartilhada, os colegas da escola. A coordenação e a direção consultam.
A família vê a rubrica na atividade e, depois da correção, só os níveis do
próprio filho.
"""

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.academics.models import Subject
from apps.communication.family_events import notify_family
from apps.core.models import Role, create_audit_log

from .models import Activity, Rubric, RubricCriterion, RubricDescriptor, RubricLevel, RubricScore

MAX_LEVELS, MAX_CRITERIA = 5, 8
STAFF = (Role.PROFESSOR.value, Role.COORDENACAO.value, Role.DIRECAO.value)


def rubrics_for(user):
    """Rubricas que a pessoa pode usar numa atividade: as dela e as compartilhadas."""
    return Rubric.objects.filter(school=user.school).filter(Q(created_by=user) | Q(shared=True))


class RubricForm(forms.Form):
    title = forms.CharField(label="Nome", max_length=150)
    description = forms.CharField(label="Para que serve", required=False, widget=forms.Textarea(attrs={"rows": 2}))
    subject = forms.ModelChoiceField(label="Disciplina", queryset=Subject.objects.none(), required=False)
    shared = forms.BooleanField(label="Colegas da escola podem usar", required=False)

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["subject"].queryset = Subject.objects.filter(school=school)

    def grid_from(self, data):
        """Lê a grade (níveis × critérios) enviada pelo formulário."""
        levels = []
        for i in range(MAX_LEVELS):
            label = (data.get(f"nivel_{i}") or "").strip()[:60]
            pts = (data.get(f"pontos_{i}") or "").strip().replace(",", ".")
            if label:
                try:
                    points = float(pts) if pts else None
                except ValueError:
                    points = "erro"
                levels.append({"i": i, "label": label, "points": points})
        criteria = []
        for j in range(MAX_CRITERIA):
            name = (data.get(f"criterio_{j}") or "").strip()[:150]
            if name:
                criteria.append({"j": j, "name": name, "cells": [
                    (data.get(f"desc_{j}_{lv['i']}") or "").strip()[:300] for lv in levels]})
        return levels, criteria


def _grid_errors(levels, criteria):
    errors = []
    if len(levels) < 2:
        errors.append("Informe pelo menos dois níveis (ex.: “Ainda não”, “Em parte”, “Atingiu”).")
    if not criteria:
        errors.append("Informe pelo menos um critério.")
    if any(lv["points"] == "erro" for lv in levels):
        errors.append("Os pontos de cada nível precisam ser números (ou ficar em branco).")
    return errors


def rubric_list(request):
    user = request.user
    if user.role not in STAFF:
        raise PermissionDenied
    qs = Rubric.objects.filter(school=user.school).select_related("subject", "created_by")
    if user.role == Role.PROFESSOR.value:
        qs = qs.filter(Q(created_by=user) | Q(shared=True))
    return render(request, "pedagogy/rubric_list.html", {
        "rubrics": qs, "can_create": user.role == Role.PROFESSOR.value})


def rubric_form(request, pk=None, duplicate=False):
    user = request.user
    if user.role != Role.PROFESSOR.value:
        raise PermissionDenied
    source = get_object_or_404(Rubric, pk=pk, school=user.school) if pk else None
    editing = source if (source and not duplicate) else None
    if source and duplicate and not (source.created_by_id == user.pk or source.shared):
        raise PermissionDenied
    if editing:
        if editing.created_by_id != user.pk:
            raise PermissionDenied
        if editing.in_use:
            messages.warning(request, "Esta rubrica já foi usada para avaliar. Para mudar, duplique: as avaliações "
                                      "feitas continuam com a rubrica original.")
            return redirect("pedagogy:rubric_list")
    initial = {}
    levels, criteria = [], []
    if source:
        initial = {"title": source.title + (" (cópia)" if duplicate else ""), "description": source.description,
                   "subject": source.subject_id, "shared": source.shared and not duplicate}
        lvs, rows = source.grid()
        levels = [{"i": i, "label": lv.label, "points": lv.points} for i, lv in enumerate(lvs)]
        criteria = [{"j": j, "name": c.name, "cells": cells} for j, (c, cells) in enumerate(rows)]
    form = RubricForm(request.POST or None, initial=initial, school=user.school)
    errors = []
    if request.method == "POST":
        levels, criteria = form.grid_from(request.POST)
        errors = _grid_errors(levels, criteria)
        if form.is_valid() and not errors:
            with transaction.atomic():
                r = editing or Rubric(school=user.school, created_by=user)
                for f in ("title", "description", "subject", "shared"):
                    setattr(r, f, form.cleaned_data[f])
                r.save()
                if editing:  # sem avaliações ainda: reescreve a grade inteira
                    r.criteria.all().delete()
                    r.levels.all().delete()
                lv_objs = [RubricLevel.objects.create(rubric=r, label=lv["label"], points=lv["points"], order=n)
                           for n, lv in enumerate(levels)]
                for n, c in enumerate(criteria):
                    crit = RubricCriterion.objects.create(rubric=r, name=c["name"], order=n)
                    RubricDescriptor.objects.bulk_create([
                        RubricDescriptor(criterion=crit, level=lv, text=text)
                        for lv, text in zip(lv_objs, c["cells"]) if text])
                create_audit_log(user=user, action="update" if editing else "create", request=request, target=r,
                                 detail=f"Rubrica {r.title}")
            messages.success(request, "Rubrica salva. Escolha-a no formulário da atividade de casa.")
            return redirect("pedagogy:rubric_list")
    # Linhas em branco para completar a grade na tela.
    while len(levels) < 4:
        levels.append({"i": len(levels), "label": "", "points": None})
    for lv_i, lv in enumerate(levels):
        lv["i"] = lv_i
    while len(criteria) < 4:
        criteria.append({"j": len(criteria), "name": "", "cells": []})
    for c in criteria:
        c["cells"] = (list(c["cells"]) + [""] * len(levels))[:len(levels)]
        c["cell_pairs"] = list(zip(levels, c["cells"]))
    return render(request, "pedagogy/rubric_form.html", {
        "form": form, "levels": levels, "criteria": criteria, "errors": errors, "obj": editing,
        "max_levels": MAX_LEVELS, "max_criteria": MAX_CRITERIA})


def activity_rubric_scores(request, pk):
    """Professor marca o nível de cada estudante em cada critério."""
    from .views import _activity_students, _get_managed_activity

    user = request.user
    act = _get_managed_activity(user, pk)
    if not act.rubric_id:
        messages.warning(request, "Esta atividade não tem rubrica. Escolha uma em Editar.")
        return redirect("pedagogy:activity_detail", pk=act.pk)
    rubric = act.rubric
    levels, rows = rubric.grid()
    criteria = [c for c, _ in rows]
    students = _activity_students(act, {})
    current = {}
    for sc in RubricScore.objects.filter(activity=act):
        current[(sc.student_id, sc.criterion_id)] = sc.level_id
    if request.method == "POST":
        if act.status == Activity.Status.CANCELED:
            messages.error(request, "Atividade cancelada: as avaliações ficam como estavam.")
            return redirect("pedagogy:activity_rubric_scores", pk=act.pk)
        valid_levels = {lv.pk for lv in levels}
        changed_students = set()
        with transaction.atomic():
            for st in students:
                for c in criteria:
                    raw = request.POST.get(f"r_{st.pk}_{c.pk}", "")
                    if not raw.isdigit() or int(raw) not in valid_levels:
                        continue  # vazio = sem avaliação; registro salvo é mantido
                    lv = int(raw)
                    if current.get((st.pk, c.pk)) == lv:
                        continue
                    RubricScore.objects.update_or_create(activity=act, student=st, criterion=c,
                                                         defaults={"level_id": lv, "updated_by": user})
                    changed_students.add(st)
            create_audit_log(user=user, action="update", request=request, target=act,
                             detail=f"Avaliou {len(changed_students)} estudante(s) com a rubrica {rubric.title}")
        if act.is_visible_to_family:
            from django.urls import reverse

            for st in changed_students:
                notify_family(st, "atividade_corrigida", f"Atividade corrigida: {act.title}",
                              body=f"A avaliação de {st.first_name} pela rubrica está disponível.",
                              url=reverse("pedagogy:activity_detail", args=[act.pk]),
                              dedupe_key=f"rubrica-{act.pk}-{st.pk}-{act.updated_at:%Y%m%d}")
        messages.success(request, f"Avaliação salva para {len(changed_students)} estudante(s).")
        return redirect("pedagogy:activity_rubric_scores", pk=act.pk)
    table = [{"student": st, "cells": [(c, current.get((st.pk, c.pk))) for c in criteria]} for st in students]
    return render(request, "pedagogy/rubric_scores.html", {
        "activity": act, "rubric": rubric, "levels": levels, "criteria": criteria, "table": table,
        "read_only": act.status == Activity.Status.CANCELED})


def family_rubric_rows(activity, student_ids):
    """Níveis atribuídos aos estudantes dados (só os próprios, para a família)."""
    out = {}
    for sc in RubricScore.objects.filter(activity=activity, student_id__in=student_ids).select_related(
            "criterion", "level"):
        out.setdefault(sc.student_id, []).append(sc)
    return out
