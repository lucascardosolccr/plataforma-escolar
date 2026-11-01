"""Motor de lacunas, priorização, propagação e horizonte (Prompt 17, §7 e §8). Nível 1 de maturidade:
regras curriculares e pedagógicas explícitas sobre evidências registradas. Nenhuma probabilidade.

- ``classify``: tipo de lacuna de uma habilidade (§7.1), sempre com o fundamento.
- ``gap_analysis``: para uma habilidade-alvo, o estado de cada pré-requisito e um resumo em linguagem
  de hipótese ("recomenda-se verificar antes de concluir"), nunca categórico.
- ``priorities``: ordena as lacunas de um estudante por critérios explicados e trocáveis (§7.2).
- ``propagation``: percorre o grafo para a frente sem multiplicar probabilidades (§8.1). A confiança
  é a da relação mais fraca do caminho, rebaixada pela distância e por relação ainda não validada.
- ``horizon``: onde as habilidades afetadas aparecem nas atividades e avaliações planejadas (§8.3).
- ``scenarios``: cenários A/B/C condicionais e qualitativos (§8.2).

A decisão registrada pelo professor (``SkillJudgment``) prevalece sobre o estado calculado até surgir
evidência nova; a ausência de registro nunca é tratada como ausência de conhecimento.
"""

import datetime
from collections import OrderedDict

from django.utils import timezone

from . import graph
from .mastery import STATES, assess
from .models import LearningIntervention, MasteryScale, SkillEvidence

GAP_KINDS = OrderedDict([
    ("confirmada", "Lacuna confirmada por múltiplas evidências"),
    ("situacao", "Dificuldade observada em situação específica"),
    ("hipotese", "Hipótese de pré-requisito não consolidado"),
    ("sem_evidencia", "Ausência de evidências"),
    ("conflitante", "Evidências conflitantes"),
    ("superada", "Dificuldade aparentemente superada"),
    ("reavaliar", "Lacuna que precisa ser reavaliada"),
])
WEAK = {"dificuldade", "desenvolvimento"}
OK = {"consolidacao", "consolidada"}
CONF = ["baixa", "media", "alta"]
CONF_LABEL = {"baixa": "baixa", "media": "média", "alta": "alta"}
NATURE = {
    "prerequisito": "pré-requisito pedagógico: costuma ser mobilizado diretamente",
    "conceitual": "dependência conceitual: usa o mesmo conceito",
    "facilitador": "conhecimento facilitador: ajuda, mas não é indispensável",
    "complementar": "habilidade complementar: costuma ser trabalhada junto",
    "mobiliza": "a habilidade seguinte mobiliza esta",
    "transversal": "relação entre disciplinas",
    "progressao": "progressão curricular prevista (mesma unidade, ano seguinte)",
    "estatistica": "associação observada nos dados (não é causa)",
    "hipotese": "relação hipotética, aguardando validação",
}


def _judgment(student, item):
    from .models import SkillJudgment

    return SkillJudgment.objects.filter(student=student, item=item, active=True).order_by("-decided_on", "-pk").first()


def item_state(student, item, scale=None, today=None, evidences=None):
    """Estado da habilidade para o estudante, com a decisão do professor quando houver."""
    scale = scale or MasteryScale.for_school(student.school)
    today = today or timezone.localdate()
    evs = evidences if evidences is not None else list(
        SkillEvidence.objects.filter(student=student, item=item).order_by("observed_on"))
    a = assess(evs, scale, today=today)
    j = _judgment(student, item)
    a.judgment = j
    a.newer_evidence = bool(j and a.last_date and a.last_date > j.decided_on)
    a.effective = j.state if (j and not a.newer_evidence) else a.state
    if j and not a.newer_evidence:  # mesmo comportamento de mastery.apply_judgments: o estado exibido é o decidido
        a.computed_state, a.state = a.state, j.state
    return a


