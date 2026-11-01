"""Bayesian Knowledge Tracing (Corbett & Anderson, 1995) — Nível 3 de maturidade, experimental.

Pergunta: dada a sequência de evidências de um estudante numa habilidade, qual a probabilidade de a
próxima evidência ser um acerto?

Por que BKT: as evidências já são sequências no tempo por estudante e habilidade, e o BKT tem quatro
parâmetros com sentido pedagógico (conhecimento inicial, aprendizagem entre oportunidades, acerto por
chute, erro por descuido). É mais simples e interpretável que modelos profundos de knowledge tracing,
que exigiriam muito mais dados do que uma escola produz.

Método (puro Python):
- acerto = proporção de acerto da evidência ≥ ``CORRECT`` (0,6); evidências sem resposta (ausência,
  não entrega) ficam fora, porque não dizem nada sobre o conhecimento;
- parâmetros por habilidade com pelo menos ``MIN_ITEM_OBS`` observações de treino; as demais usam os
  parâmetros do conjunto (agrupados), estimados com todas as sequências de treino;
- ajuste por máxima verossimilhança em grade, com chute e descuido abaixo de 0,3 (evita soluções
  degeneradas, em que "saber" passa a significar errar);
- validação TEMPORAL: o corte é a data que deixa 70% das observações no treino; cada observação de
  teste é prevista só com as anteriores (inclusive as de treino da mesma sequência);
- comparação com a taxa base do treino e com "repetir o último resultado";
- métricas: AUC, Brier, log-loss, acurácia e calibração.

Sem dados suficientes (``MIN_OBS``, ``MIN_TEST``, ``MIN_SEQ``) o modelo fica em modo exploratório.
Com dados suficientes, fica "experimental" até a aprovação humana registrada. ``synthetic_check`` só
confere que o código recupera parâmetros conhecidos; não diz nada sobre estudantes reais.
"""

import math
import random
from collections import defaultdict

from .models import ModelRun, SkillEvidence
from .predictive import metrics

NAME = "bkt_proximo_acerto"
VERSION = "1.0"
CORRECT = 0.6
MIN_OBS, MIN_TEST, MIN_SEQ, MIN_ITEM_OBS = 300, 80, 40, 40
GRID = {
    "l0": [0.1, 0.2, 0.35, 0.5, 0.65],
    "t": [0.02, 0.05, 0.1, 0.2, 0.3],
    "g": [0.05, 0.1, 0.2, 0.28],
    "s": [0.05, 0.1, 0.2, 0.28],
}


def predict_sequence(obs, p):
    """Probabilidade de acerto antes de cada observação (lista de 0/1), dados os parâmetros."""
    know = p["l0"]
    out = []
    for o in obs:
        p_correct = know * (1 - p["s"]) + (1 - know) * p["g"]
        out.append(p_correct)
        if o:
            post = know * (1 - p["s"]) / p_correct if p_correct else know
        else:
            denom = know * p["s"] + (1 - know) * (1 - p["g"])
            post = know * p["s"] / denom if denom else know
        know = post + (1 - post) * p["t"]
    return out


def loglik(seqs, p):
    ll = 0.0
    for obs in seqs:
        for o, pr in zip(obs, predict_sequence(obs, p)):
            pr = min(max(pr, 1e-6), 1 - 1e-6)
            ll += math.log(pr if o else 1 - pr)
    return ll


def fit(seqs):
    best, best_ll = None, -math.inf
    for l0 in GRID["l0"]:
        for t in GRID["t"]:
            for g in GRID["g"]:
                for s in GRID["s"]:
                    p = {"l0": l0, "t": t, "g": g, "s": s}
                    ll = loglik(seqs, p)
                    if ll > best_ll:
                        best, best_ll = p, ll
    return best


def sequences(school):
    """{(estudante, habilidade): [(data, acerto)]} em ordem temporal."""
    seqs = defaultdict(list)
    qs = (SkillEvidence.objects.filter(school=school, ratio__isnull=False, weight__gt=0)
          .order_by("observed_on", "pk").values_list("student_id", "item_id", "observed_on", "ratio"))
    for sid, iid, day, ratio in qs:
        seqs[(sid, iid)].append((day, 1 if ratio >= CORRECT else 0))
    return seqs


