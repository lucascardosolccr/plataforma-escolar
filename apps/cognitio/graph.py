"""Grafo de pré-requisitos entre habilidades.

Geração automática (``build_progressions``), transparente e conservadora:
liga uma habilidade do ano N a uma do ano N+1 do mesmo componente e da mesma
unidade temática quando o texto oficial das duas compartilha vocabulário de
conteúdo (similaridade de Jaccard ≥ 0,20, no máximo 2 pré-requisitos por
habilidade). Toda ligação nasce "proposta", com a justificativa e as palavras
em comum, e só vale como hipótese até um profissional validar.

Isso é progressão curricular inferida do texto, não prova de dependência
cognitiva. Associações estatísticas são calculadas à parte, só com dados
suficientes, e não indicam causalidade.
"""

import re
import unicodedata
from collections import defaultdict

from django.db.models import Q

from apps.core.fmt import dec

STOP = set("""a o e é de da do das dos em no na nos nas um uma uns umas para por com sem como que se ao aos à às
ou seu sua seus suas entre sobre até mais menos outros outras outro outra diferentes diferente diversos diversas
partir meio meios modo forma formas uso usar utilizar utilizando base bem ser ter isso esta este estes estas
esse essa esses essas também já não sim entre ainda quando onde qual quais cada mesmo mesma tipos tipo tais tal
identificar reconhecer compreender analisar descrever relacionar comparar explicar produzir elaborar resolver
planejar ler escrever apresentar utilizar construir discutir propor selecionar organizar registrar
estabelecer observar investigar valorizar participar experimentar fruir conhecer""".split())


def _norm(t):
    t = "".join(c for c in unicodedata.normalize("NFD", (t or "").lower()) if unicodedata.category(c) != "Mn")
    return re.findall(r"[a-z]{4,}", t)


def _stem(w):
    for suf in ("mente", "coes", "cao", "oes", "ais", "eis", "res", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


def content_words(text):
    return {_stem(w) for w in _norm(text) if w not in STOP}


PROGRESSION_SOURCE = ("BNCC (MEC, 2018): mesma unidade temática no ano seguinte; proposta automática por semelhança "
                      "do texto oficial, a validar pela equipe")


def build_progressions(CurriculumItem, SkillRelation, threshold=0.20, per_target=2):
    """Cria relações propostas de progressão curricular. Idempotente; não toca nas
    relações já validadas ou rejeitadas. Devolve quantas criou."""
    has_source = "reference" in {f.name for f in SkillRelation._meta.get_fields()}
    skills = list(CurriculumItem.objects.filter(school__isnull=True, kind="habilidade", active=True)
                  .exclude(thematic_unit=""))
    by_key = defaultdict(list)
    for s in skills:
        years = [int(y) for y in s.years.split(",") if y.strip().isdigit()]
        if len(years) == 1:  # habilidades de vários anos não definem "ano seguinte"
            by_key[(s.component, s.thematic_unit, years[0])].append(s)
    words = {s.pk: content_words(s.text + " " + (s.knowledge_object or "")) for s in skills}
    created = 0
    for (comp, unit, year), targets in by_key.items():
        sources = by_key.get((comp, unit, year - 1), [])
        if not sources:
            continue
        for t in targets:
            scored = []
            for s in sources:
                a, b = words[s.pk], words[t.pk]
                if not a or not b:
                    continue
                inter = a & b
                sim = len(inter) / len(a | b)
                if sim >= threshold:
                    scored.append((sim, s, inter))
            for sim, s, inter in sorted(scored, key=lambda x: -x[0])[:per_target]:
                common = ", ".join(sorted(inter)[:6])
                _, new = SkillRelation.objects.get_or_create(
                    school=None, source=s, target=t,
                    defaults={"kind": "progressao", "confidence": "media" if sim >= 0.35 else "baixa",
                              "status": "proposta", "origin": "automatica",
                              "rationale": f"Mesma unidade temática ({unit}), ano seguinte; similaridade "
                                           f"{dec(sim)}; termos em comum: {common}.",
                              # campos do Prompt 17; as migrações antigas usam o modelo sem eles
                              **({"reference": PROGRESSION_SOURCE, "stage_year": f"{s.years}º → {t.years}º ano"[:40]}
                                 if has_source else {})})
                created += new
    return created


def _visible(qs, school):
    """Relações nacionais e da escola. A decisão local (validar ou rejeitar) substitui
    a proposta nacional do mesmo par; rejeitadas não aparecem."""
    from django.db.models import Exists, OuterRef

    from .models import SkillRelation

    local = SkillRelation.objects.filter(school=school, source=OuterRef("source"), target=OuterRef("target"))
    return (qs.filter(Q(school__isnull=True) | Q(school=school))
            .exclude(Q(school__isnull=True) & Q(Exists(local)))
            .exclude(status="rejeitada"))


def prerequisites(item, school):
    from .models import SkillRelation

    return _visible(SkillRelation.objects.filter(target=item), school).select_related("source")


def dependents(item, school):
    from .models import SkillRelation

    return _visible(SkillRelation.objects.filter(source=item), school).select_related("target")


def chain(item, school, depth=2):
    """Cadeia de pré-requisitos (até ``depth`` níveis) e dependentes diretos."""
    levels, seen, frontier = [], {item.pk}, [item]
    for _ in range(depth):
        nxt = []
        for it in frontier:
            for rel in prerequisites(it, school):
                if rel.source_id not in seen:
                    seen.add(rel.source_id)
                    nxt.append(rel.source)
                    levels.append((rel, it))
        frontier = nxt
    return levels


def association(source, target, school, min_n=20):
    """Associação observada entre dificuldade no pré-requisito e na dependente.

    Devolve None se houver menos de ``min_n`` estudantes com as duas habilidades
    avaliadas. Não é causalidade.
    """
    from .mastery import assess, group_evidence
    from .models import MasteryScale, SkillEvidence

    scale = MasteryScale.for_school(school)
    evs = group_evidence(SkillEvidence.objects.filter(school=school, item__in=[source, target]))
    students = {sid for sid, _ in evs}
    pairs = []
    for sid in students:
        a = assess(evs.get((sid, source.pk), []), scale)
        b = assess(evs.get((sid, target.pk), []), scale)
        if a.level >= 2 and b.level >= 2:  # ambas com conclusão
            pairs.append((a.state == "dificuldade", b.state == "dificuldade"))
    if len(pairs) < min_n:
        return {"n": len(pairs), "enough": False}
    with_a = [b for a, b in pairs if a]
    without_a = [b for a, b in pairs if not a]
    p1 = sum(with_a) / len(with_a) if with_a else None
    p0 = sum(without_a) / len(without_a) if without_a else None
    return {"n": len(pairs), "enough": True, "p_with": p1, "p_without": p0,
            "n_with": len(with_a), "n_without": len(without_a)}
