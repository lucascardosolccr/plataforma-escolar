"""Inteligência prescritiva: recomendação de estratégias, trilhas e resultado das intervenções.

A recomendação é uma ordenação explicada (pontos por critério), nunca uma
prescrição: o professor aceita, edita, troca ou rejeita. O "resultado
posterior" compara evidências antes e depois do início da intervenção; é
associação no tempo, não prova de efeito. A comparação com colegas da mesma
turma (``comparison``) ajuda a ler o resultado, mas também não é causal: os
grupos não foram sorteados.
"""

import datetime
from collections import defaultdict

from django.db.models import Q
from django.utils import timezone

from .mastery import assess
from .models import InterventionStrategy, LearningIntervention, MasteryScale, SkillEvidence


def load_strategies(Strategy, Dimension):
    from .data.estrategias import ESTRATEGIAS

    n = 0
    for (comp, dim, errors, title, objective, proc, materials, minutes, follow, expected, level, refs) in ESTRATEGIAS:
        dimension = Dimension.objects.filter(component=comp, name=dim).first() if comp and dim else None
        _, new = Strategy.objects.update_or_create(
            school=None, title=title, defaults={
                "component": comp or "", "dimension": dimension, "error_types": errors, "objective": objective,
                "procedures": proc, "materials": materials, "minutes": minutes, "follow_up": follow,
                "expected_evidence": expected, "evidence_level": level, "references": refs, "active": True})
        n += new
    return n


def strategy_history(strategy, school):
    """Uso e resultado da estratégia na escola (contagem simples, sem inferência causal)."""
    return strategy_histories([strategy], school)[strategy.pk]


def strategy_histories(strategies, school):
    """``strategy_history`` de várias estratégias com uma consulta de intervenções (antes, uma por estratégia:
    29 no banco de estratégias). O custo que sobra é o das intervenções que existem, não o do catálogo."""
    out = {s.pk: {"uses": 0, "improved": 0, "unchanged": 0, "no_data": 0} for s in strategies}
    if not out:
        return out
    scale = MasteryScale.for_school(school)
    for iv in LearningIntervention.objects.filter(school=school, strategy_id__in=out).prefetch_related("students"):
        for r in outcomes(iv, scale):
            h = out[iv.strategy_id]
            h["uses"] += 1
            h[{"melhorou": "improved", "sem_evidencia": "no_data"}.get(r["result"], "unchanged")] += 1
    return out


def recommend(item, school, component="", error_types=(), students=(), limit=5, history=None):
    """Estratégias ordenadas para a habilidade, com as razões de cada uma. ``history`` (dicionário) guarda o
    histórico de cada estratégia entre chamadas seguidas, para não recalculá-lo a cada habilidade."""
    component = component or item.component
    dims = set(item.dimensions.values_list("pk", flat=True))
    qs = InterventionStrategy.objects.filter(Q(school__isnull=True) | Q(school=school), active=True).filter(
        Q(component=component) | Q(component="") | Q(component="Competências digitais", dimension__in=dims))
    used = {}
    if students:
        for iv in LearningIntervention.objects.filter(school=school, item=item, students__in=students).distinct():
            for r in outcomes(iv):
                if r["result"] != "melhorou" and iv.strategy_id:
                    used[iv.strategy_id] = r["result"]
    ranked = []
    strategies = list(qs.select_related("dimension"))
    history = {} if history is None else history
    history.update(strategy_histories([s for s in strategies if s.pk not in history], school))
    for s in strategies:
        score, reasons = 0, []
        if s.component == component:
            score += 3
            reasons.append(f"própria de {component}")
        elif not s.component:
            score += 1
            reasons.append("estratégia geral de avaliação formativa")
        if s.dimension_id and s.dimension_id in dims:
            score += 3
            reasons.append(f"trabalha a dimensão “{s.dimension.name}”, ligada a esta habilidade")
        errs = {e for e in s.error_types.split("|") if e}
        hit = errs & set(error_types)
        if hit:
            score += 2 * len(hit)
            reasons.append("responde ao tipo de erro registrado")
        if s.evidence_level == "pesquisa":
            score += 1
        if s.pk in used:
            score -= 3
            reasons.append("já usada com estes estudantes nesta habilidade sem melhora registrada")
        hist = history[s.pk]
        if hist["uses"] >= 3 and hist["improved"] / hist["uses"] >= 0.5:
            score += 1
            reasons.append(f"melhora registrada em {hist['improved']} de {hist['uses']} usos nesta escola")
        ranked.append((score, s, reasons, hist))
    ranked.sort(key=lambda t: (-t[0], t[1].title))
    return [{"strategy": s, "score": sc, "reasons": rs, "history": h} for sc, s, rs, h in ranked[:limit] if sc > 0]


