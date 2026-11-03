"""Assistente analítico do EIA-Cognitio (Prompt 17, §14), por regras, sem modelo de linguagem.

Custo zero e sem dependência nova: a pergunta é classificada por palavras-chave em uma das intenções
abaixo; o código da habilidade, o estudante e a turma vêm do texto ou dos campos escolhidos na tela.
Cada resposta é montada só com dados da plataforma (grafo, evidências, intervenções, banco de
estratégias) e traz as fontes e as limitações. Quando falta dado, a resposta diz o que falta e como
obter. Nunca inventa pré-requisito, resultado ou referência.

O acesso segue o EIA-Cognitio: só estudantes e turmas que a pessoa pode ver.
"""

import re
import unicodedata
from dataclasses import dataclass, field

from django.urls import reverse

from apps.curriculum.models import CurriculumItem, component_for

from . import access, gaps, graph
from .mastery import STATES

CODE = re.compile(r"\b(EF\d{2}[A-Z]{2}\d{2}|CMDF-[A-Z]{2,6}\d{2}-[OC]\d{3})\b", re.I)


def _plain(t):
    return "".join(c for c in unicodedata.normalize("NFD", (t or "").lower()) if unicodedata.category(c) != "Mn")


# (chave, rótulo, palavras que indicam a intenção). A ordem desempata: a primeira com mais acertos vence.
INTENTS = [
    ("depois_recuperacao", "O que mudou depois da recuperação", ["mudou depois", "depois da recuperacao",
                                                                "depois da intervencao", "apos a recuperacao",
                                                                "resultado da intervencao", "avancou depois",
                                                                "funcionou", "deu resultado", "melhorou depois"]),
    ("evidencias_coletar", "Que evidências coletar", ["que evidencias", "quais evidencias devo", "coletar",
                                                      "verificar se o estudante avancou", "verificar se avancou",
                                                      "como verificar", "como avaliar", "como saber se"]),
    ("nao_avaliadas", "Habilidades trabalhadas e ainda não avaliadas", ["habilidades ainda nao",
                                                                        "habilidades nao avaliadas",
                                                                        "nao foram avaliadas", "trabalhadas",
                                                                        "habilidades sem avaliacao",
                                                                        "trabalhei e nao avaliei"]),
    ("sem_evidencia", "Quem não tem evidências suficientes", ["sem evidencias suficientes", "nao possuem evidencias",
                                                              "sem evidencia", "evidencias suficientes para uma",
                                                              "nao foram avaliados", "ainda nao avaliad",
                                                              "nao foi avaliado", "falta avaliar"]),
    ("intervencao_semelhante", "Quem precisa de intervenção semelhante", ["intervencao semelhante",
                                                                          "intervencao parecida",
                                                                          "precisam de uma intervencao",
                                                                          "precisam de intervencao",
                                                                          "quais estudantes precisam"]),
    ("retomar", "O que retomar antes do próximo conteúdo", ["retomad", "retomar", "antes de iniciar",
                                                            "proximo conteudo", "antes do proximo",
                                                            "revisar antes", "rever antes"]),
    ("atividades", "Atividades que podem ajudar", ["atividades podem ajudar", "que atividade", "estrategia",
                                                   "o que fazer", "como ajudar", "atividades para", "como trabalhar",
                                                   "sugestao de atividade", "o que posso fazer"]),
    ("dependentes", "Competências posteriores", ["posteriores", "dependem", "depender", "depende dessa",
                                                 "competencias seguintes", "o que vem depois", "afetar",
                                                 "consequencia", "impacto", "proximas habilidades"]),
    ("evidencias_lacuna", "Por que ainda não consolidou", ["quais evidencias indicam", "evidencias indicam",
                                                           "nao consolidou", "por que", "ainda nao consolid"]),
    ("prerequisitos", "Pré-requisitos", ["pre-requisito", "pre requisito", "prerequisito", "precisa desenvolver",
                                         "para alcancar", "sustenta", "base para", "o que falta",
                                         "falta para", "precisa saber antes", "antes de aprender"]),
]

