"""Validação retrospectiva dos indicadores precoces com os dados da própria escola.

Pergunta: quando os indicadores de ``trajectory.py`` acendem numa data, o estudante de fato termina os 60
dias seguintes com frequência abaixo de 75%, alguma disciplina abaixo da média ou desistência?

Por que validar localmente: revisando os indicadores de evasão de 30 anos de pesquisa, Bowers, Sprott &
Taff (2013, The High School Journal 96(2), 77–100) mostraram que a maioria sinaliza muitos estudantes que
não chegam ao desfecho e deixa de sinalizar muitos que chegam. Um indicador que funciona em Chicago ou
Baltimore não funciona por isso numa escola do DF.

Método:

- **Cortes:** a cada 60 dias desde o início de cada ano letivo, enquanto houver 60 dias de desfecho já
  observados. Na data de corte, os indicadores são recalculados SÓ com notas, frequência, entregas e
  ocorrências até ela, com a turma daquele momento (matrícula iniciada antes e não encerrada).
- **Desfecho (60 dias seguintes):** presença abaixo de 75% (com 5 ou mais registros), alguma disciplina
  abaixo da média de aprovação, ou matrícula encerrada como desistente. Quem foi transferido na janela
  fica de fora, porque o desfecho não é observável.
- **Métricas:** sensibilidade (dos que chegaram ao desfecho, quantos estavam sinalizados), precisão (dos
  sinalizados, quantos chegaram), especificidade e taxa base. Para o número de indicadores, a AUC (Bowers &
  Zhou, 2019, JESPAR 24(1), 20–46, doi:10.1080/10824669.2018.1523734): 0,5 é acaso, e acima de 0,8 é
  considerada boa nessa literatura.
- **Equidade:** as mesmas métricas por turma e por turno. Diferença grande de sensibilidade entre grupos
  significa que o indicador deixa de ver estudantes de um grupo (Gardner, Brooks & Baker, 2019, LAK,
  doi:10.1145/3303772.3303791; Baker & Hawn, 2022, IJAIED 32, 1052–1092, doi:10.1007/s40593-021-00285-9).
  A plataforma não guarda cor, renda nem gênero, então não faz esses recortes.

- **Limiares alternativos:** as mesmas métricas para outros cortes de frequência, entregas, ocorrências e
  número de disciplinas abaixo da média. O índice J de Youden (sensibilidade + especificidade − 1;
  Youden, 1950, Cancer 3(1), 32–35) indica o corte que melhor separa os grupos nos dados da escola. A
  escolha final é pedagógica: deixar de ver um estudante e chamar uma família sem necessidade têm custos
  diferentes. O limiar se ajusta na escala do EIA.

Limites declarados: o estado atual de uma entrega pode ter mudado depois do corte (entrega atrasada), e a
data em que a nota foi lançada não é guardada, só a da prova. Com dados de demonstração ou sintéticos, o
resultado não diz nada sobre estudantes reais. Sem ``MIN_N`` casos e ``MIN_POS`` desfechos, o resultado
fica em "dados insuficientes". Com eles, fica "experimental" até a direção aprovar o uso.
"""

import datetime
from collections import defaultdict

from django.utils import timezone

from .models import ModelRun
from .trajectory import INDICATORS, LEGAL_MIN, MIN_ATT_RECORDS, MIN_REGISTERED, auc, class_overview, thresholds_for

NAME, VERSION = "indicadores_precoces", "1.0"
STEP = HORIZON = 60
MIN_N, MIN_POS = 100, 20
BASE_RANGE = (0.03, 0.60)  # fora disso o desfecho é raro ou quase certo e a validação não distingue nada
MIN_SLICE = 10
ALTERNATIVES = {"attendance": [0.80, 0.85, 0.90, 0.95], "delivery": [0.50, 0.60, 0.70, 0.80],
                "occurrences": [1, 2, 3], "below": [1, 2]}


def _year_bounds(year, today):
    start = year.start_date or datetime.date(today.year, 2, 1)
    end = year.end_date or datetime.date(start.year, 12, 20)
    return start, end


def cutoffs_for(year, today):
    start, end = _year_bounds(year, today)
    last = min(end, today) - datetime.timedelta(days=HORIZON)
    out, d = [], start + datetime.timedelta(days=STEP)
    while d <= last:
        out.append(d)
        d += datetime.timedelta(days=STEP)
    return out