def error_types_for(students, item):
    errs = SkillEvidence.objects.filter(student__in=students, item=item).exclude(error_type="") \
        .values_list("error_type", flat=True)
    return list(set(errs))


def build_trail(item, school, students, class_group, subject, scale=None):
    """Passos sugeridos: pré-requisitos com dificuldade ou sem evidência → habilidade → verificação."""
    from .graph import prerequisites
    from .mastery import group_evidence

    scale = scale or MasteryScale.for_school(school)
    steps = []
    grouped = group_evidence(SkillEvidence.objects.filter(student__in=students))
    for rel in prerequisites(item, school):
        weak = [st for st in students
                if assess(grouped.get((st.pk, rel.source_id), []), scale).state in ("dificuldade", "insuficiente",
                                                                                   "nao_avaliado", "contraditoria")]
        if weak:
            rec = recommend(rel.source, school, subject_name(subject), students=weak, limit=1)
            steps.append({"item": rel.source, "kind": "Retomar pré-requisito", "students": weak,
                          "strategy": rec[0]["strategy"] if rec else None,
                          "why": f"{rel.get_kind_display()} ({rel.get_status_display().lower()}): {rel.rationale[:160]}"})
    rec = recommend(item, school, subject_name(subject), error_types_for(students, item), students, limit=1)
    steps.append({"item": item, "kind": "Desenvolver a habilidade", "students": list(students),
                  "strategy": rec[0]["strategy"] if rec else None, "why": "Habilidade-alvo."})
    verify = InterventionStrategy.objects.filter(school__isnull=True,
                                                 title="Verificação curta com devolutiva imediata").first()
    steps.append({"item": item, "kind": "Verificar novamente", "students": list(students), "strategy": verify,
                  "why": "Registrar nova evidência para saber se a intervenção ajudou."})
    return steps


def subject_name(subject):
    from apps.curriculum.models import component_for

    return component_for(subject) if subject else ""


def outcomes(intervention, scale=None):
    """Para cada estudante: estado antes e depois do início e o resultado."""
    scale = scale or MasteryScale.for_school(intervention.school)
    out = []
    evs = list(SkillEvidence.objects.filter(item=intervention.item,
                                            student__in=intervention.students.all()).order_by("observed_on"))
    for st in intervention.students.all():
        mine = [e for e in evs if e.student_id == st.pk]
        before = assess([e for e in mine if e.observed_on < intervention.starts_on], scale,
                        today=intervention.starts_on - datetime.timedelta(days=1))
        after_ev = [e for e in mine if e.observed_on >= intervention.starts_on]
        after = assess(after_ev, scale) if after_ev else None
        if not after_ev or not [e for e in after_ev if e.ratio is not None]:
            result = "sem_evidencia"
        elif before.mean is None:
            result = "sem_comparacao"
        else:
            after_mean = sum(e.ratio for e in after_ev if e.ratio is not None) / len(
                [e for e in after_ev if e.ratio is not None])
            diff = after_mean - before.mean
            result = "melhorou" if diff >= 0.1 else "piorou" if diff <= -0.1 else "estavel"
        out.append({"student": st, "before": before, "after": after, "result": result,
                    "n_after": len([e for e in after_ev if e.ratio is not None]),
                    "next": NEXT_AFTER.get(result, "")})
    return out


# Prompt 18 §12: sem o resultado esperado, revisar antes de repetir a mesma atividade.
NEXT_AFTER = {
    "estavel": ("Sem mudança nas evidências: reveja a hipótese (o obstáculo é mesmo esta habilidade ou um "
                "pré-requisito dela?), a estratégia ou o instrumento de verificação, antes de repetir a mesma atividade."),
    "piorou": ("Resultados mais baixos depois do início: confira se a verificação mediu a mesma coisa e reveja a "
               "hipótese e a estratégia. Não repita a mesma atividade sem essa revisão."),
    "sem_evidencia": "Registre uma verificação curta depois da intervenção para saber se ela ajudou.",
}


