"""Plano de preparação para a prova (Prompt 18 §10.7).

Regras, todas explícitas e auditáveis (não há modelo estatístico aqui):

1. **Fundamentos primeiro.** Se uma habilidade da prova está fraca
   ("dificuldade" ou "em desenvolvimento") e um pré-requisito dela tem lacuna
   *confirmada* ou dificuldade observada (``cognitio.gaps.classify``), o plano
   começa retomando esse pré-requisito. Pré-requisito com hipótese ou sem
   evidência vira um passo de *verificação curta*, não de retomada: ausência de
   registro não é ausência de conhecimento.
2. **Depois, os tópicos que mais precisam de estudo**: habilidade fraca, em
   seguida sem evidência suficiente, e por último o que já foi demonstrado
   (revisão rápida, para não repetir o que o estudante já domina).
3. **Desempate pela prioridade do professor** no tópico, nunca só pela nota
   mais baixa.
4. Cada passo diz por que está ali, o que estudar e como conferir.

Sem evidências para nenhuma habilidade da prova, o plano é o **plano geral**
(a ordem de prioridade do professor), dito assim na tela.

A família e o estudante só recebem a versão personalizada quando a escola
liga o compartilhamento do resumo de aprendizagens (``MasteryScale.share_with_family``),
e mesmo então em linguagem própria: sem "dificuldade", sem porcentagem,
sem comparação com colegas (a mesma regra de ``cognitio.views_family``).
"""

from apps.cognitio import gaps, graph
from apps.cognitio.mastery import STATES
from apps.cognitio.models import MasteryScale

from .models import ExamTopic

WEAK = gaps.WEAK
OK = gaps.OK
RETAKE = {"confirmada", "situacao"}      # pré-requisito a retomar
VERIFY = {"hipotese", "sem_evidencia", "conflitante", "reavaliar"}  # a verificar
# Tipos de relação (§6.1): só fundamento indispensável pode virar "retome antes".
FOUNDATION_KINDS = {"prerequisito", "conceitual"}
# Relações mais fracas (ajuda, hipótese, progressão, associação nos dados) no
# máximo pedem uma verificação; complementar, transversal e "mobiliza" não entram.
CHECK_ONLY_KINDS = {"facilitador", "hipotese", "progressao", "estatistica"}

FAMILY_WORDS = {
    "weak": "em desenvolvimento, com acompanhamento do professor",
    "none": "ainda sem registro suficiente",
    "ok": "já demonstrado nas atividades",
}


def _bucket(state):
    if state in WEAK or state in ("contraditoria", "reverificar"):
        return "weak"
    if state in OK:
        return "ok"
    return "none"


def _materials_for(guide, items, topic=None):
    ids = {it.pk for it in items}
    out = []
    for m in guide.active_materials:
        if (topic is not None and m.topic_id == topic.pk) or ids & {c.pk for c in m.curriculum.all()}:
            out.append(m)
    return out


def preparation_plan(guide, student, detailed=False, personalize=True):
    """Passos ordenados para este estudante.

    ``detailed`` (equipe) mostra os estados técnicos; sem ele, a linguagem é a
    da família. ``personalize=False`` dá o plano geral sem ler registro nenhum
    do estudante (escola sem compartilhamento com a família).
    Devolve {"personalized": bool, "steps": [...], "note": str}.
    """
    school = guide.school
    scale = MasteryScale.for_school(school)
    topics = list(guide.topics.prefetch_related("curriculum"))
    items = {it.pk: it for t in topics for it in t.curriculum.all()}
    states = gaps.item_states(student, list(items.values()), scale) if (items and personalize) else {}
    evaluated = any(a.effective not in ("nao_avaliado",) for a in states.values())

    if not evaluated:
        steps = [_topic_step(guide, t, None, detailed) for t in
                 sorted(topics, key=lambda t: (ExamTopic.PRIORITY_ORDER.get(t.priority, 9), t.order, t.pk))]
        return {"personalized": False, "steps": steps,
                "note": ("Plano geral: ainda não há registros das habilidades desta prova para este estudante. "
                         "A ordem segue a prioridade indicada pelo professor.")}

    steps, seen_prereq = [], set()
    # 1. Fundamentos: pré-requisitos das habilidades fracas.
    for it in items.values():
        a = states[it.pk]
        if a.effective not in WEAK:
            continue
        analysis = gaps.gap_analysis(student, it, school)
        for row in analysis["rows"]:
            pre = row["item"]
            if pre.pk in seen_prereq or pre.pk in items:
                continue
            rel_kind = row["relation"].kind
            if rel_kind not in FOUNDATION_KINDS | CHECK_ONLY_KINDS:
                continue
            # Relação fraca só conta se a escola a validou; senão cada progressão
            # proposta automaticamente viraria um passo "confira" sem fundamento.
            if rel_kind in CHECK_ONLY_KINDS and row["relation"].status != "validada":
                continue
            if row["kind"] in RETAKE or row["kind"] in VERIFY:
                seen_prereq.add(pre.pk)
                steps.append(_prereq_step(guide, it, row, detailed,
                                          retake=row["kind"] in RETAKE and rel_kind in FOUNDATION_KINDS))
    retakes = [s for s in steps if s["kind"] == "retomar"]
    checks = [s for s in steps if s["kind"] == "verificar"]

    # 2. Tópicos, do que mais precisa de estudo para o que já foi demonstrado.
    def topic_rank(t):
        own = [states[i.pk].effective for i in t.curriculum.all()]
        bucket = min((_bucket(s) for s in own), key=["weak", "none", "ok"].index) if own else "none"
        return (["weak", "none", "ok"].index(bucket), ExamTopic.PRIORITY_ORDER.get(t.priority, 9), t.order, t.pk)

    topic_steps = [_topic_step(guide, t, states, detailed) for t in sorted(topics, key=topic_rank)]
    return {"personalized": True, "steps": retakes + checks + topic_steps,
            "note": "Plano a partir dos registros do professor. O professor pode ajustar a ordem."}