def classify(a, scale, today=None):
    """(tipo, fundamento) ou (None, motivo) quando não há lacuna."""
    today = today or timezone.localdate()
    state = getattr(a, "effective", a.state)
    j = getattr(a, "judgment", None)
    if j and not a.newer_evidence:
        if state in OK:
            return None, f"Decisão do professor em {j.decided_on:%d/%m/%Y}: {j.rationale}"
        if state == "reverificar":
            return "reavaliar", f"O professor pediu nova verificação em {j.decided_on:%d/%m/%Y}: {j.rationale}"
    if state in ("nao_avaliado", "insuficiente"):
        return "sem_evidencia", (f"{a.n_valid} registro(s) válido(s); são precisos pelo menos {scale.min_evidence}. "
                                 "Ausência de registro não quer dizer ausência de conhecimento.")
    if state == "contraditoria":
        return "conflitante", "Resultados muito diferentes entre si nas situações avaliadas."
    if state in OK:
        valid = [e for e in a.evidence if e.ratio is not None]
        if any(e.ratio < float(scale.t1) for e in valid[:-1]) and a.trend == "evolucao":
            return "superada", "Houve resultados baixos antes; os mais recentes são altos e consistentes."
        return None, "Evidências suficientes de domínio nas situações avaliadas."
    if a.stale and a.last_date:
        return "reavaliar", f"A última evidência é de {a.last_date:%d/%m/%Y} ({(today - a.last_date).days} dias)."
    if state in WEAK:
        valid = [e for e in a.evidence if e.ratio is not None]
        days = {e.observed_on for e in valid}
        kinds = {(e.source_type, e.source_label) for e in valid}  # situação = fonte + descrição do registro
        if state == "dificuldade" and len(days) >= 2 and len(kinds) >= 2:
            return "confirmada", (f"{len(valid)} evidências em {len(days)} datas e {len(kinds)} situações diferentes "
                                  "mostram dificuldade.")
        if state == "dificuldade":
            return "situacao", "A dificuldade aparece em uma situação só; vale observar em outra antes de concluir."
        return "hipotese", "Acertos parciais: ainda não consolidado nas situações avaliadas."
    return None, ""


VERIFY = {
    "sem_evidencia": "Proponha uma verificação curta desta habilidade (2 ou 3 questões ou uma observação).",
    "conflitante": "Verifique de novo em outra situação para entender a diferença entre os resultados.",
    "reavaliar": "Reavalie: a evidência é antiga e pode não refletir o momento atual.",
    "situacao": "Observe em outra situação (outro tipo de tarefa) antes de tratar como lacuna.",
    "hipotese": "Verifique este pré-requisito antes de concluir que ele é o obstáculo.",
    "confirmada": "Há base para planejar uma intervenção específica.",
    "superada": "Acompanhe: a melhora recente precisa se manter.",
}


def gap_analysis(student, target, school, subjects=None, today=None):
    today = today or timezone.localdate()
    scale = MasteryScale.for_school(school)
    target_state = item_state(student, target, scale, today)
    rows = []
    for rel in graph.prerequisites(target, school):
        a = item_state(student, rel.source, scale, today)
        kind, why = classify(a, scale, today)
        rows.append({"relation": rel, "item": rel.source, "a": a, "kind": kind, "kind_label": GAP_KINDS.get(kind, ""),
                     "why": why, "verify": VERIFY.get(kind, ""),
                     "state_label": ("Decisão do professor: " if a.judgment and not a.newer_evidence else "")
                     + STATES.get(a.effective, (a.effective,))[0] if a.effective in STATES else
                     "Decisão do professor: nova verificação",
                     "days": (today - a.last_date).days if a.last_date else None})
    ok = [r for r in rows if r["kind"] in (None, "superada")]
    open_ = [r for r in rows if r["kind"] not in (None, "superada")]
    if not rows:
        summary = (f"Não há pré-requisitos documentados para {target.code} no grafo desta escola. Cadastre ou valide "
                   "relações na estrutura da habilidade para que a análise funcione.")
    else:
        parts = [f"Para desenvolver {target.code}, o estudante apresenta evidências suficientes em {len(ok)} "
                 f"de {len(rows)} pré-requisito(s) identificado(s)."]
        for r in open_[:4]:
            parts.append(f"{r['item'].code}: {r['kind_label'].lower()}.")
        if open_:
            parts.append("Recomenda-se verificar essas aprendizagens antes de concluir que alguma delas constitui um "
                         "obstáculo.")
        summary = " ".join(parts)
    return {"target": target, "target_state": target_state, "rows": rows, "summary": summary,
            "n_ok": len(ok), "n_open": len(open_)}


# --------------------------------------------------------------------- priorização
CRITERIA = OrderedDict([
    ("prioridade", "Prioridade combinada (explicada)"),
    ("dependentes", "Mais habilidades dependentes"),
    ("persistencia", "Dificuldade mais persistente"),
    ("recencia", "Evidência mais recente"),
    ("proximas", "Aparece nas próximas atividades"),
])