def train_and_validate(school, user=None):
    seqs = sequences(school)
    allobs = sorted(d for s in seqs.values() for d, _ in s)
    run = ModelRun(school=school, name=NAME, version=VERSION)
    n = len(allobs)
    if n < MIN_OBS or len(seqs) < MIN_SEQ:
        run.status = ModelRun.Status.INSUFFICIENT
        run.n_train = n
        run.notes = (f"{n} observações em {len(seqs)} sequências estudante-habilidade. São necessárias pelo menos "
                     f"{MIN_OBS} observações e {MIN_SEQ} sequências para treinar e testar com corte temporal. "
                     "Nenhuma probabilidade é mostrada aos professores.")
        run.save()
        return run
    cutoff = allobs[int(n * 0.7)]
    train_by_item, train_all = defaultdict(list), []
    for (sid, iid), s in seqs.items():
        tr = [o for d, o in s if d < cutoff]
        if tr:
            train_by_item[iid].append(tr)
            train_all.append(tr)
    pooled = fit(train_all)
    params = {iid: fit(ss) for iid, ss in train_by_item.items() if sum(len(x) for x in ss) >= MIN_ITEM_OBS}
    y, scores, base_last = [], [], []
    for (sid, iid), s in seqs.items():
        obs = [o for _, o in s]
        preds = predict_sequence(obs, params.get(iid, pooled))
        for k, (d, o) in enumerate(s):
            if d >= cutoff:
                y.append(o)
                scores.append(preds[k])
                base_last.append(float(obs[k - 1]) if k else None)
    run.cutoff = cutoff
    run.n_train, run.n_test = n - len(y), len(y)
    run.positives = sum(y)
    if len(y) < MIN_TEST or len(set(y)) < 2:
        run.status = ModelRun.Status.INSUFFICIENT
        run.notes = (f"Teste com {len(y)} observações depois de {cutoff:%d/%m/%Y}; são necessárias {MIN_TEST}, com "
                     "acertos e erros. Modo exploratório.")
        run.save()
        return run
    rate = sum(o for s in train_all for o in s) / max(sum(len(s) for s in train_all), 1)
    last = [b if b is not None else rate for b in base_last]
    run.metrics = metrics(y, scores)
    run.metrics["log_loss"] = -sum(math.log(min(max(p if o else 1 - p, 1e-6), 1)) for o, p in zip(y, scores)) / len(y)
    run.baseline = {"taxa_base": metrics(y, [rate] * len(y)), "ultimo_resultado": metrics(y, last)}
    run.coefficients = {"agrupado": pooled, "por_habilidade": {str(k): v for k, v in params.items()},
                        "acerto_minimo": CORRECT}
    auc, auc_last = run.metrics.get("auc") or 0, run.baseline["ultimo_resultado"].get("auc") or 0.5
    run.status = ModelRun.Status.EXPERIMENTAL
    run.notes = ("Validado tecnicamente com corte temporal. "
                 + ("Superou 'repetir o último resultado' em AUC. " if auc > auc_last else
                    "NÃO superou 'repetir o último resultado' em AUC: não usar. ")
                 + "Uso só depois de aprovação pedagógica registrada.")
    run.save()
    return run


def synthetic_check(n_students=300, length=8, seed=11, true=None):
    """Gera sequências SINTÉTICAS com parâmetros conhecidos e confere se o ajuste os recupera."""
    true = true or {"l0": 0.2, "t": 0.2, "g": 0.2, "s": 0.1}
    rnd = random.Random(seed)
    seqs = []
    for _ in range(n_students):
        know = rnd.random() < true["l0"]
        obs = []
        for _ in range(length):
            p = (1 - true["s"]) if know else true["g"]
            obs.append(1 if rnd.random() < p else 0)
            if not know and rnd.random() < true["t"]:
                know = True
        seqs.append(obs)
    return {"true": true, "fitted": fit(seqs)}


def active_run(school):
    return ModelRun.objects.filter(school=school, name=NAME, status=ModelRun.Status.APPROVED).first()


def estimate(run, student, item):
    """Probabilidade de acerto na próxima evidência, só com um modelo aprovado. ``None`` sem modelo."""
    if run is None:
        return None
    p = run.coefficients.get("por_habilidade", {}).get(str(item.pk)) or run.coefficients.get("agrupado")
    obs = [1 if r >= run.coefficients.get("acerto_minimo", CORRECT) else 0 for r in
           SkillEvidence.objects.filter(student=student, item=item, ratio__isnull=False, weight__gt=0)
           .order_by("observed_on", "pk").values_list("ratio", flat=True)]
    if not obs or not p:
        return None
    preds = predict_sequence(obs + [1], p)
    return {"p": preds[-1], "n": len(obs), "run": run}