EXAMPLES = [
    "Quais pré-requisitos o aluno precisa desenvolver para alcançar EF06MA07?",
    "Quais evidências indicam que ele ainda não consolidou EF06MA07?",
    "Quais competências posteriores podem depender de EF05MA03?",
    "Quais estudantes da turma precisam de uma intervenção semelhante em EF06MA07?",
    "Quais habilidades devem ser retomadas antes de iniciar o próximo conteúdo?",
    "O que mudou depois da recuperação?",
    "Quais estudantes ainda não possuem evidências suficientes para uma conclusão em EF06MA07?",
    "Quais atividades podem ajudar a desenvolver EF06MA07?",
    "Que evidências devo coletar para verificar se o estudante avançou em EF06MA07?",
    "Quais habilidades já trabalhadas ainda não foram avaliadas?",
]


@dataclass
class Answer:
    intent: str = ""
    intent_label: str = ""
    title: str = ""
    paragraphs: list = field(default_factory=list)
    items: list = field(default_factory=list)  # (texto, url ou None)
    sources: list = field(default_factory=list)
    limits: list = field(default_factory=list)
    missing: str = ""
    maturity: str = "Nível 1 (regras curriculares e pedagógicas)"


def detect(question):
    q = _plain(question)
    best, score = None, 0
    for key, label, words in INTENTS:
        s = sum(1 for w in words if w in q)
        if s > score:
            best, score = (key, label), s
    return best


def _item(user, question):
    m = CODE.search(question or "")
    if not m:
        return None
    return CurriculumItem.objects.filter(CurriculumItem.visible_q(user.school), code=m.group(1).upper(),
                                         active=True).first()


def _student_from_text(user, question, candidates):
    q = _plain(question)
    for st in candidates:
        if _plain(st.full_name) in q:
            return st
    hits = [st for st in candidates if re.search(r"\b" + re.escape(_plain(st.first_name)) + r"\b", q)]
    return hits[0] if len(hits) == 1 else None


def visible_students(user, class_group=None):
    from apps.registry.models import Enrollment

    qs = Enrollment.objects.filter(student__school=user.school, status="ativo").select_related("student",
                                                                                                "class_group")
    if class_group is not None:
        qs = qs.filter(class_group=class_group)
    out, seen = [], set()
    for e in qs:
        if e.student_id in seen:
            continue
        subjects = access.student_subjects(user, e.student)
        if subjects is None or subjects:
            seen.add(e.student_id)
            out.append(e.student)
    return sorted(out, key=lambda s: s.full_name)


def _subject_for(user, class_group, item):
    from apps.academics.models import Subject, TeacherAssignment

    allowed = access.class_subjects(user, class_group)
    ids = set(TeacherAssignment.objects.filter(class_group=class_group).values_list("subject_id", flat=True))
    if allowed is not None:
        ids &= allowed
    subjects = list(Subject.objects.filter(pk__in=ids))
    if item:
        match = [s for s in subjects if component_for(s) == item.component]
        if match:
            return match[0]
    return subjects[0] if len(subjects) == 1 else None


def answer(user, question, student=None, class_group=None, item=None):
    det = detect(question)
    a = Answer()
    if det is None:
        a.title = "Não entendi a pergunta"
        a.paragraphs.append("Este assistente funciona por regras e entende perguntas parecidas com os exemplos abaixo. "
                            "Inclua o código da habilidade (por exemplo, EF06MA07) e escolha o estudante ou a turma.")
        return a
    a.intent, a.intent_label = det
    item = _item(user, question) or item
    if student is None:
        student = _student_from_text(user, question, visible_students(user, class_group))
    a.sources.append("Dados registrados na plataforma (evidências, grafo de pré-requisitos, intervenções).")
    handler = HANDLERS[a.intent]
    handler(user, a, item, student, class_group)
    return a