def upcoming_items(student, today=None, days=30):
    """Habilidades ligadas a atividades e avaliações das turmas do estudante nos próximos dias."""
    from apps.pedagogy.models import Activity, Evaluation
    from apps.registry.models import Enrollment

    today = today or timezone.localdate()
    classes = Enrollment.objects.filter(student=student, status="ativo").values("class_group_id")
    end = today + datetime.timedelta(days=days)
    out = {}
    for ev in Evaluation.objects.filter(class_group_id__in=classes, date__gte=today, date__lte=end).prefetch_related(
            "curriculum"):
        for it in ev.curriculum.all():
            out.setdefault(it.pk, []).append(("avaliação", ev.title, ev.date))
    for act in Activity.objects.filter(class_group_id__in=classes, deadline__gte=today, deadline__lte=end) \
            .exclude(status="cancelada").prefetch_related("curriculum"):
        for it in act.curriculum.all():
            out.setdefault(it.pk, []).append(("atividade", act.title, act.deadline))
    return out


def priorities(student, school, subjects=None, order="prioridade", today=None):
    """Lacunas do estudante com a pontuação de cada critério à vista. Só para a equipe e por estudante:
    nunca vira classificação entre estudantes."""
    today = today or timezone.localdate()
    scale = MasteryScale.for_school(school)
    evs = SkillEvidence.objects.filter(student=student).select_related("item").order_by("observed_on")
    if subjects is not None:
        evs = evs.filter(subject_id__in=subjects)
    by_item = OrderedDict()
    for e in evs:
        by_item.setdefault(e.item_id, []).append(e)
    upcoming = upcoming_items(student, today)
    ivs = LearningIntervention.objects.filter(students=student)
    rows = []
    for item_evs in by_item.values():
        item = item_evs[0].item
        a = item_state(student, item, scale, today, item_evs)
        kind, why = classify(a, scale, today)
        if kind not in ("confirmada", "situacao", "reavaliar", "conflitante", "hipotese"):
            continue
        deps = list(graph.dependents(item, school))
        low = [e for e in item_evs if e.ratio is not None and e.ratio < float(scale.t2)]
        persist = (low[-1].observed_on - low[0].observed_on).days if len(low) >= 2 else 0
        recent = a.last_date and (today - a.last_date).days <= 30
        dep_ids = {d.target_id for d in deps}
        soon = upcoming.get(item.pk, []) + [u for d in dep_ids for u in upcoming.get(d, [])]
        my_ivs = [iv for iv in ivs if iv.item_id == item.pk]
        parts = []
        score = 0
        conf_pts = {"confirmada": 3, "situacao": 1, "hipotese": 1, "reavaliar": 0, "conflitante": 0}[kind]
        score += conf_pts
        parts.append((f"tipo de lacuna ({GAP_KINDS[kind].lower()})", conf_pts))
        dep_pts = min(len(deps), 3)
        score += dep_pts
        parts.append((f"{len(deps)} habilidade(s) dependente(s) no grafo", dep_pts))
        per_pts = 2 if persist >= 30 else 1 if persist >= 7 else 0
        score += per_pts
        parts.append((f"persistência de {persist} dia(s)", per_pts))
        rec_pts = 1 if recent else 0
        score += rec_pts
        parts.append(("evidência dos últimos 30 dias" if recent else "evidência antiga", rec_pts))
        soon_pts = 2 if soon else 0
        score += soon_pts
        parts.append((f"aparece em {len(soon)} atividade(s)/avaliação(ões) dos próximos 30 dias" if soon
                      else "não aparece nas próximas atividades", soon_pts))
        active_iv = [iv for iv in my_ivs if iv.status in ("aceita", "andamento")]
        iv_pts = -2 if active_iv else 0
        if iv_pts:
            parts.append(("já há intervenção em andamento", iv_pts))
        score += iv_pts
        rows.append({"item": item, "a": a, "kind": kind, "kind_label": GAP_KINDS[kind], "why": why, "score": score,
                     "parts": parts, "deps": len(deps), "persist": persist, "last": a.last_date, "soon": soon,
                     "interventions": my_ivs, "verify": VERIFY[kind]})
    key = {"prioridade": lambda r: (-r["score"], r["item"].code),
           "dependentes": lambda r: (-r["deps"], r["item"].code),
           "persistencia": lambda r: (-r["persist"], r["item"].code),
           "recencia": lambda r: (-(r["last"].toordinal() if r["last"] else 0), r["item"].code),
           "proximas": lambda r: (-len(r["soon"]), r["item"].code)}.get(order)
    rows.sort(key=key or (lambda r: (-r["score"], r["item"].code)))
    return rows