def _prereq_step(guide, target, row, detailed, retake):
    pre = row["item"]
    rel = row["relation"]
    validated = rel.status == "validada"
    reason = (f"{pre.code} é base para {target.code}, cobrada na prova. "
              + (row["why"] if detailed else ("Os registros indicam que vale retomar antes."
                                              if retake else "Ainda não há registro suficiente sobre ela.")))
    if not validated:
        reason += " (Relação entre as habilidades ainda a confirmar pela escola.)"
    return {
        "kind": "retomar" if retake else "verificar",
        "title": ("Retome antes: " if retake else "Confira se você já sabe: ") + pre.text[:140],
        "code": pre.code,
        "reason": reason,
        "how": ("Estude o fundamento e faça um exercício curto antes de seguir." if retake
                else "Faça 2 ou 3 questões rápidas sobre isso; se tiver dúvida, leve ao professor."),
        "materials": _materials_for(guide, [pre]),
        "state": row["state_label"] if detailed else "",
        "topic": None,
    }


def _topic_step(guide, topic, states, detailed):
    own = list(topic.curriculum.all())
    state_txt = ""
    bucket = "none"
    if states is not None and own:
        effs = [states[i.pk].effective for i in own]
        bucket = min((_bucket(s) for s in effs), key=["weak", "none", "ok"].index)
        if detailed:
            state_txt = "; ".join(f"{i.code}: {STATES.get(states[i.pk].effective, ('?',))[0]}" for i in own)
        else:
            state_txt = FAMILY_WORDS[bucket]
    if states is None:
        reason = f"Prioridade {topic.get_priority_display().lower()} na prova."
    elif bucket == "weak":
        reason = "Este tópico pede mais estudo: os registros mostram que está em desenvolvimento."
    elif bucket == "ok":
        reason = "Já demonstrado nas atividades: uma revisão rápida basta."
    else:
        reason = "Ainda sem registro suficiente: estude e confira com exercícios."
    return {
        "kind": "revisar" if bucket == "ok" else "estudar",
        "title": topic.title,
        "code": ", ".join(i.code for i in own),
        "reason": reason,
        "how": "Marque como você está neste tópico depois de estudar.",
        "materials": _materials_for(guide, own, topic),
        "state": state_txt,
        "topic": topic,
    }


def class_skill_overview(guide, students):
    """Estados das habilidades da prova na turma: {item: {estado: n}} (equipe).

    Duas consultas para a turma inteira, sem nomes: só contagens.
    """
    from apps.cognitio.mastery import assess
    from apps.cognitio.models import SkillEvidence, SkillJudgment

    items = {}
    for t in guide.topics.prefetch_related("curriculum"):
        for it in t.curriculum.all():
            items[it.pk] = it
    if not items or not students:
        return []
    scale = MasteryScale.for_school(guide.school)
    sids = [s.pk for s in students]
    evs, judged = {}, {}
    for e in SkillEvidence.objects.filter(student_id__in=sids, item_id__in=items).order_by("observed_on"):
        evs.setdefault((e.student_id, e.item_id), []).append(e)
    for j in SkillJudgment.objects.filter(student_id__in=sids, item_id__in=items, active=True).order_by(
            "decided_on", "pk"):
        judged[(j.student_id, j.item_id)] = j
    rows = []
    for iid, it in items.items():
        counts = {}
        for sid in sids:
            a = gaps._with_judgment(assess(evs.get((sid, iid), []), scale), judged.get((sid, iid)))
            counts[a.effective] = counts.get(a.effective, 0) + 1
        rows.append({"item": it, "counts": [(STATES[k][0], counts[k]) for k in STATES if counts.get(k)],
                     "weak": sum(counts.get(k, 0) for k in WEAK),
                     "dependents": graph.dependents(it, guide.school).count()})
    return sorted(rows, key=lambda r: (-r["weak"], -r["dependents"], r["item"].code))
