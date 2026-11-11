"""Análise da prova depois da correção (Prompt 18 §10.10).

Responde, só com o que foi registrado por questão:

1. quais habilidades foram avaliadas;
2. quais foram demonstradas nesta prova;
3. quais continuam em desenvolvimento;
4. quais erros apareceram mais;
5. quais pré-requisitos merecem investigação;
6. quais conteúdos e materiais da preparação retomar;
7. quais estudantes precisam de apoio, individual ou em pequeno grupo;
8. quais estratégias testar.

Regras que evitam conclusões indevidas:

- **É o retrato desta prova, não o estado da habilidade.** O estado vem de todas as
  evidências (``mastery``/``gaps``); aqui só se diz "demonstrou nesta prova".
- **Habilidade medida por uma questão só não basta para concluir** (§10.10). A tela
  avisa e não sugere grupo de apoio com base nela.
- **Questão que quase ninguém acertou é revisada antes de virar conclusão sobre a
  turma**: pode ser enunciado ambíguo, conteúdo não trabalhado ou erro de correção.
- Ausente, "não aplicada" e sem registro não contam como erro. Em branco conta como
  zero, como no cálculo das evidências (``evidence._collect_class``).
- Os cortes são os da escala da escola (``MasteryScale``): abaixo de t1, "não
  demonstrou"; de t1 a t2, "demonstrou em parte"; a partir de t2, "demonstrou".
- Habilidade só secundária nas questões não é classificada: o peso dela na evidência
  também é menor.

Qualidade da prova (análise clássica de itens, ``quality``):

- **Discriminação** de cada questão: correlação entre a questão e o total das outras questões (item-total
  corrigida). Perto de zero, a questão não separa quem foi bem na prova de quem foi mal; negativa, quem foi bem
  errou mais, o que costuma ser gabarito trocado, enunciado ambíguo ou "pegadinha". Faixas convencionais dos
  manuais de análise de itens: 0,30 ou mais boa; 0,20 a 0,29 aceitável; abaixo de 0,20 revisar. São convenção,
  não lei: numa prova curta ou numa turma homogênea as correlações caem.
- **Consistência da prova:** alfa de Cronbach (Cronbach, 1951), lido como limite inferior da confiabilidade
  (Sijtsma, 2009), com o erro-padrão de medida em pontos de 0 a 10: a nota de um estudante, numa prova parecida,
  variaria tipicamente esse tanto para mais ou para menos.
- Só com ``MIN_ITEM_STUDENTS`` estudantes com resultado em todas as questões e ``MIN_ITEMS`` questões ou mais.
  Com menos, a correlação de cada questão é instável demais e a tela não mostra.
"""

from collections import Counter

from apps.curriculum.models import component_for

from . import graph
from .gaps import classify, item_states
from .models import MasteryScale, QuestionResponse
from .recommend import error_types_for, recommend
from .taxonomy import error_label

LEVELS = (  # rótulos curtos: a tela avisa que tudo se refere a esta prova
    ("demonstrou", "Demonstrou"),
    ("parcial", "Em parte"),
    ("nao_demonstrou", "Não demonstrou"),
    ("sem_registro", "Sem registro"),
)
REVIEW_FACILITY = 0.2  # média de acerto abaixo disto: revisar a questão antes de concluir
MIN_FOR_REVIEW = 5  # com poucos estudantes, a média de uma questão oscila demais
MIN_GROUP = 2  # pequeno grupo: pelo menos dois estudantes na mesma habilidade
MIN_ITEM_STUDENTS = 10  # análise de itens: estudantes com todas as questões
MIN_ITEMS = 3
LOW_DISCRIMINATION = 0.20
NEGATIVE_DISCRIMINATION = -0.10  # perto de zero é "não separa"; só abaixo disto é "separa ao contrário"


def _ratio(r, q):
    """Fração de acerto, ou None quando a resposta não conta (ausente, não aplicada)."""
    if r is None:
        return None
    if r.status == QuestionResponse.Status.BLANK:
        return 0.0
    if r.status == QuestionResponse.Status.ANSWERED and r.points is not None and q.max_points:
        return max(0.0, min(1.0, float(r.points / q.max_points)))
    return None


def _level(ratio, t1, t2):
    if ratio is None:
        return "sem_registro"
    if ratio < t1:
        return "nao_demonstrou"
    if ratio < t2:
        return "parcial"
    return "demonstrou"


def _item_quality(questions, students, responses, q_rows):
    from apps.core.stats import item_analysis

    complete = []
    for s in students:
        row = [_ratio(responses.get((q.pk, s.pk)), q) for q in questions]
        if all(x is not None for x in row):
            complete.append(row)
    if len(questions) < MIN_ITEMS or len(complete) < MIN_ITEM_STUDENTS:
        return {"enough": False, "complete": len(complete), "need_students": MIN_ITEM_STUDENTS,
                "need_items": MIN_ITEMS}
    res = item_analysis(complete)
    if res is None or res["alpha"] is None:
        return {"enough": False, "complete": len(complete), "need_students": MIN_ITEM_STUDENTS,
                "need_items": MIN_ITEMS, "constant": True}
    for row, it in zip(q_rows, res["items"]):
        r = it["r_rest"]
        row["discrimination"] = r
        row["disc_flag"] = (None if r is None else "negativa" if r < NEGATIVE_DISCRIMINATION
                            else "baixa" if r < LOW_DISCRIMINATION
                            else None)
        row["better_without"] = (it["alpha_without"] is not None and res["alpha"] is not None
                                 and it["alpha_without"] > res["alpha"] + 0.03)
    # Alfa negativo: as questões variam em sentidos opostos (quem vai bem numa vai mal noutra). Não é um piso de
    # confiabilidade e o erro-padrão de medida (DP·√(1 − α)) perde o sentido, então não é mostrado.
    negative = res["alpha"] < 0
    return {"enough": True, "complete": len(complete), "alpha": res["alpha"], "negative_alpha": negative,
            "sem10": res["sem"] * 10 if res["sem"] is not None and not negative else None,
            "flagged": [r for r in q_rows if r.get("disc_flag")]}