# --------------------------------------------------------------------- propagação
def _weaker(a, b):
    return a if CONF.index(a) <= CONF.index(b) else b


def propagation(student, item, school, depth=3, today=None):
    """Habilidades potencialmente afetadas, para a frente no grafo (busca em largura)."""
    from .recommend import recommend

    today = today or timezone.localdate()
    scale = MasteryScale.for_school(school)
    seen = {item.pk}
    frontier = [(item, [], "alta", True)]
    out = []
    for dist in range(1, depth + 1):
        nxt = []
        for node, path, conf, validated in frontier:
            for rel in graph.dependents(node, school):
                tgt = rel.target
                if tgt.pk in seen:
                    continue
                seen.add(tgt.pk)
                edge_conf = rel.confidence if rel.confidence in CONF else "baixa"
                c = _weaker(conf, edge_conf)
                all_valid = validated and rel.status == "validada"
                shown = c
                for _ in range(dist - 1):  # cada passo a mais rebaixa um nível
                    shown = CONF[max(CONF.index(shown) - 1, 0)]
                if not all_valid:
                    shown = "baixa"
                a = item_state(student, tgt, scale, today)
                if a.effective in OK:
                    impact = ("O estudante já demonstrou esta habilidade: a lacuna não parece impedir este avanço "
                              "(pode haver caminho alternativo ou compensação).")
                elif a.effective in WEAK or a.effective == "contraditoria":
                    impact = "A dificuldade já aparece também aqui: vale olhar as duas juntas."
                else:
                    impact = "Ainda sem evidência: observe quando esta habilidade for trabalhada."
                rec = recommend(tgt, school, component=tgt.component, limit=1)
                out.append({"item": tgt, "distance": dist, "relation": rel, "kind": rel.kind,
                            "nature": NATURE.get(rel.kind, rel.get_kind_display()), "path": path + [rel],
                            "a": a, "state_label": STATES.get(a.effective, (a.effective,))[0] if a.effective in STATES
                            else "Nova verificação pedida", "impact": impact,
                            "confidence": shown, "confidence_label": CONF_LABEL[shown], "validated": all_valid,
                            "needs_check": a.effective in ("nao_avaliado", "insuficiente"),
                            "strategy": rec[0] if rec else None})
                nxt.append((tgt, path + [rel], c, all_valid))
        frontier = nxt
    return out


def horizon(student, affected, today=None):
    """Onde a habilidade e as afetadas aparecem no planejamento: próximas 2 semanas, fim do bimestre
    (período do calendário que contém hoje) e fim do ano letivo."""
    from apps.school_calendar.models import CalendarPeriod
    from apps.school_calendar.services import current_year

    today = today or timezone.localdate()
    year = current_year(student.school)
    period = CalendarPeriod.objects.filter(school=student.school, start__lte=today, end__gte=today).first()
    windows = [("Próximas duas semanas", today + datetime.timedelta(days=14))]
    if period:
        windows.append((f"Até o fim do {period.name} ({period.end:%d/%m})", period.end))
    if year and year.end_date:
        windows.append((f"Até o fim do ano letivo ({year.end_date:%d/%m})", year.end_date))
    longest = max(d for _, d in windows)
    ups = upcoming_items(student, today, days=max((longest - today).days, 1))
    ids = {r["item"].pk: r["item"] for r in affected}
    out = []
    for label, end in windows:
        rows = []
        for pk, it in ids.items():
            for kind, title, when in ups.get(pk, []):
                if when and when <= end:
                    rows.append({"item": it, "kind": kind, "title": title, "date": when})
        out.append({"label": label, "rows": sorted(rows, key=lambda r: r["date"])})
    return out