def _members(class_group, cutoff):
    """{estudante: matrícula} de quem estava na turma na data de corte."""
    from apps.registry.models import Enrollment

    out = {}
    for e in Enrollment.objects.filter(class_group=class_group):
        if (e.started_on is None or e.started_on <= cutoff) and (e.ended_on is None or e.ended_on > cutoff):
            out[e.student_id] = e
    return out


def _outcomes(class_group, members, cutoff, rules):
    """{estudante: True/False} para quem tem desfecho observável na janela."""
    from apps.analytics import bi

    end = cutoff + datetime.timedelta(days=HORIZON)
    first = cutoff + datetime.timedelta(days=1)
    ids = list(members)
    grades = bi.load_grades_light(ids, first, end, class_group=class_group)
    records = bi.load_attendance(ids, first, end, class_group=class_group)
    out = {}
    for sid, enr in members.items():
        left_in_window = enr.ended_on is not None and first <= enr.ended_on <= end
        if left_in_window and enr.status == "transferido":
            continue  # desfecho não observável
        dropped = left_in_window and enr.status == "desistente"
        rows = bi._subject_rows(grades.get(sid, []), rules)
        att = records.get(sid, [])
        low_att = len(att) >= 5 and sum(1 for _, s in att if s in bi.PRESENCE) / len(att) < LEGAL_MIN
        below = any(r["below"] for r in rows.values())
        if not (rows or len(att) >= 5 or dropped):
            continue  # sem nota, frequência nem desistência na janela: nada a comparar
        out[sid] = bool(dropped or low_att or below)
    return out


def collect(school, today=None):
    """Uma linha por estudante × data de corte: indicadores na data e desfecho depois."""
    from apps.academics.models import ClassGroup, SchoolYear
    from apps.analytics import bi

    today = today or timezone.localdate()
    rules = bi.school_rules(school)
    th = thresholds_for(school)
    rows = []
    for year in SchoolYear.objects.filter(school=school):
        start, _ = _year_bounds(year, today)
        for cutoff in cutoffs_for(year, today):
            for cg in ClassGroup.objects.filter(school=school, school_year=year):
                members = _members(cg, cutoff)
                if not members:
                    continue
                outcome = _outcomes(cg, members, cutoff, rules[0])
                if not outcome:
                    continue
                view = class_overview(cg, start, cutoff, today=cutoff, students=set(outcome), rules=rules,
                                      thresholds=th)
                for r in view["rows"]:
                    keys = [i["key"] for i in r["indicators"]]
                    att, d = r["attendance"], r["delivery"]
                    rows.append({"flags": keys, "count": len(keys), "y": outcome[r["student"].pk],
                                 "class": cg.name, "turn": cg.get_turn_display(), "cutoff": cutoff.isoformat(),
                                 "att": att["rate"], "att_n": att["records"], "deliv": d["rate"],
                                 "deliv_n": d["registered"], "occ": r["occurrences"] or 0,
                                 "below": sum(1 for s in r["subjects"].values() if s["below"])})
    return rows


def _confusion(rows, flagged):
    tp = sum(1 for r in rows if flagged(r) and r["y"])
    fp = sum(1 for r in rows if flagged(r) and not r["y"])
    fn = sum(1 for r in rows if not flagged(r) and r["y"])
    tn = len(rows) - tp - fp - fn
    div = lambda a, b: round(a / b, 3) if b else None
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "sensibilidade": div(tp, tp + fn), "precisao": div(tp, tp + fp),
            "especificidade": div(tn, tn + fp), "sinalizados": tp + fp}


def metrics(rows):
    pos = [r["count"] for r in rows if r["y"]]
    neg = [r["count"] for r in rows if not r["y"]]
    a = auc(pos, neg)
    out = {"n": len(rows), "positivos": len(pos), "taxa_base": round(len(pos) / len(rows), 3) if rows else None,
           "auc_contagem": round(a, 3) if a is not None else None,
           "pelo_menos_1": _confusion(rows, lambda r: r["count"] >= 1),
           "pelo_menos_2": _confusion(rows, lambda r: r["count"] >= 2),
           "por_indicador": {k: {"rotulo": label, **_confusion(rows, lambda r, k=k: k in r["flags"])}
                             for k, label in INDICATORS.items()}}
    return out