def _need(a, text):
    a.missing = text
    return a


def _skill_link(it):
    return reverse("cognitio:skill_graph", args=[it.pk])


def _h_prereqs(user, a, item, student, cg):
    if not item:
        return _need(a, "Informe o código da habilidade-alvo (por exemplo, EF06MA07).")
    a.title = f"Pré-requisitos de {item.code}"
    if student:
        g = gaps.gap_analysis(student, item, user.school)
        a.paragraphs.append(g["summary"])
        for r in g["rows"]:
            a.items.append((f"{r['item'].code} — {r['relation'].get_kind_display().lower()}: {r['state_label']}"
                            + (f"; {r['kind_label'].lower()}" if r["kind"] else "") + (f". {r['verify']}" if r["verify"]
                                                                                        else ""),
                            reverse("cognitio:student_projection", args=[student.pk]) + f"?habilidade={item.pk}"))
    else:
        rels = list(graph.prerequisites(item, user.school))
        a.paragraphs.append(f"{len(rels)} pré-requisito(s) documentado(s) no grafo. Escolha um estudante para ver o "
                            "que ele já demonstrou em cada um." if rels else
                            "Não há pré-requisitos documentados para esta habilidade no grafo desta escola.")
        for r in rels:
            a.items.append((f"{r.source.code} — {r.get_kind_display().lower()} ({r.get_status_display().lower()}): "
                            f"{r.rationale}", _skill_link(r.source)))
    a.sources.append(f"{item.code}: {item.source[:160]}")
    a.limits.append("Relações propostas automaticamente valem como hipótese até a equipe validar.")


def _h_evidence_gap(user, a, item, student, cg):
    from .views_projection import evidence_urls

    if not (item and student):
        return _need(a, "Informe o código da habilidade e escolha o estudante.")
    a.title = f"Evidências de {student.first_name} em {item.code}"
    st = gaps.item_state(student, item)
    kind, why = gaps.classify(st, gaps.MasteryScale.for_school(user.school))
    a.paragraphs.append(f"Estado: {STATES.get(st.effective, (st.effective,))[0]}. "
                        + (f"{gaps.GAP_KINDS[kind]}: {why}" if kind else why))
    last = st.evidence[-8:]
    for e, url in zip(last, evidence_urls(last)):
        a.items.append((f"{e.observed_on:%d/%m/%Y} · {e.get_source_type_display()}: {e.source_label}"
                        + (f" · {round(e.ratio * 100)}% de acerto" if e.ratio is not None else " · sem resposta (não "
                           "conta)"), url))
    if not st.evidence:
        a.limits.append("Sem evidência registrada: isso não indica que o estudante não sabe.")


def _h_dependents(user, a, item, student, cg):
    from .structure import forward

    if not item:
        return _need(a, "Informe o código da habilidade (por exemplo, EF05MA03).")
    a.title = f"O que pode depender de {item.code}"
    rows = gaps.propagation(student, item, user.school) if student else forward(item, user.school, depth=2)
    if not rows:
        a.paragraphs.append("Nenhuma habilidade posterior documentada no grafo.")
    for r in rows:
        extra = f"; {student.first_name}: {r['state_label'].lower()}" if student else ""
        a.items.append((f"{r['item'].code} — {r['nature']}; confiança {r.get('confidence_label', r.get('confidence'))}"
                        f", {r['distance']} passo(s){extra}", _skill_link(r["item"])))
    a.limits.append("Hipóteses pedagógicas: uma lacuna não impede necessariamente o que vem depois; nada é "
                    "multiplicado ao longo da cadeia.")


