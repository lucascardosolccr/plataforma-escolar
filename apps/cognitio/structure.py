"""Estrutura de uma aprendizagem (Prompt 17, §5): objetivo de chegada, conhecimentos anteriores,
evidências esperadas, critérios de domínio, dependências posteriores, consequências possíveis da lacuna,
intervenções e verificação posterior. Nível 1 de maturidade (regras curriculares e pedagógicas).

Tudo sai de dados da plataforma: texto oficial do item, relações do grafo (com tipo, fonte e validação),
critérios das questões já ligadas à habilidade, dimensões observáveis, banco de estratégias e a escala
de domínio da escola. Onde não há dado, a página diz que não há.
"""

from collections import OrderedDict

from apps.curriculum.models import ItemDimension

from . import graph
from .gaps import CONF, CONF_LABEL, NATURE
from .mastery import STATES
from .models import MasteryScale, QuestionSkill


def forward(item, school, depth=2):
    """Dependentes até ``depth`` passos, com a confiança mais fraca do caminho rebaixada pela distância."""
    seen, frontier, out = {item.pk}, [(item, "alta", True)], []
    for dist in range(1, depth + 1):
        nxt = []
        for node, conf, validated in frontier:
            for rel in graph.dependents(node, school):
                if rel.target_id in seen:
                    continue
                seen.add(rel.target_id)
                c = rel.confidence if rel.confidence in CONF else "baixa"
                c = c if CONF.index(c) <= CONF.index(conf) else conf
                shown = CONF[max(CONF.index(c) - (dist - 1), 0)]
                ok = validated and rel.status == "validada"
                if not ok:
                    shown = "baixa"
                out.append({"relation": rel, "item": rel.target, "distance": dist, "via": node,
                            "nature": NATURE.get(rel.kind, rel.get_kind_display()), "confidence": CONF_LABEL[shown],
                            "validated": ok})
                nxt.append((rel.target, c, ok))
        frontier = nxt
    return out


def expected_evidence(item):
    """Critérios e indicadores já escritos pelos professores nas questões desta habilidade."""
    links = (QuestionSkill.objects.filter(item=item).select_related("question__evaluation")
             .order_by("-question__evaluation__date")[:40])
    criteria = OrderedDict()
    for qs in links:
        q = qs.question
        if q.criteria.strip():
            criteria.setdefault(q.criteria.strip(), q)
    dims = ItemDimension.objects.filter(item=item).select_related("dimension").order_by("-validated")
    return {"criteria": list(criteria.items())[:6], "n_questions": len(links), "dimensions": list(dims),
            "operational": item.operational_note}


def mastery_criteria(school):
    scale = MasteryScale.for_school(school)
    rows = [(k, v[0], v[2]) for k, v in STATES.items()]
    return {"scale": scale, "states": rows}


def structure(item, school):
    from .recommend import recommend

    prereqs = list(graph.prerequisites(item, school).prefetch_related("changes"))
    ahead = forward(item, school, depth=2)
    return {
        "prereqs": prereqs,
        "ahead": ahead,
        "consequences": [r for r in ahead],
        "evidence": expected_evidence(item),
        "criteria": mastery_criteria(school),
        "interventions": recommend(item, school, component=item.component, limit=3),
    }