def threshold_table(rows, current):
    """Para cada indicador ajustável: métricas de cada limiar alternativo, o atual e o de maior J de Youden."""
    specs = {
        "frequencia": ("attendance", lambda v: f"presença abaixo de {round(v * 100)}%",
                       lambda r, v: r.get("att") is not None and r.get("att_n", 0) >= MIN_ATT_RECORDS and r["att"] < v),
        "entregas": ("delivery", lambda v: f"entregas abaixo de {round(v * 100)}%",
                     lambda r, v: r.get("deliv") is not None and r.get("deliv_n", 0) >= MIN_REGISTERED
                     and r["deliv"] < v),
        "comportamento": ("occurrences", lambda v: f"{v} ou mais ocorrências", lambda r, v: r.get("occ", 0) >= v),
        "desempenho": ("below", lambda v: f"{v} ou mais disciplinas abaixo da média",
                       lambda r, v: r.get("below", 0) >= v),
    }
    out = {}
    for key, (name, label, pred) in specs.items():
        cur = current.get(name, 1)
        lines = []
        for v in ALTERNATIVES[name]:
            c = _confusion(rows, lambda r, v=v, pred=pred: pred(r, v))
            j = (c["sensibilidade"] + c["especificidade"] - 1
                 if c["sensibilidade"] is not None and c["especificidade"] is not None else None)
            lines.append({"limiar": label(v), "atual": round(float(v), 3) == round(float(cur), 3), **c,
                          "youden": round(j, 3) if j is not None else None})
        scored = [ln for ln in lines if ln["youden"] is not None and ln["sinalizados"]]
        if scored:
            max(scored, key=lambda ln: ln["youden"])["maior_youden"] = True
        out[key] = {"rotulo": INDICATORS[key], "linhas": lines}
    return out


def slices(rows, key):
    groups = defaultdict(list)
    for r in rows:
        groups[r[key]].append(r)
    out = []
    for name, rs in sorted(groups.items()):
        pos = [r["count"] for r in rs if r["y"]]
        neg = [r["count"] for r in rs if not r["y"]]
        conf = _confusion(rs, lambda r: r["count"] >= 2)
        a = auc(pos, neg)
        out.append({"grupo": name, "n": len(rs), "positivos": len(pos),
                    "sensibilidade": conf["sensibilidade"] if len(pos) >= MIN_SLICE else None,
                    "auc": round(a, 3) if a is not None and len(pos) >= MIN_SLICE and len(neg) >= MIN_SLICE
                    else None})
    shown = [s["sensibilidade"] for s in out if s["sensibilidade"] is not None]
    return {"grupos": out, "maior_diferenca_sensibilidade": round(max(shown) - min(shown), 3) if len(shown) >= 2
            else None}


def run(school, user=None, today=None):
    rows = collect(school, today)
    m = metrics(rows)
    th = thresholds_for(school)
    m["limiares"] = threshold_table(rows, {**th, "below": 1})
    m["limiares_em_uso"] = {"frequencia": th["attendance"], "entregas": th["delivery"],
                            "comportamento": th["occurrences"]}
    base = m["taxa_base"]
    if base is not None and not BASE_RANGE[0] <= base <= BASE_RANGE[1]:
        m["aviso"] = (f"O desfecho adverso aconteceu em {round(base * 100)}% dos casos. Com uma taxa tão "
                      f"{'alta' if base > BASE_RANGE[1] else 'baixa'}, quase qualquer sinal parece preciso (ou "
                      "inútil); a validação não separa bons e maus indicadores e não pode ser aprovada. Confira os "
                      "critérios de aprovação e os lançamentos de notas.")
    status = (ModelRun.Status.INSUFFICIENT if m["n"] < MIN_N or m["positivos"] < MIN_POS or "aviso" in m
              else ModelRun.Status.EXPERIMENTAL)
    cutoffs = sorted({r["cutoff"] for r in rows})
    return ModelRun.objects.create(
        school=school, name=NAME, version=VERSION, n_train=0, n_test=m["n"], positives=m["positivos"],
        cutoff=datetime.date.fromisoformat(cutoffs[-1]) if cutoffs else None,
        metrics={**m, "por_turma": slices(rows, "class"), "por_turno": slices(rows, "turn"),
                 "cortes": cutoffs, "horizonte_dias": HORIZON},
        baseline={"taxa_base": m["taxa_base"]}, coefficients={"indicadores": list(INDICATORS)}, status=status,
        notes="Validação retrospectiva dos indicadores precoces. Com dados de demonstração ou sintéticos, não "
              "demonstra eficácia real.")


def latest_approved(school):
    return ModelRun.objects.filter(school=school, name=NAME, status=ModelRun.Status.APPROVED).first()