def _h_similar(user, a, item, student, cg):
    if not (item and cg):
        return _need(a, "Escolha a turma e informe o código da habilidade.")
    from .mastery import assess, group_evidence

    a.title = f"Quem pode se beneficiar da mesma intervenção em {item.code} — {cg.name}"
    studs = visible_students(user, cg)
    grouped = group_evidence(gaps.SkillEvidence.objects.filter(student__in=studs, item=item).order_by("observed_on"))
    scale = gaps.MasteryScale.for_school(user.school)
    weak = [s for s in studs if assess(grouped.get((s.pk, item.pk), []), scale).state in gaps.WEAK]
    a.paragraphs.append(f"{len(weak)} estudante(s) com dificuldade ou em desenvolvimento nas evidências de {item.code}."
                        if weak else f"Nenhum estudante com dificuldade sustentada por evidência em {item.code}.")
    for s in weak:
        a.items.append((s.full_name, reverse("cognitio:student_projection", args=[s.pk]) + f"?habilidade={item.pk}"))
    a.limits.append("Agrupamento para planejar, não classificação dos estudantes.")


def _h_retake(user, a, item, student, cg):
    if not cg:
        return _need(a, "Escolha a turma.")
    subject = _subject_for(user, cg, item)
    if subject is None:
        return _need(a, "Informe uma habilidade da disciplina (o código) para eu saber de qual disciplina se trata.")
    a.title = f"O que retomar antes das próximas habilidades — {cg.name}, {subject.name}"
    needs = gaps.class_prerequisite_needs(cg, subject, user.school, visible_students(user, cg))
    if not needs["targets"]:
        a.paragraphs.append("Não há atividades ou avaliações planejadas com habilidades ligadas nas próximas semanas.")
        a.limits.append("Ligue as habilidades ao criar atividades e avaliações para esta resposta funcionar.")
        return
    a.paragraphs.append("Próximas habilidades: " + ", ".join(t.code for t in needs["targets"]) + ".")
    for r in needs["rows"][:8]:
        a.items.append((f"{r['item'].code} sustenta {', '.join(t.code for t in r['targets'])}: {len(r['weak'])} ainda "
                        f"não consolidaram, {len(r['missing'])} sem evidência", _skill_link(r["item"])))


def _h_after(user, a, item, student, cg):
    from .models import LearningIntervention
    from .recommend import RESULT_LABELS, next_step, outcomes

    if not student:
        return _need(a, "Escolha o estudante.")
    a.title = f"O que mudou depois das intervenções — {student.first_name}"
    a.maturity = "Nível 5 (antes e depois, sem causalidade)"
    ivs = LearningIntervention.objects.filter(students=student).select_related("item").order_by("-starts_on")
    if item:
        ivs = ivs.filter(item=item)
    for iv in ivs[:6]:
        mine = [r for r in outcomes(iv) if r["student"].pk == student.pk]
        if mine:
            r = mine[0]
            text = (f"{iv.item.code} · {iv.title}: {RESULT_LABELS[r['result']]} (antes: {r['before'].label.lower()}"
                    + (f"; depois: {r['after'].label.lower()}" if r["after"] else "")
                    + f"). Recomendação: {next_step(iv)['label'].lower()}.")
            a.items.append((text, reverse("cognitio:intervention_detail", args=[iv.pk])))
    if not a.items:
        a.paragraphs.append("Não há intervenções registradas para este estudante"
                            + (f" em {item.code}." if item else "."))
    a.limits.append("Comparação antes e depois é associação no tempo, não prova de efeito.")


def _h_insufficient(user, a, item, student, cg):
    if not (item and cg):
        return _need(a, "Escolha a turma e informe o código da habilidade.")
    from .mastery import assess, group_evidence

    a.title = f"Sem evidências suficientes em {item.code} — {cg.name}"
    studs = visible_students(user, cg)
    grouped = group_evidence(gaps.SkillEvidence.objects.filter(student__in=studs, item=item).order_by("observed_on"))
    scale = gaps.MasteryScale.for_school(user.school)
    few = [s for s in studs if assess(grouped.get((s.pk, item.pk), []), scale).state in ("nao_avaliado",
                                                                                          "insuficiente")]
    a.paragraphs.append(f"{len(few)} de {len(studs)} estudante(s) ainda sem evidência suficiente (mínimo "
                        f"{scale.min_evidence}). Isso não indica que não sabem: faltam oportunidades de demonstrar.")
    for s in few:
        a.items.append((s.full_name, None))