def scenarios(student, item, school, affected):
    """Cenários condicionais (§8.2), qualitativos; números só com dados da própria escola."""
    from .recommend import outcomes

    monitor = [r for r in affected if not r["a"].effective in OK][:6]
    past = LearningIntervention.objects.filter(school=school, item=item).exclude(status="aceita")
    results = []
    for iv in past:
        results += [r["result"] for r in outcomes(iv)]
    judged = [r for r in results if r in ("melhorou", "estavel", "piorou")]
    b = None
    if len(judged) >= 5:
        b = {"n": len(judged), "improved": judged.count("melhorou")}
    return {
        "A": {"title": "Cenário A — lacuna não trabalhada",
              "text": "Se nada mudar, estas habilidades posteriores continuam exigindo o que ainda não foi "
                      "demonstrado e merecem acompanhamento quando forem trabalhadas. É uma hipótese pedagógica, "
                      "não uma previsão de fracasso.", "monitor": monitor},
        "B": {"title": "Cenário B — intervenção específica",
              "text": (f"Na escola, intervenções nesta habilidade tiveram {b['improved']} melhora(s) nas evidências "
                       f"posteriores em {b['n']} resultado(s) avaliado(s). Associação no tempo, não prova de efeito."
                       if b else "Ainda não há resultados suficientes de intervenções nesta habilidade na escola "
                       "(mínimo de 5) para estimar o que muda. A decisão continua sendo pedagógica."), "data": b},
        "C": {"title": "Cenário C — intervenção com reavaliação",
              "text": "Registre uma verificação curta depois da intervenção: o estado da habilidade e esta análise "
                      "são recalculados com a nova evidência."},
    }


# --------------------------------------------------------------------- turma
def class_prerequisite_needs(class_group, subject, school, students, today=None, days=45, items=None):
    """Pré-requisitos das habilidades planejadas para a turma e disciplina (atividades e avaliações dos
    próximos ``days`` dias) e, em cada um, quem ainda não demonstrou: base para retomada coletiva e para
    agrupar estudantes que podem se beneficiar da mesma intervenção (§13.1). Uma consulta de evidências
    para a turma toda; as decisões ativas dos professores prevalecem, como no mapa individual.

    Com ``items`` (por exemplo, as habilidades de um planejamento), usa essas habilidades como alvo."""
    from apps.pedagogy.models import Activity, Evaluation

    from .mastery import group_evidence
    from .models import SkillJudgment

    today = today or timezone.localdate()
    end = today + datetime.timedelta(days=days)
    targets = {it.pk: (it, today) for it in (items or [])}
    if items is None:
        evals = Evaluation.objects.filter(class_group=class_group, subject=subject, date__gte=today, date__lte=end)
        acts = Activity.objects.filter(class_group=class_group, subject=subject, deadline__gte=today,
                                       deadline__lte=end).exclude(status="cancelada")
    else:
        evals, acts = Evaluation.objects.none(), Activity.objects.none()
    for ev in evals.prefetch_related("curriculum"):
        for it in ev.curriculum.all():
            targets.setdefault(it.pk, (it, ev.date))
    for act in acts.prefetch_related("curriculum"):
        for it in act.curriculum.all():
            if it.pk not in targets or act.deadline < targets[it.pk][1]:
                targets[it.pk] = (it, act.deadline)
    if not targets:
        return {"targets": [], "rows": []}
    prereq_of = OrderedDict()
    for it, _when in sorted(targets.values(), key=lambda t: t[1]):
        for rel in graph.prerequisites(it, school):
            prereq_of.setdefault(rel.source_id, {"item": rel.source, "targets": [], "relations": []})
            prereq_of[rel.source_id]["targets"].append(it)
            prereq_of[rel.source_id]["relations"].append(rel)
    scale = MasteryScale.for_school(school)
    ids = [s.pk for s in students]
    grouped = group_evidence(SkillEvidence.objects.filter(student_id__in=ids, item_id__in=list(prereq_of))
                             .order_by("observed_on"))
    judged = {(j.student_id, j.item_id): j for j in SkillJudgment.objects.filter(
        student_id__in=ids, item_id__in=list(prereq_of), active=True).order_by("decided_on", "pk")}
    rows = []
    for pid, info in prereq_of.items():
        weak, missing, ok = [], [], []
        for st in students:
            a = assess(grouped.get((st.pk, pid), []), scale, today=today)
            j = judged.get((st.pk, pid))
            state = j.state if j and not (a.last_date and a.last_date > j.decided_on) else a.state
            if state in OK:
                ok.append(st)
            elif state in ("nao_avaliado", "insuficiente"):
                missing.append(st)
            else:
                weak.append(st)
        rows.append({"item": info["item"], "targets": info["targets"], "relations": info["relations"],
                     "weak": weak, "missing": missing, "ok": ok})
    rows.sort(key=lambda r: (-len(r["weak"]), -len(r["missing"]), r["item"].code))
    return {"targets": [t for t, _ in sorted(targets.values(), key=lambda t: t[1])], "rows": rows}