def analyze(ev, students, school):
    """Dicionário pronto para a tela. ``students``: os da turma na data da prova."""
    scale = MasteryScale.for_school(school)
    t1, t2 = float(scale.t1), float(scale.t2)
    component = component_for(ev.subject) or ev.subject.name
    questions = list(ev.questions.prefetch_related("questionskill_set__item"))
    responses = {(r.question_id, r.student_id): r
                 for r in QuestionResponse.objects.filter(question__in=questions)}
    by_id = {s.pk: s for s in students}

    # --- questões
    q_rows, all_errors = [], Counter()
    for q in questions:
        ratios, errors, absent = [], Counter(), 0
        for s in students:
            r = responses.get((q.pk, s.pk))
            x = _ratio(r, q)
            if x is None:
                absent += 1
                continue
            ratios.append(x)
            if r.error_type and x < 1:
                errors[r.error_type] += 1
        all_errors.update(errors)
        facility = sum(ratios) / len(ratios) if ratios else None
        q_rows.append({
            "q": q, "n": len(ratios), "absent": absent, "facility": facility,
            "low": sum(1 for x in ratios if x < t1),
            "errors": [(error_label(component, c), n) for c, n in errors.most_common(3)],
            "review": facility is not None and len(ratios) >= MIN_FOR_REVIEW and facility < REVIEW_FACILITY,
            "skills": [qs.item for qs in q.questionskill_set.all()],
        })

    # --- qualidade da prova (análise de itens)
    quality = _item_quality(questions, students, responses, q_rows)

    # --- habilidades
    skills = {}
    for q in questions:
        for qs in q.questionskill_set.all():
            sk = skills.setdefault(qs.item_id, {"item": qs.item, "main": [], "secondary": []})
            sk["main" if qs.role == "principal" else "secondary"].append(q)
    skill_rows, struggling_by_student = [], {}
    for sk in sorted(skills.values(), key=lambda s: s["item"].code):
        if not sk["main"]:
            skill_rows.append({**sk, "only_secondary": True})
            continue
        per_student = {}
        for s in students:
            vals = [x for q in sk["main"] if (x := _ratio(responses.get((q.pk, s.pk)), q)) is not None]
            per_student[s.pk] = _level(sum(vals) / len(vals) if vals else None, t1, t2)
        counts = Counter(per_student.values())
        not_dem = [by_id[i] for i, lv in per_student.items() if lv == "nao_demonstrou"]
        partial = [by_id[i] for i, lv in per_student.items() if lv == "parcial"]
        single = len(sk["main"]) == 1
        if not single:
            for st in not_dem:
                struggling_by_student.setdefault(st.pk, []).append(sk["item"])
        evaluated = len(students) - counts["sem_registro"]
        skill_rows.append({
            **sk, "only_secondary": False, "single": single,
            "counts": [(code, label, counts[code]) for code, label in LEVELS],
            "evaluated": evaluated, "not_dem": not_dem, "partial": partial,
            "group": not single and len(not_dem) >= MIN_GROUP,
            "needs_attention": evaluated and (len(not_dem) + len(partial)) / evaluated >= 0.25,
        })

    # --- pré-requisitos, estratégias e preparação para o que pede atenção
    history = {}
    for row in skill_rows:
        if row["only_secondary"] or not row["needs_attention"]:
            continue
        item, struggling = row["item"], row["not_dem"] + row["partial"]
        rels = list(graph.prerequisites(item, school))
        tallies = {rel.pk: Counter() for rel in rels}
        for st in struggling if rels else ():
            states = item_states(st, [rel.source for rel in rels], scale)  # 2 consultas por estudante
            for rel in rels:
                kind, _ = classify(states[rel.source_id], scale)
                tallies[rel.pk]["lacuna" if kind == "confirmada" else "sem_evidencia" if kind == "sem_evidencia"
                                else "ok" if kind is None else "a_verificar"] += 1
        row["prereqs"] = [{"rel": rel, "tally": tallies[rel.pk]} for rel in rels]
        row["strategies"] = recommend(item, school, component, error_types_for(struggling, item), struggling,
                                      limit=2, history=history)
    for row in skill_rows:
        row.setdefault("prereqs", [])
        row.setdefault("strategies", [])

    # --- tópicos e materiais da preparação ligados às habilidades que pedem retomada
    retake = []
    attention = {r["item"].pk for r in skill_rows if not r["only_secondary"] and r["needs_attention"]}
    if attention:
        from apps.study.models import ExamGuide

        for guide in ExamGuide.objects.filter(evaluation=ev).prefetch_related("topics__curriculum"):
            for t in guide.topics.all():
                hit = [c for c in t.curriculum.all() if c.pk in attention]
                if hit:
                    mats = list(t.materials.filter(removed_at__isnull=True).only("title", "kind"))
                    retake.append({"guide": guide, "topic": t, "skills": hit, "materials": mats})

    support = sorted(((by_id[sid], items) for sid, items in struggling_by_student.items() if len(items) >= 2),
                     key=lambda p: p[0].first_name)
    return {
        "questions": q_rows,
        "skills": skill_rows,
        "errors": [(error_label(component, c), n) for c, n in all_errors.most_common(5)],
        "retake": retake,
        "support": support,
        "has_results": any(r["n"] for r in q_rows),
        "quality": quality,
        "t1": t1, "t2": t2,
    }