def _h_activities(user, a, item, student, cg):
    from .recommend import recommend

    if not item:
        return _need(a, "Informe o código da habilidade.")
    a.title = f"Atividades e estratégias para {item.code}"
    recs = recommend(item, user.school, component=item.component, students=[student] if student else ())
    for r in recs:
        a.items.append((f"{r['strategy'].title}: {r['strategy'].objective[:160]} ({'; '.join(r['reasons'])})", None))
    if not recs:
        a.paragraphs.append("Nenhuma estratégia do banco se aplica a este componente.")
    a.sources.append("Banco de estratégias da plataforma, com o nível de evidência de cada uma.")


def _h_collect(user, a, item, student, cg):
    from .structure import expected_evidence

    if not item:
        return _need(a, "Informe o código da habilidade.")
    a.title = f"Evidências para verificar avanço em {item.code}"
    ev = expected_evidence(item)
    a.paragraphs.append("Colete uma evidência nova, em situação parecida com a dos critérios abaixo: 2 ou 3 questões "
                        "ligadas à habilidade numa avaliação curta, ou uma observação registrada.")
    for text, q in ev["criteria"]:
        a.items.append((f"Critério já usado: {text[:200]}", None))
    for d in ev["dimensions"]:
        a.items.append((f"Observe: {d.dimension.name} — {d.dimension.description}", None))
    if not ev["criteria"] and not ev["dimensions"]:
        a.limits.append("Ainda não há critérios escritos para esta habilidade; registre-os nas questões.")


def _h_not_evaluated(user, a, item, student, cg):
    from .views_dash import not_evaluated_for

    a.title = "Habilidades trabalhadas e ainda não avaliadas" + (f" — {cg.name}" if cg else "")
    found = not_evaluated_for(user, cg, limit=12)
    if not found["worked"]:
        a.paragraphs.append("Nenhum planejamento encerrado ou atividade já dada tem habilidades ligadas"
                            + (" nesta turma." if cg else " nas suas turmas."))
        a.missing = "Ligue as habilidades ao criar planejamentos e atividades para esta resposta funcionar."
    elif not found["rows"]:
        a.paragraphs.append("Tudo o que foi trabalhado (planejamentos encerrados e atividades já dadas) tem algum "
                            "registro" + (" nesta turma." if cg else " nas suas turmas."))
    else:
        a.paragraphs.append(f"{found['total']} habilidade(s) trabalhada(s) sem nenhum registro de evidência na turma e "
                            "disciplina" + (f"; aqui estão as {len(found['rows'])} mais recentes." if found["total"] >
                                            len(found["rows"]) else "."))
    for r in found["rows"]:
        a.items.append((f"{r['item'].code} · {r['cg'].name} · {r['subject'].name} · {r['origin']} de "
                        f"{r['when']:%d/%m}: registrar observação",
                        reverse("cognitio:observation_create", args=[r["cg"].pk, r["subject"].pk])
                        + f"?item={r['item'].pk}"))
    a.sources.append("Planejamentos e atividades com habilidades ligadas; evidências registradas.")
    a.limits.append("Sem registro não quer dizer que a turma não aprendeu: só que ainda não há evidência.")
    a.limits.append("Só entram planejamentos e atividades com habilidades ligadas.")


HANDLERS = {
    "nao_avaliadas": _h_not_evaluated,
    "prerequisitos": _h_prereqs, "evidencias_lacuna": _h_evidence_gap, "dependentes": _h_dependents,
    "intervencao_semelhante": _h_similar, "retomar": _h_retake, "depois_recuperacao": _h_after,
    "sem_evidencia": _h_insufficient, "atividades": _h_activities, "evidencias_coletar": _h_collect,
}