MIN_GROUP = 3  # com menos estudantes, a média de um grupo depende de uma pessoa só
SIMILAR_START = 0.1


def _means(evs, start):
    before = [e.ratio for e in evs if e.observed_on < start and e.ratio is not None]
    after = [e.ratio for e in evs if e.observed_on >= start and e.ratio is not None]
    if not before or not after:
        return None
    return sum(before) / len(before), sum(after) / len(after)


def comparison(intervention):
    """Ganho médio dos participantes e de colegas da mesma turma com ponto de partida parecido.

    Comparação descritiva: colegas com evidência na mesma habilidade antes e depois do início, que
    não participaram e cuja média anterior está na faixa dos participantes (± 0,1). Só agregados,
    e só com pelo menos ``MIN_GROUP`` estudantes em cada grupo.
    """
    from apps.registry.models import Student

    start = intervention.starts_on
    part_ids = set(intervention.students.values_list("pk", flat=True))
    class_ids = set(Student.objects.filter(enrollments__class_group=intervention.class_group,
                                           enrollments__status="ativo").values_list("pk", flat=True))
    evs = defaultdict(list)
    for e in SkillEvidence.objects.filter(item=intervention.item, student__in=part_ids | class_ids):
        evs[e.student_id].append(e)
    part = [m for m in (_means(evs[s], start) for s in part_ids) if m]
    out = {"n_part": len(part), "n_comp": 0, "enough": False}
    if not part:
        return out
    low = min(b for b, _ in part) - SIMILAR_START
    high = max(b for b, _ in part) + SIMILAR_START
    comp = [m for m in (_means(evs[s], start) for s in class_ids - part_ids) if m and low <= m[0] <= high]
    out["n_comp"] = len(comp)
    if len(part) < MIN_GROUP or len(comp) < MIN_GROUP:
        return out
    gain = lambda rows: sum(a - b for b, a in rows) / len(rows)  # noqa: E731
    out.update({"enough": True, "gain_part": round(gain(part), 2), "gain_comp": round(gain(comp), 2),
                "difference": round(gain(part) - gain(comp), 2), "range": (round(max(low, 0), 2), round(min(high, 1), 2))})
    return out


RESULT_LABELS = {
    "melhorou": "Evidências posteriores melhores",
    "estavel": "Sem mudança relevante",
    "piorou": "Evidências posteriores mais baixas",
    "sem_evidencia": "Ainda sem evidência depois do início",
    "sem_comparacao": "Sem evidência anterior para comparar",
}


def due_reviews(school, today=None):
    today = today or timezone.localdate()
    return LearningIntervention.objects.filter(school=school, review_on__lte=today,
                                               status__in=["aceita", "andamento"])


def next_step(intervention, results=None):
    """Continuar, adaptar ou encerrar (Prompt 17, §10.2), pelas evidências posteriores ao início.

    Nunca considera a intervenção bem-sucedida só por estar registrada como concluída.
    """
    results = results if results is not None else outcomes(intervention)
    judged = [r for r in results if r["result"] in ("melhorou", "estavel", "piorou")]
    if not judged:
        return {"decision": "verificar", "label": "Verificar antes de decidir",
                "why": "Ainda não há evidência desta habilidade depois do início. Registre uma verificação curta "
                       "(questões ou observação) para saber se houve avanço."}
    improved = [r for r in judged if r["result"] == "melhorou"]
    consolidated = [r for r in improved if r["after"] and r["after"].state in ("consolidacao", "consolidada")]
    n = len(judged)
    if len(consolidated) == n:
        return {"decision": "encerrar", "label": "Encerrar e acompanhar",
                "why": f"Os {n} estudante(s) com evidência posterior chegaram a consolidação ou consolidada. "
                       "Acompanhe nas próximas atividades se o resultado se mantém."}
    if len(improved) * 2 >= n:
        return {"decision": "continuar", "label": "Continuar",
                "why": f"{len(improved)} de {n} estudante(s) melhoraram nas evidências posteriores, mas nem todos "
                       "consolidaram. Mantenha a estratégia e programe nova verificação."}
    return {"decision": "adaptar", "label": "Adaptar a estratégia",
            "why": f"Só {len(improved)} de {n} estudante(s) melhoraram nas evidências posteriores. Vale trocar a "
                   "estratégia ou verificar um pré-requisito antes de insistir."}
